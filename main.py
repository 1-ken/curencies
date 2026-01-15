import asyncio
import json
import logging
import os
import time
import certifi
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from observer import SiteObserver
from alerts import AlertManager, Alert
from email_service import EmailService

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

HERE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(HERE, "config.json")

# Load configuration
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG: Dict[str, Any] = json.load(f)
except FileNotFoundError:
    logger.error(f"Config file not found: {CONFIG_PATH}")
    raise
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in config file: {e}")
    raise

STREAM_INTERVAL = int(CONFIG.get("streamIntervalSeconds", 1))
MAJORS = CONFIG.get("majors", [])

# Initialize alert manager and email service
alert_manager = AlertManager()
email_service = None
sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
if sendgrid_api_key:
    email_service = EmailService(sendgrid_api_key)
    logger.info("SendGrid email service initialized")
else:
    logger.warning("SENDGRID_API_KEY not set, email alerts disabled")

app = FastAPI(
    title="Finance Observer",
    description="Real-time forex currency pair price monitoring with price alerts",
    version="1.0.0"
)

observer: SiteObserver | None = None


@app.on_event("startup")
async def on_startup():
    """Initialize the observer on application startup."""
    global observer
    logger.info("Starting Finance Observer application...")
    
    try:
        observer = SiteObserver(
            url=CONFIG.get("url"),
            table_selector=CONFIG.get("tableSelector"),
            pair_cell_selector=CONFIG.get("pairCellSelector"),
            wait_selector=CONFIG.get("waitSelector", "body"),
            inject_mutation_observer=bool(CONFIG.get("injectMutationObserver", True)),
        )
        await observer.startup()
        logger.info("Observer started successfully")
    except Exception as e:
        logger.error(f"Failed to start observer: {e}")
        raise


@app.on_event("shutdown")
async def on_shutdown():
    """Clean up resources on application shutdown."""
    if observer:
        logger.info("Shutting down observer...")
        try:
            await observer.shutdown()
            logger.info("Observer shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


@app.get("/")
async def root():
    """Serve the client HTML page."""
    return FileResponse(os.path.join(HERE, "client.html"))


@app.get("/snapshot")
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


@app.websocket("/ws/observe")
async def ws_observe(ws: WebSocket):
    """WebSocket endpoint for streaming real-time forex data."""
    await ws.accept()
    logger.info(f"WebSocket connection established: {ws.client}")
    
    if not observer:
        logger.warning("WebSocket connection but observer not ready")
        await ws.send_json({"error": "Observer not ready"})
        await ws.close()
        return

    try:
        while True:
            data = await observer.snapshot(MAJORS)
            
            # Check price alerts
            triggered_alerts = alert_manager.check_alerts(data.get("pairs", []))
            if triggered_alerts and email_service:
                for alert_data in triggered_alerts:
                    alert = alert_data["alert"]
                    current_price = alert_data["current_price"]
                    email_service.send_price_alert(
                        to_email=alert["email"],
                        pair=alert["pair"],
                        target_price=alert["target_price"],
                        current_price=current_price,
                        condition=alert["condition"],
                        custom_message=alert.get("custom_message", ""),
                    )
            
            # Include alerts in response
            data["alerts"] = {
                "active": [a.to_dict() for a in alert_manager.get_active_alerts()],
                "triggered": [a.to_dict() for a in alert_manager.get_all_alerts() if a.status == "triggered"],
            }
            
            await ws.send_json(data)
            await asyncio.sleep(STREAM_INTERVAL)
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed: {ws.client}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# Alert API Endpoints

class CreateAlertRequest(BaseModel):
    pair: str
    target_price: float
    condition: str  # "above", "below", or "equal"
    email: str
    custom_message: str = ""  # Optional custom message for the alert email


@app.post("/api/alerts")
async def create_alert(request: CreateAlertRequest):
    """Create a new price alert."""
    if request.condition not in ["above", "below", "equal"]:
        raise HTTPException(status_code=400, detail="Condition must be 'above', 'below', or 'equal'")
    
    alert = alert_manager.create_alert(
        pair=request.pair,
        target_price=request.target_price,
        condition=request.condition,
        email=request.email,
        custom_message=request.custom_message,
    )
    return {"success": True, "alert": alert.to_dict()}


@app.get("/api/alerts")
async def get_alerts():
    """Get all alerts."""
    all_alerts = alert_manager.get_all_alerts()
    return {
        "total": len(all_alerts),
        "active": [a.to_dict() for a in all_alerts if a.status == "active"],
        "triggered": [a.to_dict() for a in all_alerts if a.status == "triggered"],
        "all": [a.to_dict() for a in all_alerts],
    }


@app.get("/api/alerts/{alert_id}")
async def get_alert(alert_id: str):
    """Get specific alert."""
    alert = alert_manager.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert.to_dict()


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    """Delete an alert."""
    if alert_manager.delete_alert(alert_id):
        return {"success": True, "message": "Alert deleted"}
    raise HTTPException(status_code=404, detail="Alert not found")
