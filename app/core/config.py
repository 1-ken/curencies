"""Application configuration loader."""
import json
import logging
import os
from urllib.parse import quote_plus
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Config:
    """Application configuration."""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
        
        self.config_path = config_path
        self.data: Dict[str, Any] = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
            return data
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.data.get(key, default)
    
    @property
    def url(self) -> str:
        return self.get("url", "https://finance.yahoo.com/markets/currencies/")
    
    @property
    def wait_selector(self) -> str:
        return self.get("waitSelector", "body")
    
    @property
    def table_selector(self) -> str:
        return self.get("tableSelector", "table")
    
    @property
    def pair_cell_selector(self) -> str:
        return self.get("pairCellSelector", "tbody tr td:nth-child(2)")
    
    @property
    def stream_interval_seconds(self) -> float:
        return float(self.get("streamIntervalSeconds", 1))
    
    @property
    def majors(self) -> list:
        return self.get("majors", ["USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"])
    
    @property
    def inject_mutation_observer(self) -> bool:
        return bool(self.get("injectMutationObserver", True))

    @property
    def redis_url(self) -> str:
        return os.getenv("REDIS_URL", self.get("redisUrl", "redis://localhost:6379/0"))

    @property
    def redis_channel(self) -> str:
        return os.getenv("REDIS_CHANNEL", self.get("redisChannel", "fx:stream"))

    @property
    def redis_latest_key(self) -> str:
        return os.getenv("REDIS_LATEST_KEY", self.get("redisLatestKey", "fx:latest"))

    @property
    def redis_queue_key(self) -> str:
        return os.getenv("REDIS_QUEUE_KEY", self.get("redisQueueKey", "fx:snapshots:queue"))

    @property
    def redis_recent_key(self) -> str:
        return os.getenv("REDIS_RECENT_KEY", self.get("redisRecentKey", "fx:snapshots:recent"))

    @property
    def redis_recent_maxlen(self) -> int:
        return int(os.getenv("REDIS_RECENT_MAXLEN", self.get("redisRecentMaxlen", 200)))

    @property
    def redis_pubsub_enabled(self) -> bool:
        value = os.getenv("REDIS_PUBSUB_ENABLED", str(self.get("redisPubSubEnabled", True)))
        return value.lower() in {"1", "true", "yes", "on"}

    @property
    def archive_interval_seconds(self) -> float:
        return float(os.getenv("ARCHIVE_INTERVAL_SECONDS", self.get("archiveIntervalSeconds", 30)))

    @property
    def archive_batch_size(self) -> int:
        return int(os.getenv("ARCHIVE_BATCH_SIZE", self.get("archiveBatchSize", 200)))

    @property
    def postgres_dsn(self) -> str:
        dsn = os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL")
        if dsn:
            if dsn.startswith("postgresql://"):
                return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            if dsn.startswith("postgres://"):
                return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
            return dsn

        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "postgres")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "fx_observer")
        safe_password = quote_plus(password)
        return f"postgresql+asyncpg://{user}:{safe_password}@{host}:{port}/{db}"

    @property
    def postgres_maintenance_db(self) -> str:
        return os.getenv("POSTGRES_MAINT_DB", self.get("postgresMaintenanceDb", "postgres"))


# Global config instance
config: Config = None


def get_config() -> Config:
    """Get global config instance."""
    global config
    if config is None:
        config = Config()
    return config
