"""OHLC candlestick schemas."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class OHLCCandle(BaseModel):
    """Single OHLC candlestick."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int  # Number of ticks in this candle
    expected_open: Optional[datetime] = None
    expected_close: Optional[datetime] = None


class OHLCResponse(BaseModel):
    """Response for OHLC endpoint."""
    pair: str
    interval: str
    start: Optional[datetime]
    end: Optional[datetime]
    count: int
    candles: List[OHLCCandle]
