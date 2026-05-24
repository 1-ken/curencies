"""Persisted OHLC candle rows."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OhlcCandle(Base):
    __tablename__ = "ohlc_candles"
    __table_args__ = (
        UniqueConstraint("pair", "interval", "bucket_time", name="uq_ohlc_candles_pair_interval_bucket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    interval: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    bucket_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
