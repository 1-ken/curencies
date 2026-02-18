"""Historical data schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HistoricalPriceResponse(BaseModel):
    pair: str
    price: float
    observed_at: datetime
    source_title: Optional[str] = None


class HistoricalQueryResponse(BaseModel):
    count: int
    items: list[HistoricalPriceResponse]
