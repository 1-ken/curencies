"""Data streaming and observation endpoints."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

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

snapshot_failure_count = 0
last_snapshot_ts: Optional[str] = None
_observer_restart_lock = asyncio.Lock()


def set_observer(obs: SiteObserver):
    """Set the global observer instance."""
    global observer
    observer = obs


def set_alert_manager(manager: AlertManager):
    """Set the global alert manager instance."""
    global alert_manager
    alert_manager = manager


def set_config(stream_interval: float, majors: List[str]):
    """Set configuration."""
    global STREAM_INTERVAL, MAJORS
    STREAM_INTERVAL = stream_interval
    MAJORS = majors


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


@router.get("/")
async def root():
    """Serve the client HTML page."""
    # Navigate from app/api/v1/endpoints/data.py to root directory
    from pathlib import Path
    root_dir = Path(__file__).parent.parent.parent.parent.parent
    client_file = root_dir / "client.html"
    return FileResponse(str(client_file))


@router.get("/snapshot")
async def snapshot():
    """Get a single snapshot of current forex data.
    
    Returns clean data format with only essential fields:
    - market_status: "open" or "closed"
    - pairs: currency pairs with prices
    - ts: timestamp
    """
    if not observer:
        logger.warning("Snapshot requested but observer not ready")
        return JSONResponse({"error": "Observer not ready"}, status_code=503)
    
    try:
        data = await observer.snapshot(MAJORS)
        # Return clean format without alerts
        clean_data = {
            "market_status": "open" if is_forex_market_open() else "closed",
            "pairs": data.get("pairs", []),
            "ts": data.get("ts")
        }
        return JSONResponse(clean_data)
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
    if last_snapshot_age_seconds is not None and last_snapshot_age_seconds > max(5.0, STREAM_INTERVAL * 6):
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
            "subscriber_count": len(data_subscribers),
        }
    )


@router.websocket("/ws/observe")
async def ws_observe(ws: WebSocket):
    """WebSocket endpoint for streaming real-time forex data."""
    await ws.accept()
    logger.info(f"WebSocket connection established: {ws.client} (total subscribers: {len(data_subscribers) + 1})")
    
    if not observer:
        logger.warning("WebSocket connection but observer not ready")
        await ws.send_json({"error": "Observer not ready"})
        await ws.close()
        return

    try:
        if redis_service and REDIS_PUBSUB_ENABLED:
            logger.info("WebSocket %s using Redis pub/sub stream", ws.client)
            async for data in redis_service.subscribe():
                data = _attach_alerts(data)
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

            while True:
                # Get data from the central stream
                data = await data_queue.get()
                data = _attach_alerts(data)
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
        if not (redis_service and REDIS_PUBSUB_ENABLED):
            if "data_queue" in locals() and data_queue in data_subscribers:
                data_subscribers.remove(data_queue)
                logger.info(
                    "WebSocket %s unsubscribed from data stream (total subscribers: %s)",
                    ws.client,
                    len(data_subscribers),
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
    # Build clean response - only essential fields for clients
    clean_data = {
        "market_status": "open" if is_forex_market_open() else "closed",
        "pairs": data.get("pairs", []),
        "ts": data.get("ts"),
        "alerts": {
            "active": [a.to_dict() for a in alert_manager.get_active_alerts()],
            "triggered": [a.to_dict() for a in alert_manager.get_all_alerts() if a.status == "triggered"],
        }
    }
    return clean_data


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
    """Restart observer safely to recover from prolonged snapshot stalls."""
    global observer
    if not observer:
        return False

    async with _observer_restart_lock:
        logger.warning("Restarting observer due to repeated snapshot failures")
        try:
            await observer.shutdown()
        except Exception as e:
            logger.warning("Observer shutdown during restart failed: %s", e)

        try:
            await observer.startup()
            logger.info("Observer restart completed")
            return True
        except Exception as e:
            logger.error("Observer restart failed: %s", e)
            return False


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
                
                # Sleep for a longer interval when market is closed (check every 5 minutes)
                await asyncio.sleep(300)
                continue
            
            # Market is open - reset the logged flag
            if market_closed_logged:
                logger.info("✅ Forex market is OPEN. Resuming data streaming.")
                market_closed_logged = False
            
            if observer:
                # Fetch current market data
                data = await asyncio.wait_for(
                    observer.snapshot(MAJORS),
                    timeout=SNAPSHOT_TIMEOUT_SECONDS,
                )
                latest_data = data
                last_snapshot_ts = data.get("ts")
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
            await asyncio.sleep(STREAM_INTERVAL)
        except Exception as e:
            snapshot_failure_count += 1
            logger.error(f"Error in data streaming task: {e}")
            if snapshot_failure_count >= MAX_SNAPSHOT_FAILURES:
                restarted = await _restart_observer()
                if restarted:
                    snapshot_failure_count = 0
            await asyncio.sleep(STREAM_INTERVAL)


async def alert_monitoring_task():
    """Background task that monitors alerts using data from the central stream.
    
    Only processes alerts when the forex market is open (24/5 operation).
    Market hours: Sunday 22:00 UTC - Friday 22:00 UTC
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
    
    try:
        while True:
            try:
                # Check if market is closed first - if so, skip waiting for data
                if not is_forex_market_open():
                    # Market is closed, no alerts to process - sleep longer
                    await asyncio.sleep(60)  # Check every 60 seconds when market closed
                    continue
                
                # Market is open - wait for data with timeout
                data = await asyncio.wait_for(data_queue.get(), timeout=5.0)
                
                # Check price alerts
                triggered_alerts = await asyncio.to_thread(
                    alert_manager.check_alerts,
                    data.get("pairs", []),
                )
                if triggered_alerts:
                    logger.warning("Triggered %s alert(s)", len(triggered_alerts))
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
            except asyncio.TimeoutError:
                # Queue timeout only when market is open - data stream may be slow
                logger.debug("Alert monitor: no data received within 5s (market may be busy)")
                continue
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

    start_dt = _parse_query_datetime(start)
    end_dt = _parse_query_datetime(end)
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
            "source_title": row.source_title,
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
