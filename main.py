import asyncio
import json
import logging
import os
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from observer import SiteObserver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

app = FastAPI(
    title="Finance Observer",
    description="Real-time forex currency pair price monitoring",
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
