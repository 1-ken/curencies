"""General API response schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class HealthCheckDetails(BaseModel):
    uptime_seconds: float
    observer: str
    stream_task: str
    alert_task: str
    cleanup_task: Optional[str] = None
    redis: str
    postgres: str
    stream_failures: Optional[int] = None
    last_snapshot_ts: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    checks: HealthCheckDetails


class PingResponse(BaseModel):
    pong: bool


class ClientConfigResponse(BaseModel):
    wsUrl: str


class StreamHealthResponse(BaseModel):
    status: str
    stream_interval_seconds: float
    snapshot_timeout_seconds: float
    max_snapshot_failures: int
    consecutive_snapshot_failures: int
    last_snapshot_ts: Optional[str]
    last_snapshot_age_seconds: Optional[float]
    subscriber_count: int
    ws_subscriber_count: int
    queue_subscriber_count: int
    retention_days: int
    retention_cleanup_schedule_utc: str
    retention_cleanup_last_run_at: Optional[str]
    retention_cleanup_next_run_at: str
    retention_cleanup_last_result: Dict[str, Any]


class PairInfo(BaseModel):
    pair: str
    price: Any  # Can be float or string with comma
    change: Any
    source: Optional[str] = None
    market: Optional[str] = None


class PairsGrouped(BaseModel):
    currencies: List[PairInfo]
    commodities: List[PairInfo]


class SnapshotResponse(BaseModel):
    market_status: str
    pairs: PairsGrouped
    ts: str
