"""Alert persistence model."""
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False, default="legacy-unassigned"
    )
    pair: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    alert_type: Mapped[str] = mapped_column(String(16), nullable=False, default="price")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="email")
    email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    custom_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition: Mapped[str | None] = mapped_column(String(16), nullable=True)

    interval: Mapped[str | None] = mapped_column(String(8), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_evaluated_candle_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
