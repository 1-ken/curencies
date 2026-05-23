"""Log of placed voice alert calls for per-user daily quotas."""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CallUsageLog(Base):
    __tablename__ = "call_usage_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    alert_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
