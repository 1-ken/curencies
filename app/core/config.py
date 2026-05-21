"""Application configuration loading."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return _project_root() / "config.json"


def _load_config_file() -> Dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    url: str = "https://finance.yahoo.com/markets/currencies/"
    wait_selector: str = "table tbody tr"
    table_selector: str = "table"
    pair_cell_selector: str = "tbody tr td:nth-child(2)"
    stream_interval_seconds: float = 0.5
    snapshot_timeout_seconds: float = 30.0
    ws_send_timeout_seconds: float = 3.0
    alert_action_timeout_seconds: float = 8.0
    max_snapshot_failures: int = 4
    redis_socket_connect_timeout_seconds: float = 2.0
    redis_socket_timeout_seconds: float = 2.0
    redis_retry_max_attempts: int = 5
    redis_retry_base_delay_seconds: float = 0.5
    redis_retry_max_delay_seconds: float = 5.0
    redis_url: str = "redis://localhost:6379/0"
    redis_channel: str = "fx:observer:snapshot"
    redis_latest_key: str = "fx:observer:latest"
    redis_queue_key: str = "fx:observer:queue"
    redis_recent_key: str = "fx:observer:recent"
    redis_recent_maxlen: int = 200
    redis_alert_queue_key: str = "fx:alerts:queue"
    redis_pubsub_enabled: bool = True
    postgres_dsn: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/observer",
    )
    postgres_maintenance_db: str = "postgres"
    majors: List[str] = field(
        default_factory=lambda: ["USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"]
    )
    inject_mutation_observer: bool = True
    sources: List[Dict[str, Any]] = field(default_factory=list)
    alert_monitor_poll_timeout_seconds: float = 0.05
    candle_check_interval_seconds: float = 0.25
    notification_worker_count: int = 4
    notification_max_retries: int = 3
    notification_retry_delay_seconds: float = 1.0
    notification_dlq_key: str = "fx:alerts:notifications:dlq"
    archive_interval_seconds: float = 30.0
    archive_batch_size: int = 200


def _build_sources(raw_sources: Any, defaults: Config) -> List[Dict[str, Any]]:
    if not isinstance(raw_sources, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        item = dict(source)
        item.setdefault("url", defaults.url)
        item.setdefault("waitSelector", defaults.wait_selector)
        item.setdefault("tableSelector", defaults.table_selector)
        item.setdefault("pairCellSelector", defaults.pair_cell_selector)
        item.setdefault("injectMutationObserver", defaults.inject_mutation_observer)
        item.setdefault("filterByMajors", True)
        item.setdefault("enabled", True)
        normalized.append(item)
    return normalized


def get_config() -> Config:
    """Load application configuration from config.json with env overrides."""
    raw = _load_config_file()
    defaults = Config()

    return Config(
        url=str(raw.get("url", defaults.url)),
        wait_selector=str(raw.get("waitSelector", defaults.wait_selector)),
        table_selector=str(raw.get("tableSelector", defaults.table_selector)),
        pair_cell_selector=str(raw.get("pairCellSelector", defaults.pair_cell_selector)),
        stream_interval_seconds=float(
            raw.get(
                "streamIntervalSeconds",
                _env_float("STREAM_INTERVAL_SECONDS", defaults.stream_interval_seconds),
            )
        ),
        snapshot_timeout_seconds=float(
            raw.get(
                "snapshotTimeoutSeconds",
                _env_float("SNAPSHOT_TIMEOUT_SECONDS", defaults.snapshot_timeout_seconds),
            )
        ),
        ws_send_timeout_seconds=float(
            raw.get(
                "wsSendTimeoutSeconds",
                _env_float("WS_SEND_TIMEOUT_SECONDS", defaults.ws_send_timeout_seconds),
            )
        ),
        alert_action_timeout_seconds=float(
            raw.get(
                "alertActionTimeoutSeconds",
                _env_float("ALERT_ACTION_TIMEOUT_SECONDS", defaults.alert_action_timeout_seconds),
            )
        ),
        max_snapshot_failures=int(
            raw.get(
                "maxSnapshotFailures",
                _env_int("MAX_SNAPSHOT_FAILURES", defaults.max_snapshot_failures),
            )
        ),
        redis_socket_connect_timeout_seconds=float(
            raw.get(
                "redisSocketConnectTimeoutSeconds",
                _env_float(
                    "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
                    defaults.redis_socket_connect_timeout_seconds,
                ),
            )
        ),
        redis_socket_timeout_seconds=float(
            raw.get(
                "redisSocketTimeoutSeconds",
                _env_float("REDIS_SOCKET_TIMEOUT_SECONDS", defaults.redis_socket_timeout_seconds),
            )
        ),
        redis_retry_max_attempts=int(
            raw.get(
                "redisRetryMaxAttempts",
                _env_int("REDIS_RETRY_MAX_ATTEMPTS", defaults.redis_retry_max_attempts),
            )
        ),
        redis_retry_base_delay_seconds=float(
            raw.get(
                "redisRetryBaseDelaySeconds",
                _env_float(
                    "REDIS_RETRY_BASE_DELAY_SECONDS",
                    defaults.redis_retry_base_delay_seconds,
                ),
            )
        ),
        redis_retry_max_delay_seconds=float(
            raw.get(
                "redisRetryMaxDelaySeconds",
                _env_float("REDIS_RETRY_MAX_DELAY_SECONDS", defaults.redis_retry_max_delay_seconds),
            )
        ),
        redis_url=str(raw.get("redisUrl", os.getenv("REDIS_URL", defaults.redis_url))),
        redis_channel=str(raw.get("redisChannel", defaults.redis_channel)),
        redis_latest_key=str(raw.get("redisLatestKey", defaults.redis_latest_key)),
        redis_queue_key=str(raw.get("redisQueueKey", defaults.redis_queue_key)),
        redis_recent_key=str(raw.get("redisRecentKey", defaults.redis_recent_key)),
        redis_recent_maxlen=int(
            raw.get(
                "redisRecentMaxlen",
                _env_int("REDIS_RECENT_MAXLEN", defaults.redis_recent_maxlen),
            )
        ),
        redis_alert_queue_key=str(raw.get("redisAlertQueueKey", defaults.redis_alert_queue_key)),
        redis_pubsub_enabled=bool(
            raw.get("redisPubsubEnabled", _env_bool("REDIS_PUBSUB_ENABLED", defaults.redis_pubsub_enabled))
        ),
        postgres_dsn=str(
            os.getenv("DATABASE_URL", raw.get("postgresDsn", defaults.postgres_dsn))
        ),
        postgres_maintenance_db=str(
            raw.get("postgresMaintenanceDb", defaults.postgres_maintenance_db)
        ),
        majors=[str(item).strip().upper() for item in raw.get("majors", defaults.majors) if str(item).strip()],
        inject_mutation_observer=bool(
            raw.get(
                "injectMutationObserver",
                _env_bool("INJECT_MUTATION_OBSERVER", defaults.inject_mutation_observer),
            )
        ),
        sources=_build_sources(raw.get("sources", []), defaults),
        alert_monitor_poll_timeout_seconds=float(
            raw.get(
                "alertMonitorPollTimeoutSeconds",
                _env_float(
                    "ALERT_MONITOR_POLL_TIMEOUT_SECONDS",
                    defaults.alert_monitor_poll_timeout_seconds,
                ),
            )
        ),
        candle_check_interval_seconds=float(
            raw.get(
                "candleCheckIntervalSeconds",
                _env_float(
                    "CANDLE_CHECK_INTERVAL_SECONDS",
                    defaults.candle_check_interval_seconds,
                ),
            )
        ),
        notification_worker_count=int(
            raw.get(
                "notificationWorkerCount",
                _env_int("NOTIFICATION_WORKER_COUNT", defaults.notification_worker_count),
            )
        ),
        notification_max_retries=int(
            raw.get(
                "notificationMaxRetries",
                _env_int("NOTIFICATION_MAX_RETRIES", defaults.notification_max_retries),
            )
        ),
        notification_retry_delay_seconds=float(
            raw.get(
                "notificationRetryDelaySeconds",
                _env_float(
                    "NOTIFICATION_RETRY_DELAY_SECONDS",
                    defaults.notification_retry_delay_seconds,
                ),
            )
        ),
        notification_dlq_key=str(
            raw.get("notificationDlqKey", defaults.notification_dlq_key)
        ),
        archive_interval_seconds=float(
            raw.get(
                "archiveIntervalSeconds",
                _env_float("ARCHIVE_INTERVAL_SECONDS", defaults.archive_interval_seconds),
            )
        ),
        archive_batch_size=int(
            raw.get("archiveBatchSize", _env_int("ARCHIVE_BATCH_SIZE", defaults.archive_batch_size))
        ),
    )


NEXTAUTH_SECRET = os.getenv("NEXTAUTH_SECRET", "").strip()
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
