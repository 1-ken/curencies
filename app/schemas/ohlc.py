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


class FormingCandle(OHLCCandle):
    """OHLC candle that is still forming."""
    is_forming: bool = True
    progress_percent: Optional[float] = None
    time_remaining_seconds: Optional[float] = None


class OHLCWithFormingResponse(BaseModel):
    """Response for OHLC endpoint with forming candle."""
    pair: str
    interval: str
    start: Optional[datetime]
    end: Optional[datetime]
    closed_candles_count: int
    has_forming_candle: bool
    last_update: datetime
    candles: List[OHLCCandle]  # Can contain both closed and forming candles
