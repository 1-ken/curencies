"""Historical forex and stream metrics models."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class HistoricalPrice(Base):
    __tablename__ = "historical_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    source_title: Mapped[str] = mapped_column(String(255), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class StreamMetric(Base):
    __tablename__ = "stream_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    ws_subscriber_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_subscriber_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stream_status: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")
