"""Finance Observer - FastAPI application entry point."""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from app.core.config import get_config
from app.services.alert_service import AlertManager
from app.services.observer_service import SiteObserver
from app.services.postgres_service import PostgresService
from app.services.redis_service import RedisService
from app.api.v1 import api as api_v1
from app.api.v1.endpoints import alerts as alerts_endpoints
from app.api.v1.endpoints import data as data_endpoints

# Load environment variables from .env file
load_dotenv()

# Configure logging with local time
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.Formatter.converter = time.localtime
logger = logging.getLogger(__name__)

# Initialize configuration
config = get_config()

# Initialize FastAPI app
app = FastAPI(
    title="Finance Observer",
    description="Real-time forex currency pair price monitoring with price alerts",
    version="1.0.0"
)


@app.middleware("http")
async def normalize_paths(request, call_next):
    path = request.url.path
    stripped = path.rstrip()
    if stripped != path:
        return RedirectResponse(url=stripped, status_code=307)
    if path in {"/Historical", "/Snapshot"}:
        return RedirectResponse(url=path.lower(), status_code=307)
    return await call_next(request)

# Global state
observer: SiteObserver | None = None
observers: list[SiteObserver] = []
alert_manager: AlertManager = AlertManager()
background_task: asyncio.Task | None = None
data_stream_task: asyncio.Task | None = None
archive_task: asyncio.Task | None = None
cleanup_task: asyncio.Task | None = None
redis_service: RedisService | None = None
postgres_service: PostgresService | None = None

# Initialize services
sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
if sendgrid_api_key:
    logger.info("SendGrid email service initialized")
else:
    logger.warning("SENDGRID_API_KEY not set, email alerts disabled")

af_username = os.getenv("AFRICASTALKING_USERNAME")
af_api_key = os.getenv("AFRICASTALKING_API_KEY")
if af_username and af_api_key:
    logger.info("Africa's Talking SMS service initialized")
else:
    logger.warning("AFRICASTALKING credentials not set, SMS alerts disabled")

twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_from_number = os.getenv("TWILIO_FROM_NUMBER")
if twilio_account_sid and twilio_auth_token and twilio_from_number:
    logger.info("Twilio call service initialized")
else:
    logger.warning("TWILIO credentials not set, call alerts disabled")


@app.on_event("startup")
async def on_startup():
    """Initialize the observer on application startup."""
    global observer, observers, background_task, data_stream_task, archive_task, cleanup_task
    global redis_service, postgres_service
    logger.info("Starting Finance Observer application...")
    
    try:
        redis_service = RedisService(
            url=config.redis_url,
            channel=config.redis_channel,
            latest_key=config.redis_latest_key,
            queue_key=config.redis_queue_key,
            recent_key=config.redis_recent_key,
            recent_maxlen=config.redis_recent_maxlen,
            socket_connect_timeout_seconds=config.redis_socket_connect_timeout_seconds,
            socket_timeout_seconds=config.redis_socket_timeout_seconds,
            retry_max_attempts=config.redis_retry_max_attempts,
            retry_base_delay_seconds=config.redis_retry_base_delay_seconds,
            retry_max_delay_seconds=config.redis_retry_max_delay_seconds,
        )
        try:
            await redis_service.connect()
        except Exception as e:
            logger.warning("Redis unavailable: %s", e)
            redis_service = None

        postgres_service = PostgresService(
            config.postgres_dsn,
            maintenance_db=config.postgres_maintenance_db,
        )
        try:
            await postgres_service.connect()
            await postgres_service.init_models()
        except Exception as e:
            logger.warning("PostgreSQL unavailable: %s", e)
            postgres_service = None

        observers = []
        for source in config.sources:
            source_name = str(source.get("name", "default"))
            source_observer = SiteObserver(
                url=source.get("url", config.url),
                table_selector=source.get("tableSelector", config.table_selector),
                pair_cell_selector=source.get("pairCellSelector", config.pair_cell_selector),
                wait_selector=source.get("waitSelector", config.wait_selector),
                inject_mutation_observer=bool(
                    source.get("injectMutationObserver", config.inject_mutation_observer)
                ),
                filter_by_majors=bool(source.get("filterByMajors", True)),
                source_name=source_name,
            )
            try:
                await source_observer.startup()
                observers.append(source_observer)
                logger.info("Observer '%s' started successfully", source_name)
            except Exception as e:
                logger.error(
                    "Observer '%s' initial startup failed (%s). "
                    "Continuing startup in degraded mode.",
                    source_name,
                    e,
                )

        observer = observers[0] if observers else None
        
        # Set instances for endpoint handlers
        alerts_endpoints.set_alert_manager(alert_manager)
        data_endpoints.set_observers(observers)
        data_endpoints.set_observer(observer)
        data_endpoints.set_alert_manager(alert_manager)
        data_endpoints.set_config(config.stream_interval_seconds, config.majors)
        data_endpoints.set_runtime_tuning(
            config.snapshot_timeout_seconds,
            config.ws_send_timeout_seconds,
            config.alert_action_timeout_seconds,
            config.max_snapshot_failures,
        )
        data_endpoints.set_redis_service(redis_service, config.redis_pubsub_enabled)
        data_endpoints.set_postgres_service(postgres_service)
        data_endpoints.set_archive_config(
            config.archive_interval_seconds,
            config.archive_batch_size,
        )
        
        # Start background alert monitoring task FIRST to ensure it subscribes 
        # before data streaming begins broadcasting
        background_task = asyncio.create_task(data_endpoints.alert_monitoring_task())
        logger.info("Background alert monitoring task started")
        
        # Give alert monitor a moment to subscribe
        await asyncio.sleep(0.1)
        
        # Start central data streaming task
        data_stream_task = asyncio.create_task(data_endpoints.data_streaming_task())
        logger.info("Central data streaming task started")

        if redis_service and postgres_service:
            archive_task = asyncio.create_task(data_endpoints.archive_snapshots_task())
            logger.info("Archive task started")

        if postgres_service:
          cleanup_task = asyncio.create_task(data_endpoints.retention_cleanup_task())
          logger.info("Retention cleanup task started")
    except Exception as e:
        logger.error(f"Failed to start observer: {e}")
        raise


@app.on_event("shutdown")
async def on_shutdown():
    """Clean up resources on application shutdown."""
    global background_task, data_stream_task, archive_task, cleanup_task
    global redis_service, postgres_service
    
    logger.info("Shutting down Finance Observer...")
    
    # Cancel background tasks
    if background_task:
        logger.info("Cancelling background alert monitoring task...")
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
        logger.info("Background task cancelled")
    
    if data_stream_task:
        logger.info("Cancelling data streaming task...")
        data_stream_task.cancel()
        try:
            await data_stream_task
        except asyncio.CancelledError:
            pass
        logger.info("Data streaming task cancelled")

    if archive_task:
        logger.info("Cancelling archive task...")
        archive_task.cancel()
        try:
            await archive_task
        except asyncio.CancelledError:
            pass
        logger.info("Archive task cancelled")

    if cleanup_task:
        logger.info("Cancelling retention cleanup task...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Retention cleanup task cancelled")
    
    for obs in observers:
        logger.info("Shutting down observer '%s'...", getattr(obs, "source_name", "default"))
        try:
            await obs.shutdown()
            logger.info("Observer '%s' shutdown complete", getattr(obs, "source_name", "default"))
        except Exception as e:
            logger.error("Error during observer shutdown: %s", e)

    if redis_service:
        try:
            await redis_service.close()
        except Exception as e:
            logger.error("Error closing Redis: %s", e)

    if postgres_service:
        try:
            await postgres_service.close()
        except Exception as e:
            logger.error("Error closing PostgreSQL: %s", e)
    
    logger.info("Finance Observer shutdown complete")


# ─── Liveness & readiness health endpoint ───────────────────────────────────

_app_start_time: float = time.monotonic()

@app.get("/health", tags=["monitoring"])
async def health_check():
    """Comprehensive liveness probe.

    Returns 200 + status="ok" when all subsystems are healthy.
    Returns 503 + status="degraded" when non-critical components are unavailable.
    Returns 503 + status="down"    when the observer or stream is broken.
    """
    checks: dict = {}
    overall = "ok"

    # 1. Process uptime
    checks["uptime_seconds"] = round(time.monotonic() - _app_start_time, 1)

    # 2. Observer / browser
    obs_ready = any(
        obs.browser is not None and obs.page is not None
        for obs in observers
    )
    checks["observer"] = "up" if obs_ready else "down"
    if not obs_ready:
        overall = "down"

    # 3. Background tasks
    checks["stream_task"] = (
        "up" if data_stream_task and not data_stream_task.done() else "down"
    )
    checks["alert_task"] = (
        "up" if background_task and not background_task.done() else "down"
    )
    checks["cleanup_task"] = (
        "up" if cleanup_task and not cleanup_task.done() else "unavailable"
    )
    if checks["stream_task"] == "down":
        overall = "down"

    # 4. Redis ping (non-blocking, 1 s timeout)
    if redis_service and redis_service._client:
        try:
            await asyncio.wait_for(redis_service._client.ping(), timeout=1.0)
            checks["redis"] = "up"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            if overall == "ok":
                overall = "degraded"
    else:
        checks["redis"] = "unavailable"
        if overall == "ok":
            overall = "degraded"

    # 5. PostgreSQL ping (non-blocking, 1 s timeout)
    if postgres_service and postgres_service._engine:
        try:
            async def _pg_ping():
                async with postgres_service._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            await asyncio.wait_for(_pg_ping(), timeout=1.0)
            checks["postgres"] = "up"
        except Exception as e:
            checks["postgres"] = f"error: {e}"
            if overall == "ok":
                overall = "degraded"
    else:
        checks["postgres"] = "unavailable"
        if overall == "ok":
            overall = "degraded"

    # 6. Stream health snapshot
    stream_failures = getattr(data_endpoints, "snapshot_failure_count", None)
    last_ts = getattr(data_endpoints, "last_snapshot_ts", None)
    checks["stream_failures"] = stream_failures
    checks["last_snapshot_ts"] = last_ts
    if stream_failures is not None and stream_failures >= getattr(data_endpoints, "MAX_SNAPSHOT_FAILURES", 4):
        overall = "down"

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        {
            "status": overall,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        },
        status_code=status_code,
    )


@app.get("/ping", tags=["monitoring"])
async def ping():
    """Minimal TCP-level liveness probe — always returns 200 if the process is alive."""
    return JSONResponse({"pong": True})


# ─── Live monitoring dashboard ────────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Finance Observer — Live Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
    --text: #e2e8f0; --muted: #94a3b8;
    --green: #22c55e; --yellow: #f59e0b; --red: #ef4444;
    --blue: #3b82f6; --purple: #a855f7;
    --chart-h: 220px;
  }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 14px; min-height: 100vh; }

  /* ── Banner ── */
  #banner {
    padding: 14px 24px; font-weight: 700; font-size: 15px;
    display: flex; align-items: center; gap: 10px;
    transition: background 0.4s;
  }
  #banner .dot { width: 10px; height: 10px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
  #banner.ok   { background: #052e16; color: var(--green); }
  #banner.degraded { background: #1c1003; color: var(--yellow); }
  #banner.down { background: #1f0202; color: var(--red); }
  #banner.loading { background: var(--surface); color: var(--muted); }

  /* ── Layout ── */
  .container { max-width: 1280px; margin: 0 auto; padding: 24px 20px; }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 20px; letter-spacing: -0.3px; }

  /* ── Status grid ── */
  .status-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 28px;
  }
  .status-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px;
    display: flex; flex-direction: column; gap: 6px;
  }
  .status-card .label { font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
  .status-card .value { font-size: 18px; font-weight: 700; }
  .status-card .pill {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 12px; font-weight: 600; padding: 2px 8px;
    border-radius: 999px; width: fit-content;
  }
  .pill.up   { background: #052e164f; color: var(--green); }
  .pill.down { background: #1f02024f; color: var(--red); }
  .pill.degraded { background: #1c10034f; color: var(--yellow); }

  /* ── Charts ── */
  .charts-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 16px; margin-bottom: 20px;
  }
  .chart-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px;
  }
  .chart-card h3 { font-size: 13px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 12px; }
  .chart-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
  .chart-head h3 { margin-bottom: 0; }
  .chart-card.chart-wide { grid-column: 1 / -1; }
  .perf-controls { display: flex; align-items: center; gap: 8px; }
  .perf-controls button {
    border: 1px solid var(--border); background: transparent; color: var(--muted);
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
    padding: 4px 8px; border-radius: 6px; cursor: pointer;
  }
  .perf-controls button.active { color: var(--text); border-color: var(--blue); }
  #perf-summary { font-size: 12px; color: var(--muted); min-width: 140px; text-align: right; }
  .chart-wrap { height: var(--chart-h); position: relative; }

  /* ── Pairs table ── */
  .pairs-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 20px;
  }
  .pairs-card h3 { font-size: 13px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    padding: 6px 10px; border-bottom: 1px solid var(--border); }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  .up-pct   { color: var(--green); font-weight: 600; }
  .down-pct { color: var(--red);   font-weight: 600; }

  /* ── Footer ── */
  .footer { font-size: 11px; color: var(--muted); text-align: center;
    padding-top: 12px; display: flex; gap: 20px; justify-content: center; }
  .footer span { display: flex; align-items: center; gap: 4px; }
  #last-updated { }
</style>
</head>
<body>

<div id="banner" class="loading">
  <span class="dot"></span>
  <span id="banner-text">Connecting…</span>
</div>

<div class="container">
  <h1>Finance Observer — Live Dashboard</h1>

  <!-- ── Status cards ── -->
  <div class="status-grid">
    <div class="status-card">
      <span class="label">Overall</span>
      <span id="c-status" class="value">—</span>
    </div>
    <div class="status-card">
      <span class="label">Observer</span>
      <span id="c-observer" class="pill">—</span>
    </div>
    <div class="status-card">
      <span class="label">Stream Task</span>
      <span id="c-stream-task" class="pill">—</span>
    </div>
    <div class="status-card">
      <span class="label">Alert Task</span>
      <span id="c-alert-task" class="pill">—</span>
    </div>
    <div class="status-card">
      <span class="label">Redis</span>
      <span id="c-redis" class="pill">—</span>
    </div>
    <div class="status-card">
      <span class="label">PostgreSQL</span>
      <span id="c-postgres" class="pill">—</span>
    </div>
    <div class="status-card">
      <span class="label">Uptime</span>
      <span id="c-uptime" class="value">—</span>
    </div>
    <div class="status-card">
      <span class="label">WS Subscribers</span>
      <span id="c-subscribers" class="value">—</span>
    </div>
    <div class="status-card">
      <span class="label">Stream Failures</span>
      <span id="c-failures" class="value">—</span>
    </div>
    <div class="status-card">
      <span class="label">Snapshot Age</span>
      <span id="c-age" class="value">—</span>
    </div>
    <div class="status-card">
      <span class="label">Overall Performance (7d)</span>
      <span id="c-performance" class="value">—</span>
    </div>
  </div>

  <!-- ── Charts ── -->
  <div class="charts-grid">
    <div class="chart-card">
      <h3>Snapshot Age (seconds)</h3>
      <div class="chart-wrap"><canvas id="chart-age"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Consecutive Failures</h3>
      <div class="chart-wrap"><canvas id="chart-failures"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>WebSocket Subscribers</h3>
      <div class="chart-wrap"><canvas id="chart-subs"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>Subscribers: Live vs Persisted</h3>
      <div class="chart-wrap"><canvas id="chart-subs-persisted"></canvas></div>
    </div>
    <div class="chart-card chart-wide">
      <div class="chart-head">
        <h3>System Performance Trend</h3>
        <div class="perf-controls">
          <button id="perf-24h" type="button" data-window="24h">24h</button>
          <button id="perf-7d" type="button" data-window="7d" class="active">7d</button>
          <span id="perf-summary">Overall: —</span>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="chart-performance"></canvas></div>
    </div>
    <div class="chart-card chart-wide">
      <h3>Downtime by Hour of Day (UTC)</h3>
      <div class="chart-wrap"><canvas id="chart-downtime-hour"></canvas></div>
    </div>
  </div>

  <!-- ── FX Pairs table ── -->
  <div class="pairs-card">
    <h3>Latest Market Snapshot</h3>
    <table>
      <thead><tr><th>Market</th><th>Pair</th><th>Price</th><th>Change %</th></tr></thead>
      <tbody id="pairs-tbody"><tr><td colspan="4" style="color:var(--muted)">Waiting for snapshot…</td></tr></tbody>
    </table>
  </div>

  <div class="footer">
    <span>Auto-refresh: <strong>5 s</strong></span>
    <span>Last updated: <strong id="last-updated">—</strong></span>
  </div>
</div>

<script>
const POINTS = 60;  // rolling window (60 × 5 s = 5 min)
const POLL_MS = 5000;
const PERF_POINTS = 1000;
let wsSocket = null;
let wsBackoffMs = 1000;
let wsReconnectTimer = null;

// ── Chart defaults ──────────────────────────────────────────────────────────
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#2a2d3e';

function makeChart(id, label, color, yMin) {
  const ctx = document.getElementById(id).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: color,
        backgroundColor: color + '1a',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.35,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { maxTicksLimit: 6, maxRotation: 0, font: { size: 10 } },
          grid: { display: false },
        },
        y: {
          min: yMin !== undefined ? yMin : undefined,
          ticks: { font: { size: 10 } },
          grid: { color: '#2a2d3e' },
        }
      }
    }
  });
}

const chartAge  = makeChart('chart-age',      'Age (s)',    '#f59e0b', 0);
const chartFail = makeChart('chart-failures', 'Failures',   '#ef4444', 0);
const chartSubs = makeChart('chart-subs',     'Subscribers','#3b82f6', 0);
const chartSubsPersisted = new Chart(document.getElementById('chart-subs-persisted').getContext('2d'), {
  type: 'line',
  data: {
    datasets: [
      {
        label: 'Live',
        data: [],
        borderColor: '#3b82f6',
        backgroundColor: '#3b82f61a',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.25,
      },
      {
        label: 'Persisted',
        data: [],
        borderColor: '#a855f7',
        backgroundColor: '#a855f71a',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.25,
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: { legend: { display: true } },
    parsing: false,
    scales: {
      x: {
        type: 'linear',
        ticks: {
          maxTicksLimit: 6,
          callback: (v) => {
            const d = new Date(Number(v));
            return d.getHours().toString().padStart(2, '0') + ':' +
                   d.getMinutes().toString().padStart(2, '0') + ':' +
                   d.getSeconds().toString().padStart(2, '0');
          },
          font: { size: 10 },
        },
        grid: { display: false },
      },
      y: {
        min: 0,
        ticks: { font: { size: 10 } },
        grid: { color: '#2a2d3e' },
      }
    }
  }
});

const chartPerformance = new Chart(document.getElementById('chart-performance').getContext('2d'), {
  type: 'line',
  data: {
    datasets: [
      {
        label: 'Overall Performance %',
        data: [],
        borderColor: '#22c55e',
        backgroundColor: '#22c55e1a',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.25,
        yAxisID: 'y',
      },
      {
        label: 'Snapshot Failures',
        data: [],
        borderColor: '#ef4444',
        backgroundColor: '#ef44441a',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.25,
        yAxisID: 'y1',
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 250 },
    parsing: false,
    scales: {
      x: {
        type: 'linear',
        ticks: {
          maxTicksLimit: 8,
          callback: (v) => {
            const d = new Date(Number(v));
            return d.getMonth() + 1 + '/' + d.getDate() + ' ' +
                   d.getHours().toString().padStart(2, '0') + ':' +
                   d.getMinutes().toString().padStart(2, '0');
          },
          font: { size: 10 },
        },
        grid: { display: false },
      },
      y: {
        min: 0,
        max: 100,
        ticks: { font: { size: 10 }, callback: (v) => v + '%' },
        grid: { color: '#2a2d3e' },
      },
      y1: {
        position: 'right',
        min: 0,
        ticks: { font: { size: 10 } },
        grid: { drawOnChartArea: false },
      }
    }
  }
});

const chartDowntimeHour = new Chart(document.getElementById('chart-downtime-hour').getContext('2d'), {
  type: 'bar',
  data: {
    labels: Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0') + ':00'),
    datasets: [
      {
        label: 'Downtime Events',
        data: Array(24).fill(0),
        borderColor: '#f97316',
        backgroundColor: '#f9731633',
        borderWidth: 1,
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 250 },
    plugins: { legend: { display: false } },
    scales: {
      x: {
        ticks: { maxTicksLimit: 12, maxRotation: 0, font: { size: 10 } },
        grid: { display: false },
      },
      y: {
        min: 0,
        ticks: { precision: 0, font: { size: 10 } },
        grid: { color: '#2a2d3e' },
      }
    }
  }
});

const perfState = {
  window: '7d',
};

// ── Helpers ─────────────────────────────────────────────────────────────────
function push(chart, label, value) {
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > POINTS) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update('none');
}

function pushTsPoint(dataset, tsMs, value, maxPoints) {
  dataset.push({ x: tsMs, y: value });
  if (dataset.length > maxPoints) {
    dataset.shift();
  }
}

function timeLabel() {
  const d = new Date();
  return d.getHours().toString().padStart(2,'0') + ':' +
         d.getMinutes().toString().padStart(2,'0') + ':' +
         d.getSeconds().toString().padStart(2,'0');
}

function pill(el, state) {
  el.className = 'pill ' + (state === 'up' ? 'up' : state === 'down' ? 'down' : 'degraded');
  el.textContent = state;
}

function fmtUptime(s) {
  if (s == null) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function normalizeRows(data) {
  if (!data || typeof data !== 'object') {
    return [];
  }

  if (Array.isArray(data.pairs)) {
    return data.pairs.map((row) => ({ ...row, market: row.market || row.source || 'currencies' }));
  }

  const grouped = data.pairs && typeof data.pairs === 'object' ? data.pairs : {};
  const currencies = Array.isArray(grouped.currencies)
    ? grouped.currencies.map((row) => ({ ...row, market: 'currencies' }))
    : [];
  const commodities = Array.isArray(grouped.commodities)
    ? grouped.commodities.map((row) => ({ ...row, market: 'commodities' }))
    : [];

  return currencies.concat(commodities);
}

function parseNumber(raw) {
  if (raw == null) return null;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw !== 'string') return null;
  const cleaned = raw.replace(/,/g, '').trim();
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function performanceFromMetric(metric) {
  const status = String(metric.stream_status || '').toLowerCase();
  const failures = Number(metric.snapshot_failure_count ?? 0);
  const base = status === 'healthy' ? 100 : status === 'degraded' ? 78 : status === 'stale' ? 40 : status === 'market_closed' ? 60 : 70;
  const penalty = Math.min(Math.max(0, failures) * 5, 50);
  return Math.max(0, Math.min(100, base - penalty));
}

function isDowntimeMetric(metric) {
  const status = String(metric.stream_status || '').toLowerCase();
  if (status === 'market_closed') {
    return false;
  }
  return status !== 'healthy';
}

async function resolveWsUrl() {
  try {
    const res = await fetch('/client-config');
    if (res.ok) {
      const cfg = await res.json();
      if (cfg && typeof cfg.wsUrl === 'string' && cfg.wsUrl.trim()) {
        return cfg.wsUrl.trim();
      }
    }
  } catch (_) {}

  const proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
  return proto + window.location.host + '/ws/observe';
}

function scheduleWsReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    connectWs();
  }, wsBackoffMs);
  wsBackoffMs = Math.min(wsBackoffMs * 2, 10000);
}

async function connectWs() {
  const url = await resolveWsUrl();

  try {
    wsSocket = new WebSocket(url);
  } catch (_) {
    scheduleWsReconnect();
    return;
  }

  wsSocket.onopen = () => {
    wsBackoffMs = 1000;
  };

  wsSocket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleMarketPayload(data);
    } catch (_) {}
  };

  wsSocket.onclose = () => {
    scheduleWsReconnect();
  };

  wsSocket.onerror = () => {
    try { wsSocket && wsSocket.close(); } catch (_) {}
  };
}

// ── Banner ───────────────────────────────────────────────────────────────────
function setBanner(status) {
  const banner = document.getElementById('banner');
  const text   = document.getElementById('banner-text');
  banner.className = 'loading';
  if (status === 'ok')       { banner.className = 'ok';       text.textContent = 'All systems operational'; }
  else if (status === 'degraded') { banner.className = 'degraded'; text.textContent = 'Degraded — some components unavailable'; }
  else if (status === 'down') { banner.className = 'down';    text.textContent = 'Down — observer or stream not running'; }
  else                        { banner.className = 'loading'; text.textContent = 'Connecting…'; }
}

// ── Fetch loop ────────────────────────────────────────────────────────────────
async function poll() {
  const ts = timeLabel();
  const tsMs = Date.now();

  try {
    const [hRes, sRes] = await Promise.all([
      fetch('/health'),
      fetch('/stream-health')
    ]);

    const h = await hRes.json();
    const s = await sRes.json();
    const c = h.checks || {};

    // Banner
    setBanner(h.status);

    // Status cards
    document.getElementById('c-status').textContent = h.status || '—';
    document.getElementById('c-status').style.color =
      h.status === 'ok' ? 'var(--green)' : h.status === 'degraded' ? 'var(--yellow)' : 'var(--red)';

    pill(document.getElementById('c-observer'),    c.observer    || 'down');
    pill(document.getElementById('c-stream-task'), c.stream_task || 'down');
    pill(document.getElementById('c-alert-task'),  c.alert_task  || 'down');

    const redisSt = (c.redis || 'down').startsWith('up') ? 'up' : (c.redis || '').startsWith('error') ? 'down' : 'down';
    pill(document.getElementById('c-redis'),    redisSt);
    const pgSt = (c.postgres || 'down').startsWith('up') ? 'up' : (c.postgres || '').startsWith('error') ? 'down' : 'down';
    pill(document.getElementById('c-postgres'), pgSt);

    document.getElementById('c-uptime').textContent = fmtUptime(c.uptime_seconds);

    // Stream-health fields
    const age   = s.last_snapshot_age_seconds;
    const fails = s.consecutive_snapshot_failures;
    const subs  = s.subscriber_count;

    document.getElementById('c-subscribers').textContent = subs != null ? subs : '—';
    document.getElementById('c-failures').textContent    = fails != null ? fails : '—';
    document.getElementById('c-age').textContent         = age   != null ? age.toFixed(1) + ' s' : '—';

    // Charts
    push(chartAge,  ts, age   != null ? parseFloat(age.toFixed(2))  : null);
    push(chartFail, ts, fails != null ? fails : null);
    push(chartSubs, ts, subs  != null ? subs  : null);

    pushTsPoint(chartSubsPersisted.data.datasets[0].data, tsMs, subs != null ? subs : 0, POINTS);
    chartSubsPersisted.update('none');

    document.getElementById('last-updated').textContent = ts;

  } catch (err) {
    setBanner(null);
    console.warn('Poll error:', err);
  }

  // Persisted metrics trend (best-effort)
  try {
    const hist = await fetch('/historical/stream-metrics?limit=60&order=desc');
    if (hist.ok) {
      const payload = await hist.json();
      renderPersistedSubscriberTrend(payload);
    }
  } catch (_) {}
}

function handleMarketPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return;
  }
  renderPairs(payload);
}

function renderPairs(data) {
  const tbody = document.getElementById('pairs-tbody');
  if (!data || typeof data !== 'object') {
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">No data</td></tr>';
    return;
  }

  const rows = normalizeRows(data);
  if (rows.length === 0) {
    const msg = data.error ? 'No fresh snapshot: ' + data.error : 'No pair rows in snapshot';
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">' + msg + '</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((info) => {
    const pair = info.pair || '—';
    const market = info.market === 'commodities' ? 'commodities' : 'currencies';
    const parsedPrice = parseNumber(info.price);
    const price = parsedPrice != null
      ? (market === 'currencies' ? parsedPrice.toFixed(5) : parsedPrice.toLocaleString(undefined, { maximumFractionDigits: 4 }))
      : (info.price ?? '—');
    const change = parseNumber(info.change);
    const chgCell = change == null ? '<td>—</td>'
      : change >= 0
        ? '<td class="up-pct">+' + change.toFixed(2) + '%</td>'
        : '<td class="down-pct">' + change.toFixed(2) + '%</td>';
    return '<tr><td>' + market + '</td><td>' + pair + '</td><td>' + price + '</td>' + chgCell + '</tr>';
  }).join('');
}

function renderPersistedSubscriberTrend(payload) {
  if (!payload || !Array.isArray(payload.items)) {
    return;
  }

  const points = payload.items
    .slice()
    .reverse()
    .map((item) => {
      const x = new Date(item.observed_at).getTime();
      const y = Number(item.ws_subscriber_count ?? 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return null;
      }
      return { x, y };
    })
    .filter(Boolean);

  chartSubsPersisted.data.datasets[1].data = points;
  chartSubsPersisted.update('none');
}

async function refreshPerformanceChart() {
  const end = new Date();
  const start = new Date(end.getTime() - (perfState.window === '24h' ? 24 : 24 * 7) * 60 * 60 * 1000);
  const query = '/historical/stream-metrics?order=asc&limit=5000&start=' +
    encodeURIComponent(start.toISOString()) + '&end=' + encodeURIComponent(end.toISOString());

  try {
    const res = await fetch(query);
    if (!res.ok) {
      return;
    }

    const payload = await res.json();
    const items = Array.isArray(payload.items) ? payload.items : [];

    const perfPoints = [];
    const failPoints = [];
    const downtimeByHour = Array(24).fill(0);
    let perfSum = 0;
    let perfCount = 0;

    for (const item of items) {
      const x = new Date(item.observed_at).getTime();
      if (!Number.isFinite(x)) continue;

      const score = performanceFromMetric(item);
      const failures = Number(item.snapshot_failure_count ?? 0);

      perfPoints.push({ x, y: score });
      failPoints.push({ x, y: Number.isFinite(failures) ? failures : 0 });

      if (isDowntimeMetric(item)) {
        const hour = new Date(item.observed_at).getUTCHours();
        if (Number.isInteger(hour) && hour >= 0 && hour < 24) {
          downtimeByHour[hour] += 1;
        }
      }

      perfSum += score;
      perfCount += 1;
    }

    if (perfPoints.length > PERF_POINTS) {
      chartPerformance.data.datasets[0].data = perfPoints.slice(-PERF_POINTS);
      chartPerformance.data.datasets[1].data = failPoints.slice(-PERF_POINTS);
    } else {
      chartPerformance.data.datasets[0].data = perfPoints;
      chartPerformance.data.datasets[1].data = failPoints;
    }

    chartPerformance.update('none');
  chartDowntimeHour.data.datasets[0].data = downtimeByHour;
  chartDowntimeHour.update('none');

    const overall = perfCount > 0 ? (perfSum / perfCount) : null;
    const summary = document.getElementById('perf-summary');
    const card = document.getElementById('c-performance');

    if (overall == null) {
      summary.textContent = 'Overall: —';
      card.textContent = '—';
      card.style.color = 'var(--muted)';
      return;
    }

    const label = overall.toFixed(1) + '%';
    summary.textContent = 'Overall: ' + label;
    card.textContent = label;
    card.style.color = overall >= 85 ? 'var(--green)' : overall >= 65 ? 'var(--yellow)' : 'var(--red)';
  } catch (_) {}
}

function setPerfWindow(windowKey) {
  perfState.window = windowKey;
  document.getElementById('perf-24h').classList.toggle('active', windowKey === '24h');
  document.getElementById('perf-7d').classList.toggle('active', windowKey === '7d');
  refreshPerformanceChart();
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.getElementById('perf-24h').addEventListener('click', () => setPerfWindow('24h'));
document.getElementById('perf-7d').addEventListener('click', () => setPerfWindow('7d'));

connectWs();
poll();
setInterval(poll, POLL_MS);
refreshPerformanceChart();
setInterval(refreshPerformanceChart, 60000);
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse, tags=["monitoring"])
async def dashboard():
    """Live monitoring dashboard — auto-refreshing line graphs for all subsystems."""
    return HTMLResponse(content=_DASHBOARD_HTML)


# ─── API routers ──────────────────────────────────────────────────────────────

# Include API routers
app.include_router(api_v1.router)

# Add data endpoints at root level (for /snapshot, /client-config, /stream-health, /ws/observe)
app.include_router(data_endpoints.router)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
