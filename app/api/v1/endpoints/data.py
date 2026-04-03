"""Data streaming and observation endpoints."""
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.services.observer_service import SiteObserver
from app.services.alert_service import AlertManager
from app.services.redis_service import RedisService
from app.services.postgres_service import PostgresService
from app.utils.forex_market_hours import is_forex_market_open, get_time_until_market_opens

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["data"],
    responses={503: {"description": "Service unavailable"}},
)

# Global instances
observer: SiteObserver = None
observers: List[SiteObserver] = []
alert_manager: AlertManager = None
data_subscribers: List[asyncio.Queue] = []
latest_data: Dict[str, Any] = {}
redis_service: Optional[RedisService] = None
postgres_service: Optional[PostgresService] = None

# Configuration
STREAM_INTERVAL = 1.0
MAJORS = []
REDIS_PUBSUB_ENABLED = True
ARCHIVE_INTERVAL = 30.0
ARCHIVE_BATCH_SIZE = 200
SNAPSHOT_TIMEOUT_SECONDS = 8.0
WS_SEND_TIMEOUT_SECONDS = 3.0
ALERT_ACTION_TIMEOUT_SECONDS = 8.0
MAX_SNAPSHOT_FAILURES = 4
METRICS_PERSIST_INTERVAL_SECONDS = 30.0
RETENTION_DAYS = 14
RETENTION_CHECK_INTERVAL_SECONDS = 60.0
RETENTION_TRIGGER_WEEKDAY_UTC = 6
RETENTION_TRIGGER_HOUR_UTC = 22
RETENTION_TRIGGER_MINUTE_WINDOW = 5

snapshot_failure_count = 0
last_snapshot_ts: Optional[str] = None
_observer_restart_lock = asyncio.Lock()
_active_ws_connections = 0
_last_metrics_persist_at = 0.0
retention_cleanup_last_run_at: Optional[str] = None
retention_cleanup_last_result: Dict[str, Any] = {}
_retention_cleanup_last_run_key: Optional[str] = None


def _is_retention_cleanup_window(now_utc: datetime) -> bool:
    return (
        now_utc.weekday() == RETENTION_TRIGGER_WEEKDAY_UTC
        and now_utc.hour == RETENTION_TRIGGER_HOUR_UTC
        and now_utc.minute < RETENTION_TRIGGER_MINUTE_WINDOW
    )


def _next_retention_cleanup_at(now_utc: datetime) -> datetime:
    base = now_utc.astimezone(timezone.utc)
    target = base.replace(
        hour=RETENTION_TRIGGER_HOUR_UTC,
        minute=0,
        second=0,
        microsecond=0,
    )
    days_ahead = (RETENTION_TRIGGER_WEEKDAY_UTC - base.weekday()) % 7
    target = target + timedelta(days=days_ahead)
    if target <= base:
        target = target + timedelta(days=7)
    return target


def _get_active_subscriber_count() -> int:
    return max(0, _active_ws_connections)


async def _persist_stream_metric_if_due(status: str) -> None:
    global _last_metrics_persist_at
    if not postgres_service:
        return

    now = time.monotonic()
    if now - _last_metrics_persist_at < METRICS_PERSIST_INTERVAL_SECONDS:
        return

    try:
        await postgres_service.insert_stream_metric(
            observed_at=datetime.now(timezone.utc),
            ws_subscriber_count=_get_active_subscriber_count(),
            queue_subscriber_count=len(data_subscribers),
            snapshot_failure_count=snapshot_failure_count,
            stream_status=status,
        )
        _last_metrics_persist_at = now
    except Exception as e:
        logger.error("Failed to persist stream metrics: %s", e)


def set_observer(obs: SiteObserver):
    """Set the global observer instance."""
    global observer
    observer = obs


def set_observers(obs_list: List[SiteObserver]):
    """Set all observer instances."""
    global observers, observer
    observers = obs_list or []
    observer = observers[0] if observers else None


def set_alert_manager(manager: AlertManager):
    """Set the global alert manager instance."""
    global alert_manager
    alert_manager = manager


def set_config(stream_interval: float, majors: List[str]):
    """Set configuration."""
    global STREAM_INTERVAL, MAJORS
    STREAM_INTERVAL = stream_interval
    MAJORS = majors


def _active_observers() -> List[SiteObserver]:
    if observers:
        return observers
    if observer:
        return [observer]
    return []


async def _collect_snapshot_from_observers() -> Dict[str, Any]:
    active = _active_observers()
    if not active:
        raise RuntimeError("Observer not ready")

    tasks = [
        asyncio.wait_for(obs.snapshot(MAJORS), timeout=SNAPSHOT_TIMEOUT_SECONDS)
        for obs in active
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged_pairs: List[Dict[str, Any]] = []
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    merged_majors = set()
    merged_titles: List[str] = []
    merged_changes: List[str] = []
    merged_samples: List[str] = []
    successful_snapshots = 0
    timeout_failures = 0

    for obs, result in zip(active, results):
        source_name = str(getattr(obs, "source_name", "default"))
        if isinstance(result, Exception):
            if isinstance(result, asyncio.TimeoutError):
                timeout_failures += 1
            logger.error(
                "Snapshot failed for observer '%s': %s",
                source_name,
                result,
            )
            continue

        successful_snapshots += 1

        pairs = result.get("pairs") or []
        if pairs:
            normalized_pairs = []
            for item in pairs:
                normalized_pairs.append(dict(item))
            merged_pairs.extend(normalized_pairs)
            by_source[source_name] = normalized_pairs
        merged_majors.update(result.get("majors") or [])
        title = result.get("title")
        if title:
            merged_titles.append(title)
        merged_changes.extend(result.get("changes") or [])
        merged_samples.extend(result.get("pairsSample") or [])

    if successful_snapshots == 0 and timeout_failures > 0:
        raise asyncio.TimeoutError("All observers timed out")

    return {
        "title": " | ".join(dict.fromkeys(merged_titles)),
        "majors": sorted(merged_majors),
        "pairs": merged_pairs,
        "sources": by_source,
        "pairsSample": merged_samples[:10],
        "changes": merged_changes,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _split_pairs_by_source(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    explicit = data.get("sources")
    if isinstance(explicit, dict):
        return {
            str(name): list(items or [])
            for name, items in explicit.items()
            if isinstance(items, list)
        }

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in data.get("pairs", []):
        source_name = str(item.get("source") or "default")
        grouped.setdefault(source_name, []).append(item)
    return grouped


def set_redis_service(service: Optional[RedisService], pubsub_enabled: bool):
    """Set the Redis service instance."""
    global redis_service, REDIS_PUBSUB_ENABLED
    redis_service = service
    REDIS_PUBSUB_ENABLED = pubsub_enabled


def set_postgres_service(service: Optional[PostgresService]):
    """Set the PostgreSQL service instance."""
    global postgres_service
    postgres_service = service


def set_archive_config(interval_seconds: float, batch_size: int):
    """Set archival task configuration."""
    global ARCHIVE_INTERVAL, ARCHIVE_BATCH_SIZE
    ARCHIVE_INTERVAL = interval_seconds
    ARCHIVE_BATCH_SIZE = batch_size


def set_runtime_tuning(
    snapshot_timeout_seconds: float,
    ws_send_timeout_seconds: float,
    alert_action_timeout_seconds: float,
    max_snapshot_failures: int,
):
    """Set runtime resiliency tuning values."""
    global SNAPSHOT_TIMEOUT_SECONDS, WS_SEND_TIMEOUT_SECONDS
    global ALERT_ACTION_TIMEOUT_SECONDS, MAX_SNAPSHOT_FAILURES
    SNAPSHOT_TIMEOUT_SECONDS = max(1.0, float(snapshot_timeout_seconds))
    WS_SEND_TIMEOUT_SECONDS = max(0.5, float(ws_send_timeout_seconds))
    ALERT_ACTION_TIMEOUT_SECONDS = max(1.0, float(alert_action_timeout_seconds))
    MAX_SNAPSHOT_FAILURES = max(1, int(max_snapshot_failures))


@router.get("/snapshot")
async def snapshot():
    """Get a single snapshot of current forex data.
    
    Returns clean data format with only essential fields:
    - market_status: "open" or "closed"
    - pairs: currency pairs with prices
    - ts: timestamp
    """
    if not _active_observers():
        logger.warning("Snapshot requested but observer not ready")
        return JSONResponse({"error": "Observer not ready"}, status_code=503)

    # Prefer fresh streamed cache to avoid extra Playwright reads from dashboard polling.
    # This reduces contention with the central data stream task.
    cached_pairs = (latest_data or {}).get("pairs") or []
    cached_ts = (latest_data or {}).get("ts")
    if cached_pairs and cached_ts:
        try:
            parsed = datetime.fromisoformat(cached_ts)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
            if age_seconds <= max(5.0, STREAM_INTERVAL * 3):
                cached_sources = _split_pairs_by_source(latest_data or {})
                return JSONResponse(
                    {
                        "market_status": "open" if is_forex_market_open() else "closed",
                        "pairs": {
                            "currencies": cached_sources.get("currencies", []),
                            "commodities": cached_sources.get("commodities", []),
                        },
                        "ts": cached_ts,
                    }
                )
        except Exception:
            pass
    
    try:
        data = await _collect_snapshot_from_observers()
        pairs = data.get("pairs") or []
        if not pairs:
            logger.warning("Snapshot requested but source returned empty pairs")
            return JSONResponse({"error": "No fresh market data available"}, status_code=503)

        # Return clean format without alerts
        grouped_pairs = _split_pairs_by_source(data)

        clean_data = {
            "market_status": "open" if is_forex_market_open() else "closed",
            "pairs": {
                "currencies": grouped_pairs.get("currencies", []),
                "commodities": grouped_pairs.get("commodities", []),
            },
            "ts": data.get("ts")
        }
        return JSONResponse(clean_data)
    except asyncio.TimeoutError:
        logger.error(
            "Snapshot endpoint timed out after %.1fs",
            SNAPSHOT_TIMEOUT_SECONDS,
        )
        return JSONResponse({"error": "Snapshot request timed out"}, status_code=504)
    except Exception as e:
        logger.error(f"Error getting snapshot: {e}")
        return JSONResponse({"error": "Failed to get snapshot"}, status_code=500)


@router.get("/client-config")
async def client_config():
    """Serve client runtime configuration derived from environment.
    Allows overriding WebSocket URL when running behind proxies or differing hosts.
    """
    ws_url = os.getenv("WS_URL", "")
    return JSONResponse({
        "wsUrl": ws_url,  # e.g., "wss://your-domain/ws/observe" or "ws://ip:8000/ws/observe"
    })


@router.get("/stream-health")
async def stream_health():
    """Expose stream freshness and resilience counters."""
    last_snapshot_age_seconds = None
    if last_snapshot_ts:
        try:
            parsed = datetime.fromisoformat(last_snapshot_ts)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            last_snapshot_age_seconds = max(
                0.0,
                (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds(),
            )
        except Exception:
            last_snapshot_age_seconds = None

    status = "healthy"
    if snapshot_failure_count > 0:
        status = "degraded"
    if snapshot_failure_count >= MAX_SNAPSHOT_FAILURES:
        status = "stale"
    elif last_snapshot_age_seconds is None and snapshot_failure_count > 0:
        status = "stale"
    elif last_snapshot_age_seconds is not None and last_snapshot_age_seconds > max(5.0, STREAM_INTERVAL * 6):
        status = "stale"

    return JSONResponse(
        {
            "status": status,
            "stream_interval_seconds": STREAM_INTERVAL,
            "snapshot_timeout_seconds": SNAPSHOT_TIMEOUT_SECONDS,
            "max_snapshot_failures": MAX_SNAPSHOT_FAILURES,
            "consecutive_snapshot_failures": snapshot_failure_count,
            "last_snapshot_ts": last_snapshot_ts,
            "last_snapshot_age_seconds": last_snapshot_age_seconds,
            "subscriber_count": _get_active_subscriber_count(),
            "ws_subscriber_count": _get_active_subscriber_count(),
            "queue_subscriber_count": len(data_subscribers),
            "retention_days": RETENTION_DAYS,
            "retention_cleanup_schedule_utc": "Sunday 22:00",
            "retention_cleanup_last_run_at": retention_cleanup_last_run_at,
            "retention_cleanup_next_run_at": _next_retention_cleanup_at(
                datetime.now(timezone.utc)
            ).isoformat(),
            "retention_cleanup_last_result": retention_cleanup_last_result,
        }
    )


@router.websocket("/ws/observe")
async def ws_observe(ws: WebSocket):
    """WebSocket endpoint for streaming real-time forex data.

    Query params:
        interval: Optional candle timeframe (default: 1m)
        pair: Optional currency pair filter (default: all pairs)
    """
    global _active_ws_connections
    await ws.accept()
    connection_counted = False

    interval = (ws.query_params.get("interval") or "1m").strip().lower()
    valid_intervals = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    if interval not in valid_intervals:
        interval = "1m"

    pair_param = (ws.query_params.get("pair") or "").strip()
    requested_pair = None
    if pair_param:
        requested_pair = pair_param.split(",", 1)[0].strip().upper().replace("/", "") or None

    has_stream_params = (
        ws.query_params.get("interval") is not None
        or ws.query_params.get("pair") is not None
    )

    logger.info(
        "WebSocket stream requested: interval=%s pair=%s",
        interval,
        requested_pair or "all",
    )
    
    if not _active_observers():
        logger.warning("WebSocket connection but observer not ready")
        await ws.send_json({"error": "Observer not ready"})
        await ws.close()
        return

    _active_ws_connections += 1
    connection_counted = True
    logger.info(
        "WebSocket connection established: %s (active subscribers: %s)",
        ws.client,
        _get_active_subscriber_count(),
    )

    stop_event = asyncio.Event()
    disconnect_watcher = asyncio.create_task(_watch_ws_disconnect(ws, stop_event))

    try:
        if redis_service and REDIS_PUBSUB_ENABLED:
            logger.info("WebSocket %s using Redis pub/sub stream", ws.client)
            async for data in redis_service.subscribe(stop_event=stop_event):
                if stop_event.is_set():
                    break
                data = await _attach_stream_metadata(
                    data,
                    interval,
                    requested_pair,
                    include_alerts=not has_stream_params,
                )
                await asyncio.wait_for(
                    ws.send_json(data),
                    timeout=WS_SEND_TIMEOUT_SECONDS,
                )
        else:
            # Subscribe to data stream
            data_queue = asyncio.Queue(maxsize=50)
            data_subscribers.append(data_queue)
            logger.info(
                "WebSocket %s subscribed to data stream (total subscribers: %s)",
                ws.client,
                len(data_subscribers),
            )

            while not stop_event.is_set():
                # Get data from the central stream
                try:
                    data = await asyncio.wait_for(data_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                data = await _attach_stream_metadata(
                    data,
                    interval,
                    requested_pair,
                    include_alerts=not has_stream_params,
                )
                await asyncio.wait_for(
                    ws.send_json(data),
                    timeout=WS_SEND_TIMEOUT_SECONDS,
                )
    except asyncio.TimeoutError:
        logger.warning("WebSocket %s send timeout; closing slow consumer", ws.client)
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed: {ws.client}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        stop_event.set()
        disconnect_watcher.cancel()
        try:
            await disconnect_watcher
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

        if not (redis_service and REDIS_PUBSUB_ENABLED):
            if "data_queue" in locals() and data_queue in data_subscribers:
                data_subscribers.remove(data_queue)
                logger.info(
                    "WebSocket %s unsubscribed from data stream (total subscribers: %s)",
                    ws.client,
                    len(data_subscribers),
                )

        if connection_counted:
            _active_ws_connections = max(0, _active_ws_connections - 1)
            logger.info(
                "WebSocket disconnected: %s (active subscribers: %s)",
                ws.client,
                _get_active_subscriber_count(),
            )
        try:
            await ws.close()
        except Exception:
            pass


def _attach_alerts(data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean and enrich snapshot data for WebSocket clients.
    
    Removes debug/metadata fields and adds market status indicator.
    Keeps only essential fields: pair prices, timestamp, market status, and alerts.
    """
    grouped_pairs = _split_pairs_by_source(data)

    # Build clean response - grouped by source for websocket consumers
    clean_data = {
        "market_status": "open" if is_forex_market_open() else "closed",
        "pairs": {
            "currencies": grouped_pairs.get("currencies", []),
            "commodities": grouped_pairs.get("commodities", []),
        },
        "ts": data.get("ts"),
        "alerts": {
            "active": [a.to_dict() for a in alert_manager.get_active_alerts()],
            "triggered": [a.to_dict() for a in alert_manager.get_all_alerts() if a.status == "triggered"],
        }
    }
    return clean_data


def _normalize_pair_symbol(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).upper().replace("/", "").strip()


def _interval_to_seconds(interval: str) -> int:
    interval_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    return interval_map.get(interval, 60)


async def _build_stream_ohlc_for_pair(
    pair: str,
    latest_price: Optional[float],
    interval: str,
) -> Optional[Dict[str, Any]]:
    normalized_pair = _normalize_pair_symbol(pair)
    if not normalized_pair:
        return None

    interval_seconds = _interval_to_seconds(interval)
    current_time = datetime.now(timezone.utc)
    epoch_seconds = current_time.timestamp()
    bucket_seconds = int(epoch_seconds // interval_seconds) * interval_seconds
    bucket_time = datetime.fromtimestamp(bucket_seconds, tz=timezone.utc)
    bucket_end_time = bucket_time + timedelta(seconds=interval_seconds)
    time_in_bucket = epoch_seconds - bucket_seconds
    progress_percent = (time_in_bucket / interval_seconds) * 100

    bucket_prices: List[float] = []
    if postgres_service:
        try:
            rows = await postgres_service.query_history(
                pair=normalized_pair,
                start=bucket_time,
                end=bucket_end_time,
                limit=10000,
                descending=False,
            )
            bucket_prices = [float(row.price) for row in rows]
        except Exception as e:
            logger.debug("Failed to load stream OHLC bucket for %s: %s", normalized_pair, e)

    if not bucket_prices and latest_price is None:
        return None

    if bucket_prices:
        open_price = bucket_prices[0]
        high_price = max(bucket_prices)
        low_price = min(bucket_prices)
        close_price = latest_price if latest_price is not None else bucket_prices[-1]
        prices_for_range = bucket_prices + ([close_price] if latest_price is not None else [])
        high_price = max(prices_for_range)
        low_price = min(prices_for_range)
        volume = len(bucket_prices)
    else:
        open_price = high_price = low_price = close_price = latest_price
        volume = 1

    return {
        "timestamp": bucket_time.isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "is_forming": True,
        "interval": interval,
        "expected_open": bucket_time.isoformat(),
        "expected_close": bucket_end_time.isoformat(),
        "progress_percent": round(progress_percent, 2),
        "time_remaining_seconds": round(interval_seconds - time_in_bucket, 2),
    }


async def _attach_stream_metadata(
    data: Dict[str, Any],
    interval: str = "1m",
    pair: Optional[str] = None,
    include_alerts: bool = True,
) -> Dict[str, Any]:
    """Attach WebSocket stream metadata while keeping the default broadcast payload."""
    payload = _attach_alerts(data)

    if not include_alerts:
        payload.pop("alerts", None)

    if pair:
        normalized_pair = _normalize_pair_symbol(pair)
        filtered_pairs: Dict[str, List[Dict[str, Any]]] = {}
        for source, items in payload.get("pairs", {}).items():
            matched_items: List[Dict[str, Any]] = []
            for item in items:
                if _normalize_pair_symbol(item.get("pair")) != normalized_pair:
                    continue

                enriched_item = dict(item)
                latest_price = None
                if enriched_item.get("price") is not None:
                    try:
                        latest_price = float(str(enriched_item["price"]).replace(",", ""))
                    except (ValueError, TypeError):
                        latest_price = None

                ohlc = None
                try:
                    ohlc = await _build_stream_ohlc_for_pair(pair, latest_price, interval)
                except Exception as e:
                    logger.debug("Failed to build stream OHLC for %s: %s", pair, e)

                if ohlc:
                    enriched_item.update(ohlc)

                matched_items.append(enriched_item)

            filtered_pairs[source] = matched_items

        payload["pairs"] = filtered_pairs

    payload["stream"] = {
        "interval": interval,
        "pair": pair,
        "stream_key": f"{pair or 'all'}:{interval}",
    }
    return payload


async def _watch_ws_disconnect(ws: WebSocket, stop_event: asyncio.Event) -> None:
    """Watch for client disconnect and signal stream loops to stop quickly."""
    try:
        while not stop_event.is_set():
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WebSocket disconnect watcher stopped: %s", e)
    finally:
        stop_event.set()


def _queue_latest(queue: asyncio.Queue, data: Dict[str, Any]) -> None:
    """Coalesce queue items to keep latest data for slow consumers."""
    try:
        queue.put_nowait(data)
        return
    except asyncio.QueueFull:
        pass

    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:
        pass

    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        logger.debug("Subscriber queue remains full after coalescing")


async def _restart_observer() -> bool:
    """Restart observer(s) safely to recover from prolonged snapshot stalls."""
    active = _active_observers()
    if not active:
        return False

    async with _observer_restart_lock:
        logger.warning("Restarting observer(s) due to repeated snapshot failures")
        restarted_any = False
        for obs in active:
            source_name = getattr(obs, "source_name", "default")
            try:
                await obs.shutdown()
            except Exception as e:
                logger.warning("Observer '%s' shutdown during restart failed: %s", source_name, e)

            try:
                await obs.startup()
                restarted_any = True
                logger.info("Observer '%s' restart completed", source_name)
            except Exception as e:
                logger.error("Observer '%s' restart failed: %s", source_name, e)
        return restarted_any


async def _run_alert_action(func, **kwargs) -> bool:
    """Run blocking alert action in thread with timeout guard."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(func, **kwargs),
            timeout=ALERT_ACTION_TIMEOUT_SECONDS,
        )
        return True
    except asyncio.TimeoutError:
        logger.error(
            "Alert action timed out after %.1fs; skipping",
            ALERT_ACTION_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.error("Alert action failed: %s", e)
    return False


async def data_streaming_task():
    """Central task that continuously fetches market data and broadcasts to subscribers.
    
    Only broadcasts data when the forex market is open (24/5 operation).
    Market hours: Sunday 22:00 UTC - Friday 22:00 UTC
    """
    global latest_data, snapshot_failure_count, last_snapshot_ts
    logger.info("Data streaming task started (with forex market hours restrictions)")
    
    market_closed_logged = False
    
    while True:
        try:
            # Check if forex market is open
            if not is_forex_market_open():
                if not market_closed_logged:
                    time_until_open = get_time_until_market_opens()
                    logger.info(
                        "🔒 Forex market is CLOSED. Data streaming paused. "
                        f"Market opens in: {time_until_open}"
                    )
                    market_closed_logged = True

                await _persist_stream_metric_if_due("market_closed")
                
                # Sleep for a longer interval when market is closed (check every 5 minutes)
                await asyncio.sleep(300)
                continue
            
            # Market is open - reset the logged flag
            if market_closed_logged:
                logger.info("✅ Forex market is OPEN. Resuming data streaming.")
                market_closed_logged = False
            
            if _active_observers():
                # Fetch current market data
                data = await _collect_snapshot_from_observers()
                pairs = data.get("pairs") or []
                if not pairs:
                    raise ValueError("Snapshot returned empty pairs")

                latest_data = data
                last_snapshot_ts = data.get("ts") or datetime.now(timezone.utc).isoformat()
                snapshot_failure_count = 0

                if redis_service:
                    try:
                        await redis_service.publish_snapshot(data)
                    except Exception as e:
                        logger.error("Failed to publish snapshot to Redis: %s", e)
                
                # Broadcast to all subscribers (alert monitor and WebSocket clients)
                # Make a copy of the list to avoid modification during iteration
                current_subscribers = data_subscribers[:]
                for queue in current_subscribers:
                    _queue_latest(queue, data.copy())

                await _persist_stream_metric_if_due("healthy")
            
            await asyncio.sleep(STREAM_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Data streaming task cancelled")
            break
        except asyncio.TimeoutError:
            snapshot_failure_count += 1
            logger.error(
                "Snapshot timed out after %.1fs (failure %s/%s)",
                SNAPSHOT_TIMEOUT_SECONDS,
                snapshot_failure_count,
                MAX_SNAPSHOT_FAILURES,
            )
            if snapshot_failure_count >= MAX_SNAPSHOT_FAILURES:
                restarted = await _restart_observer()
                if restarted:
                    snapshot_failure_count = 0
            await _persist_stream_metric_if_due("degraded")
            await asyncio.sleep(STREAM_INTERVAL)
        except Exception as e:
            snapshot_failure_count += 1
            logger.error(f"Error in data streaming task: {e}")
            if snapshot_failure_count >= MAX_SNAPSHOT_FAILURES:
                restarted = await _restart_observer()
                if restarted:
                    snapshot_failure_count = 0
            await _persist_stream_metric_if_due("degraded")
            await asyncio.sleep(STREAM_INTERVAL)


async def alert_monitoring_task():
    """Background task that monitors alerts using data from the central stream.
    
    Only processes alerts when the forex market is open (24/5 operation).
    Market hours: Sunday 22:00 UTC - Friday 22:00 UTC
    
    Handles both:
    - Price alerts (live-based, from streaming data)
    - Candle-close alerts (fully closed OHLC from PostgreSQL, checked periodically)
    """
    logger.info("Alert monitoring task started (with forex market hours restrictions)")
    
    # Dynamically import here to avoid circular imports
    from app.services.call_service import CallService
    from app.services.email_service import EmailService
    from app.services.sms_service import SMSService
    
    # Get service instances from environment
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    email_service = EmailService(sendgrid_api_key) if sendgrid_api_key else None
    
    af_username = os.getenv("AFRICASTALKING_USERNAME")
    af_api_key = os.getenv("AFRICASTALKING_API_KEY")
    sms_service = None
    if af_username and af_api_key:
        try:
            sms_service = SMSService(af_username, af_api_key)
            logger.info("SMS service available for alerts")
        except Exception as e:
            logger.error(f"Failed to initialize SMS service: {e}")

    call_service = None
    twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from_number = os.getenv("TWILIO_FROM_NUMBER")
    if twilio_account_sid and twilio_auth_token and twilio_from_number:
        try:
            call_service = CallService(twilio_account_sid, twilio_auth_token, twilio_from_number)
            logger.info("Call service available for alerts")
        except Exception as e:
            logger.error(f"Failed to initialize call service: {e}")
    
    # Subscribe to data stream with larger queue to prevent dropping data
    data_queue = asyncio.Queue(maxsize=50)
    data_subscribers.append(data_queue)
    logger.info(f"Alert monitor subscribed to data stream (total subscribers: {len(data_subscribers)})")
    
    last_candle_check = 0.0
    candle_check_interval = 1.0  # Check candle alerts every second for low-latency close triggers
    
    try:
        while True:
            try:
                # Check if market is closed first - if so, skip waiting for data
                if not is_forex_market_open():
                    # Market is closed, no alerts to process - sleep longer
                    await asyncio.sleep(60)  # Check every 60 seconds when market closed
                    continue
                
                # Market is open - process latest stream item if available, but don't block candle checks
                data = None
                try:
                    data = await asyncio.wait_for(data_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    data = None

                if data is not None:
                    # ===== Check PRICE alerts (from live stream) =====
                    triggered_alerts = await asyncio.to_thread(
                        alert_manager.check_alerts,
                        data.get("pairs", []),
                    )
                    if triggered_alerts:
                        logger.warning("Triggered %s price alert(s)", len(triggered_alerts))
                        for alert_data in triggered_alerts:
                            alert = alert_data["alert"]
                            current_price = alert_data["current_price"]
                            channel = alert.get("channel", "email")
                            
                            if channel == "sms" and sms_service and alert.get("phone"):
                                await _run_alert_action(
                                    sms_service.send_price_alert,
                                    to_phone=alert["phone"],
                                    pair=alert["pair"],
                                    target_price=alert["target_price"],
                                    current_price=current_price,
                                    condition=alert["condition"],
                                    custom_message=alert.get("custom_message", ""),
                                )
                            elif channel == "call" and call_service and alert.get("phone"):
                                await _run_alert_action(
                                    call_service.send_price_alert,
                                    to_phone=alert["phone"],
                                    pair=alert["pair"],
                                    target_price=alert["target_price"],
                                    current_price=current_price,
                                    condition=alert["condition"],
                                    custom_message=alert.get("custom_message", ""),
                                )
                            elif channel == "email" and email_service and alert.get("email"):
                                await _run_alert_action(
                                    email_service.send_price_alert,
                                    to_email=alert["email"],
                                    pair=alert["pair"],
                                    target_price=alert["target_price"],
                                    current_price=current_price,
                                    condition=alert["condition"],
                                    custom_message=alert.get("custom_message", ""),
                                )
                
                # ===== Check CANDLE-CLOSE alerts (from PostgreSQL, on timer) =====
                now = time.monotonic()
                if postgres_service and (now - last_candle_check) >= candle_check_interval:
                    last_candle_check = now
                    try:
                        # Get all active candle-close alerts
                        candle_alerts = [
                            a for a in alert_manager.get_active_alerts()
                            if a.alert_type == "candle_close"
                        ]
                        
                        if candle_alerts:
                            # Fetch latest closed candles for all alerts
                            candle_data = await postgres_service.get_latest_closed_candles_for_alerts([
                                {"pair": a.pair, "interval": a.interval}
                                for a in candle_alerts
                            ])
                            
                            # Check and dispatch candle alerts
                            triggered_candle_alerts = await asyncio.to_thread(
                                alert_manager.check_candle_alerts,
                                candle_data,
                            )
                            
                            if triggered_candle_alerts:
                                logger.warning("Triggered %s candle alert(s)", len(triggered_candle_alerts))
                                for alert_data in triggered_candle_alerts:
                                    alert = alert_data["alert"]
                                    close_price = alert_data.get("close_price", alert_data.get("current_price"))
                                    channel = alert.get("channel", "email")
                                    
                                    if channel == "sms" and sms_service and alert.get("phone"):
                                        await _run_alert_action(
                                            sms_service.send_price_alert,
                                            to_phone=alert["phone"],
                                            pair=alert["pair"],
                                            target_price=alert["threshold"],
                                            current_price=close_price,
                                            condition=alert["direction"],
                                            custom_message=alert.get("custom_message", ""),
                                        )
                                    elif channel == "call" and call_service and alert.get("phone"):
                                        await _run_alert_action(
                                            call_service.send_price_alert,
                                            to_phone=alert["phone"],
                                            pair=alert["pair"],
                                            target_price=alert["threshold"],
                                            current_price=close_price,
                                            condition=alert["direction"],
                                            custom_message=alert.get("custom_message", ""),
                                        )
                                    elif channel == "email" and email_service and alert.get("email"):
                                        await _run_alert_action(
                                            email_service.send_price_alert,
                                            to_email=alert["email"],
                                            pair=alert["pair"],
                                            target_price=alert["threshold"],
                                            current_price=close_price,
                                            condition=alert["direction"],
                                            custom_message=alert.get("custom_message", ""),
                                        )
                    except Exception as e:
                        logger.error(f"Error checking candle alerts: {e}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in alert monitoring task: {e}")
                # Continue running even if there's an error
                await asyncio.sleep(0.1)
    finally:
        # Unsubscribe on exit
        if data_queue in data_subscribers:
            data_subscribers.remove(data_queue)
            logger.info(f"Alert monitor unsubscribed from data stream (total subscribers: {len(data_subscribers)})")
        logger.info("Alert monitoring task stopped")


async def archive_snapshots_task():
    """Background task that moves Redis snapshot data to PostgreSQL.
    
    Only archives data when the forex market is open to ensure clean,
    trading-hour data in the database. Market-closed snapshots are discarded.
    """
    if not redis_service or not postgres_service:
        logger.warning("Archive task started without Redis/PostgreSQL available")
        return

    logger.info("Archive task started (with forex market hours restrictions)")
    
    while True:
        try:
            # Only archive if market is open
            if not is_forex_market_open():
                # Market is closed - discard all queued snapshots to avoid stale data
                batch = await redis_service.read_queue(ARCHIVE_BATCH_SIZE)
                if batch:
                    logger.info(
                        "🔒 Market closed - discarded %d snapshot(s) from queue to maintain clean database",
                        len(batch)
                    )
                # Wait longer when market is closed
                await asyncio.sleep(300)
                continue
            
            # Market is open - archive the data to PostgreSQL
            batch = await redis_service.read_queue(ARCHIVE_BATCH_SIZE)
            if batch:
                inserted = await postgres_service.insert_snapshots(batch)
                if inserted > 0:
                    logger.debug("✅ Archived %s rows to PostgreSQL (market is open)", inserted)
            
            await asyncio.sleep(ARCHIVE_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Archive task cancelled")
            break
        except Exception as e:
            logger.error("Error in archive task: %s", e)
            await asyncio.sleep(ARCHIVE_INTERVAL)


async def retention_cleanup_task():
    """Background task that applies weekly retention cleanup in PostgreSQL.

    Policy:
    - Keep only the latest 14 calendar days.
    - Run cleanup when the new trading week opens (Sunday 22:00 UTC).
    - Apply to both historical_prices and stream_metrics tables.
    """
    global retention_cleanup_last_run_at, retention_cleanup_last_result
    global _retention_cleanup_last_run_key

    logger.info(
        "Retention cleanup task started (weekly at Sunday %02d:00 UTC, keep=%d days)",
        RETENTION_TRIGGER_HOUR_UTC,
        RETENTION_DAYS,
    )

    while True:
        try:
            if not postgres_service:
                await asyncio.sleep(RETENTION_CHECK_INTERVAL_SECONDS)
                continue

            now_utc = datetime.now(timezone.utc)
            if _is_retention_cleanup_window(now_utc):
                run_key = now_utc.date().isoformat()
                if _retention_cleanup_last_run_key != run_key:
                    deleted = await postgres_service.delete_old_data(RETENTION_DAYS)
                    retention_cleanup_last_run_at = now_utc.isoformat()
                    retention_cleanup_last_result = deleted
                    _retention_cleanup_last_run_key = run_key
                    logger.info(
                        "Retention cleanup complete: historical_deleted=%s metrics_deleted=%s retention_days=%s",
                        deleted.get("historical_deleted", 0),
                        deleted.get("metrics_deleted", 0),
                        deleted.get("retention_days", RETENTION_DAYS),
                    )

            await asyncio.sleep(RETENTION_CHECK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Retention cleanup task cancelled")
            break
        except Exception as e:
            logger.error("Error in retention cleanup task: %s", e)
            await asyncio.sleep(RETENTION_CHECK_INTERVAL_SECONDS)


@router.get("/historical")
async def historical_data(
    pair: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 500,
    order: str = "desc",
):
    """Query historical data stored in PostgreSQL."""
    if not postgres_service:
        return JSONResponse({"error": "Historical storage not available"}, status_code=503)

    retention_floor = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    start_dt = _parse_query_datetime(start)
    end_dt = _parse_query_datetime(end)
    if start_dt is None or start_dt < retention_floor:
        start_dt = retention_floor
    if end_dt and end_dt < start_dt:
        return JSONResponse({"count": 0, "items": []})
    descending = order.lower() != "asc"
    limit = max(1, min(limit, 5000))

    rows = await postgres_service.query_history(
        pair=pair,
        start=start_dt,
        end=end_dt,
        limit=limit,
        descending=descending,
    )
    items = [
        {
            "pair": row.pair,
            "price": float(row.price),
            "observed_at": row.observed_at.isoformat(),
        }
        for row in rows
    ]
    return JSONResponse({"count": len(items), "items": items})


@router.get("/historical/ohlc")
async def historical_ohlc(
    pair: str,
    interval: str = "5m",
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1000,
):
    """Query OHLC candlestick data aggregated by time interval.
    
    Args:
        pair: Currency pair (e.g., EURUSD, GBPUSD)
        interval: Time interval - 1m, 5m, 15m, 30m, 1h, 4h, 1d (default: 5m)
        start: Start datetime (ISO 8601 format, optional)
        end: End datetime (ISO 8601 format, optional)
        limit: Max candles to return (1-5000, default: 1000)
        
    Returns:
        JSON with pair, interval, count, and array of OHLC candles
    """
    interval = interval.strip().lower()

    if not postgres_service:
        return JSONResponse({"error": "Historical storage not available"}, status_code=503)

    # Validate interval
    valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    if interval not in valid_intervals:
        return JSONResponse(
            {"error": f"Invalid interval. Must be one of: {', '.join(valid_intervals)}"},
            status_code=400
        )

    start_dt = _parse_query_datetime(start)
    end_dt = _parse_query_datetime(end)
    limit = max(1, min(limit, 5000))

    try:
        candles = await postgres_service.query_ohlc(
            pair=pair.upper().replace("/", ""),  # Normalize pair name
            interval=interval,
            start=start_dt,
            end=end_dt,
            limit=limit,
        )
        
        # Format response
        formatted_candles = [
            {
                "timestamp": candle["timestamp"].isoformat(),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
                "expected_open": candle["timestamp"].isoformat(),
                "expected_close": (candle["timestamp"] + timedelta(seconds=_interval_to_seconds(interval))).isoformat(),
            }
            for candle in candles
        ]
        
        return JSONResponse({
            "pair": pair,
            "interval": interval,
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
            "count": len(formatted_candles),
            "candles": formatted_candles,
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Error querying OHLC data: {e}")
        return JSONResponse({"error": "Failed to query OHLC data"}, status_code=500)


@router.get("/historical/stream-metrics")
async def historical_stream_metrics(
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1000,
    order: str = "desc",
):
    """Query persisted stream metrics (subscriber count, failures, stream status)."""
    if not postgres_service:
        return JSONResponse({"error": "Historical storage not available"}, status_code=503)

    retention_floor = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    start_dt = _parse_query_datetime(start)
    end_dt = _parse_query_datetime(end)
    if start_dt is None or start_dt < retention_floor:
        start_dt = retention_floor
    if end_dt and end_dt < start_dt:
        return JSONResponse({"count": 0, "items": []})
    descending = order.lower() != "asc"
    limit = max(1, min(limit, 5000))

    rows = await postgres_service.query_stream_metrics(
        start=start_dt,
        end=end_dt,
        limit=limit,
        descending=descending,
    )

    items = [
        {
            "observed_at": row.observed_at.isoformat(),
            "ws_subscriber_count": row.ws_subscriber_count,
            "queue_subscriber_count": row.queue_subscriber_count,
            "snapshot_failure_count": row.snapshot_failure_count,
            "stream_status": row.stream_status,
        }
        for row in rows
    ]
    return JSONResponse({"count": len(items), "items": items})


@router.get("/historical/ohlc-with-forming")
async def historical_ohlc_with_forming(
    pair: str,
    interval: str = "5m",
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1000,
):
    """Query OHLC candlestick data including the current forming candle.
    
    Returns both closed candles from historical data and the current forming candle 
    based on real-time price data.
    
    Args:
        pair: Currency pair (e.g., EURUSD, GBPUSD)
        interval: Time interval - 1m, 5m, 15m, 30m, 1h, 4h, 1d (default: 5m)
        start: Start datetime (ISO 8601 format, optional)
        end: End datetime (ISO 8601 format, optional)
        limit: Max closed candles to return (1-5000, default: 1000)
        
    Returns:
        JSON with pair, interval, closed candles, and current forming candle
    """
    interval = interval.strip().lower()

    if not postgres_service:
        return JSONResponse({"error": "Historical storage not available"}, status_code=503)

    # Validate interval
    valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    if interval not in valid_intervals:
        return JSONResponse(
            {"error": f"Invalid interval. Must be one of: {', '.join(valid_intervals)}"},
            status_code=400
        )

    # Map interval to seconds for bucketing
    interval_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    interval_seconds = interval_map[interval]

    start_dt = _parse_query_datetime(start)
    end_dt = _parse_query_datetime(end)
    limit = max(1, min(limit, 5000))

    try:
        # Get historical closed candles
        candles = await postgres_service.query_ohlc(
            pair=pair.upper().replace("/", ""),
            interval=interval,
            start=start_dt,
            end=end_dt,
            limit=limit,
        )
        
        # Format historical candles
        formatted_candles = [
            {
                "timestamp": candle["timestamp"].isoformat(),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": candle["volume"],
                "is_forming": False,
                "expected_open": candle["timestamp"].isoformat(),
                "expected_close": (candle["timestamp"] + timedelta(seconds=interval_seconds)).isoformat(),
            }
            for candle in candles
        ]

        # Calculate current forming candle from database prices in current bucket
        forming_candle = None
        normalized_pair = pair.upper().replace("/", "")
        
        try:
            current_time = datetime.now(timezone.utc)
            
            # Calculate the bucket start time for current forming candle
            epoch_seconds = current_time.timestamp()
            bucket_seconds = int(epoch_seconds // interval_seconds) * interval_seconds
            bucket_time = datetime.fromtimestamp(bucket_seconds, tz=timezone.utc)
            bucket_end_time = bucket_time + timedelta(seconds=interval_seconds)
            
            # Time elapsed in current bucket (0 to interval_seconds)
            time_in_bucket = epoch_seconds - bucket_seconds
            progress_percent = (time_in_bucket / interval_seconds) * 100
            
            # Get current price from latest snapshot
            current_price = None
            if latest_data.get("pairs"):
                for p in latest_data.get("pairs", []):
                    if p.get("pair", "").replace("/", "").upper() == normalized_pair:
                        if p.get("price"):
                            try:
                                current_price = float(str(p["price"]).replace(",", ""))
                            except (ValueError, TypeError):
                                pass
                        break
            
            # Query all prices in the current bucket from database
            bucket_prices = await postgres_service.query_history(
                pair=normalized_pair,
                start=bucket_time,
                end=bucket_end_time,
                limit=10000,
                descending=False,  # ASC order to get open first
            )
            
            if bucket_prices:
                # Calculate OHLC from all prices in bucket
                prices = [float(p.price) for p in bucket_prices]
                # Use current price for close if available, otherwise use last bucket price
                close_price = current_price if current_price is not None else prices[-1]
                
                forming_candle = {
                    "timestamp": bucket_time.isoformat(),
                    "open": prices[0],
                    "high": max(prices + [close_price]) if current_price is not None else max(prices),
                    "low": min(prices + [close_price]) if current_price is not None else min(prices),
                    "close": close_price,
                    "volume": len(prices),
                    "is_forming": True,
                    "expected_open": bucket_time.isoformat(),
                    "expected_close": bucket_end_time.isoformat(),
                    "progress_percent": round(progress_percent, 2),
                    "time_remaining_seconds": round(interval_seconds - time_in_bucket, 2),
                }
            elif current_price is not None:
                # Fallback to latest snapshot if no bucket data
                forming_candle = {
                    "timestamp": bucket_time.isoformat(),
                    "open": current_price,
                    "high": current_price,
                    "low": current_price,
                    "close": current_price,
                    "volume": 1,
                    "is_forming": True,
                    "expected_open": bucket_time.isoformat(),
                    "expected_close": bucket_end_time.isoformat(),
                    "progress_percent": round(progress_percent, 2),
                    "time_remaining_seconds": round(interval_seconds - time_in_bucket, 2),
                }
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Error calculating forming candle for {normalized_pair}: {e}")
            pass

        # Combine closed candles and forming candle
        all_candles = formatted_candles.copy()
        if forming_candle:
            all_candles.append(forming_candle)

        return JSONResponse({
            "pair": pair,
            "interval": interval,
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
            "closed_candles_count": len(formatted_candles),
            "has_forming_candle": forming_candle is not None,
            "last_update": latest_data.get("ts", datetime.now(timezone.utc).isoformat()),
            "candles": all_candles,
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Error querying OHLC data with forming candle: {e}")
        return JSONResponse({"error": "Failed to query OHLC data"}, status_code=500)


def _parse_query_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
