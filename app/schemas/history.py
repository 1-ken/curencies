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
