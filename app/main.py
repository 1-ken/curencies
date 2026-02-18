"""Finance Observer - FastAPI application entry point."""
import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

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
alert_manager: AlertManager = AlertManager()
background_task: asyncio.Task | None = None
data_stream_task: asyncio.Task | None = None
archive_task: asyncio.Task | None = None
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


@app.on_event("startup")
async def on_startup():
    """Initialize the observer on application startup."""
    global observer, background_task, data_stream_task, archive_task
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

        observer = SiteObserver(
            url=config.url,
            table_selector=config.table_selector,
            pair_cell_selector=config.pair_cell_selector,
            wait_selector=config.wait_selector,
            inject_mutation_observer=config.inject_mutation_observer,
        )
        await observer.startup()
        logger.info("Observer started successfully")
        
        # Set instances for endpoint handlers
        alerts_endpoints.set_alert_manager(alert_manager)
        data_endpoints.set_observer(observer)
        data_endpoints.set_alert_manager(alert_manager)
        data_endpoints.set_config(config.stream_interval_seconds, config.majors)
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
    except Exception as e:
        logger.error(f"Failed to start observer: {e}")
        raise


@app.on_event("shutdown")
async def on_shutdown():
    """Clean up resources on application shutdown."""
    global background_task, data_stream_task, archive_task
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
    
    if observer:
        logger.info("Shutting down observer...")
        try:
            await observer.shutdown()
            logger.info("Observer shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

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


# Include API routers
app.include_router(api_v1.router)

# Add data endpoints at root level (for /, /snapshot, /client-config, /ws/observe)
app.include_router(data_endpoints.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
