"""Data streaming and observation endpoints."""
import asyncio
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from app.services.observer_service import SiteObserver
from app.services.alert_service import AlertManager

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

# Configuration
STREAM_INTERVAL = 1.0
MAJORS = []


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


@router.get("/")
async def root():
    """Serve the client HTML page."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return FileResponse(os.path.join(here, "client.html"))


@router.get("/snapshot")
async def snapshot():
    """Get a single snapshot of current forex data."""
    if not observer:
        logger.warning("Snapshot requested but observer not ready")
        return JSONResponse({"error": "Observer not ready"}, status_code=503)
    
    try:
        data = await observer.snapshot(MAJORS)
        return JSONResponse(data)
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

    # Subscribe to data stream
    data_queue = asyncio.Queue(maxsize=50)
    data_subscribers.append(data_queue)
    logger.info(f"WebSocket {ws.client} subscribed to data stream (total subscribers: {len(data_subscribers)})")

    try:
        while True:
            # Get data from the central stream
            data = await data_queue.get()
            
            # Include alerts in response (processing happens in background task)
            data["alerts"] = {
                "active": [a.to_dict() for a in alert_manager.get_active_alerts()],
                "triggered": [a.to_dict() for a in alert_manager.get_all_alerts() if a.status == "triggered"],
            }
            
            await ws.send_json(data)
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed: {ws.client}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Unsubscribe from data stream
        if data_queue in data_subscribers:
            data_subscribers.remove(data_queue)
            logger.info(f"WebSocket {ws.client} unsubscribed from data stream (total subscribers: {len(data_subscribers)})")
        try:
            await ws.close()
        except Exception:
            pass


async def data_streaming_task():
    """Central task that continuously fetches market data and broadcasts to subscribers."""
    global latest_data
    logger.info("Data streaming task started")
    while True:
        try:
            if observer:
                # Fetch current market data
                data = await observer.snapshot(MAJORS)
                latest_data = data
                
                # Broadcast to all subscribers (alert monitor and WebSocket clients)
                # Make a copy of the list to avoid modification during iteration
                current_subscribers = data_subscribers[:]
                for queue in current_subscribers:
                    try:
                        queue.put_nowait(data.copy())
                    except asyncio.QueueFull:
                        # Queue is full, skip this subscriber
                        logger.debug(f"Data subscriber queue full, skipping")
                        pass
            
            await asyncio.sleep(STREAM_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Data streaming task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in data streaming task: {e}")
            await asyncio.sleep(STREAM_INTERVAL)


async def alert_monitoring_task():
    """Background task that monitors alerts using data from the central stream."""
    logger.info("Alert monitoring task started")
    
    # Dynamically import here to avoid circular imports
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
    
    # Subscribe to data stream with larger queue to prevent dropping data
    data_queue = asyncio.Queue(maxsize=50)
    data_subscribers.append(data_queue)
    logger.info(f"Alert monitor subscribed to data stream (total subscribers: {len(data_subscribers)})")
    
    try:
        while True:
            try:
                # Get data from the stream with timeout to ensure we keep monitoring
                data = await asyncio.wait_for(data_queue.get(), timeout=5.0)
                
                # Check price alerts
                triggered_alerts = alert_manager.check_alerts(data.get("pairs", []))
                if triggered_alerts:
                    logger.info(f"Triggered {len(triggered_alerts)} alert(s)")
                    for alert_data in triggered_alerts:
                        alert = alert_data["alert"]
                        current_price = alert_data["current_price"]
                        channel = alert.get("channel", "email")
                        
                        if channel == "sms" and sms_service and alert.get("phone"):
                            sms_service.send_price_alert(
                                to_phone=alert["phone"],
                                pair=alert["pair"],
                                target_price=alert["target_price"],
                                current_price=current_price,
                                condition=alert["condition"],
                                custom_message=alert.get("custom_message", ""),
                            )
                        elif channel == "email" and email_service and alert.get("email"):
                            email_service.send_price_alert(
                                to_email=alert["email"],
                                pair=alert["pair"],
                                target_price=alert["target_price"],
                                current_price=current_price,
                                condition=alert["condition"],
                                custom_message=alert.get("custom_message", ""),
                            )
            except asyncio.TimeoutError:
                # Queue timeout - data stream may have stopped, continue trying
                logger.warning("Alert monitor queue timeout - no data received for 5s")
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
