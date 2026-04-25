"""Historical data schemas."""
from datetime import datetime

from pydantic import BaseModel


class HistoricalPriceResponse(BaseModel):
    pair: str
    price: float
    observed_at: datetime


class HistoricalQueryResponse(BaseModel):
    count: int
    items: list[HistoricalPriceResponse]


class StreamMetricItem(BaseModel):
    observed_at: datetime
    ws_subscriber_count: int
    queue_subscriber_count: int
    snapshot_failure_count: int
    stream_status: str


class StreamMetricsResponse(BaseModel):
    count: int
    items: list[StreamMetricItem]
