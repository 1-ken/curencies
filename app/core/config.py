"""Application configuration loader."""
import json
import logging
import os
from urllib.parse import quote_plus
from typing import Any, Dict, List

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
    def sources(self) -> List[Dict[str, Any]]:
        """Return enabled scraping sources.

        Supports both:
        - New format: `sources: [{...}]`
        - Legacy format: top-level url/selectors keys
        """
        raw_sources = self.get("sources")
        if isinstance(raw_sources, list) and raw_sources:
            normalized_sources: List[Dict[str, Any]] = []
            for index, item in enumerate(raw_sources):
                if not isinstance(item, dict):
                    continue
                if not bool(item.get("enabled", True)):
                    continue
                source_entry: Dict[str, Any] = {
                    "name": item.get("name") or f"source-{index + 1}",
                    "url": item.get("url", "https://finance.yahoo.com/markets/currencies/"),
                    "waitSelector": item.get("waitSelector", "body"),
                    "tableSelector": item.get("tableSelector", "table"),
                    "pairCellSelector": item.get("pairCellSelector", "tbody tr td:nth-child(2)"),
                    "injectMutationObserver": bool(item.get("injectMutationObserver", True)),
                    "filterByMajors": bool(item.get("filterByMajors", True)),
                }
                # Commodities sources can override the curated allowlist via
                # a simple list of canonical symbols. Unknown sources ignore it.
                raw_allowed = item.get("allowedSymbols")
                if isinstance(raw_allowed, list):
                    source_entry["allowedSymbols"] = [
                        str(symbol) for symbol in raw_allowed if symbol
                    ]
                normalized_sources.append(source_entry)
            if normalized_sources:
                return normalized_sources

        return [
            {
                "name": "default",
                "url": self.url,
                "waitSelector": self.wait_selector,
                "tableSelector": self.table_selector,
                "pairCellSelector": self.pair_cell_selector,
                "injectMutationObserver": self.inject_mutation_observer,
                "filterByMajors": True,
            }
        ]
    
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
    def snapshot_timeout_seconds(self) -> float:
        return float(os.getenv("SNAPSHOT_TIMEOUT_SECONDS", self.get("snapshotTimeoutSeconds", 8)))

    @property
    def ws_send_timeout_seconds(self) -> float:
        return float(os.getenv("WS_SEND_TIMEOUT_SECONDS", self.get("wsSendTimeoutSeconds", 3)))

    @property
    def alert_action_timeout_seconds(self) -> float:
        return float(os.getenv("ALERT_ACTION_TIMEOUT_SECONDS", self.get("alertActionTimeoutSeconds", 8)))

    @property
    def max_snapshot_failures(self) -> int:
        return int(os.getenv("MAX_SNAPSHOT_FAILURES", self.get("maxSnapshotFailures", 4)))
    
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
    def redis_socket_connect_timeout_seconds(self) -> float:
        return float(
            os.getenv(
                "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
                self.get("redisSocketConnectTimeoutSeconds", 2),
            )
        )

    @property
    def redis_socket_timeout_seconds(self) -> float:
        return float(
            os.getenv(
                "REDIS_SOCKET_TIMEOUT_SECONDS",
                self.get("redisSocketTimeoutSeconds", 2),
            )
        )

    @property
    def redis_retry_max_attempts(self) -> int:
        return int(os.getenv("REDIS_RETRY_MAX_ATTEMPTS", self.get("redisRetryMaxAttempts", 5)))

    @property
    def redis_retry_base_delay_seconds(self) -> float:
        return float(
            os.getenv(
                "REDIS_RETRY_BASE_DELAY_SECONDS",
                self.get("redisRetryBaseDelaySeconds", 0.5),
            )
        )

    @property
    def redis_retry_max_delay_seconds(self) -> float:
        return float(
            os.getenv(
                "REDIS_RETRY_MAX_DELAY_SECONDS",
                self.get("redisRetryMaxDelaySeconds", 5),
            )
        )

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
