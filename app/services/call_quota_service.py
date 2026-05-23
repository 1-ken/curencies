"""Per-user daily call quota enforcement."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import func, select, text

from app.core.alert_limits import CALL_DAILY_LIMIT_PER_USER
from app.models import CallUsageLog
from app.services.postgres_service import PostgresService

logger = logging.getLogger(__name__)


def utc_day_start(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


class CallQuotaService:
    """Tracks and enforces daily voice-call limits per user."""

    def __init__(
        self,
        postgres_service: Optional[PostgresService] = None,
        daily_limit: int = CALL_DAILY_LIMIT_PER_USER,
    ) -> None:
        self.postgres_service = postgres_service
        self.daily_limit = daily_limit
        self._memory_counts: Dict[str, int] = {}

    def _memory_key(self, user_id: str, day_start: datetime) -> str:
        return f"{user_id}:{day_start.date().isoformat()}"

    async def get_calls_today(self, user_id: str) -> int:
        if not user_id:
            return 0
        day_start = utc_day_start()
        if self.postgres_service and self.postgres_service._sessionmaker:
            return await self.postgres_service.count_calls_since(user_id, day_start)
        return self._memory_counts.get(self._memory_key(user_id, day_start), 0)

    async def can_place_call(self, user_id: str) -> bool:
        return (await self.get_calls_today(user_id)) < self.daily_limit

    async def reserve_call_slot(self, user_id: str, alert_id: str = "") -> Tuple[bool, str]:
        """Atomically reserve a call slot if under the daily limit.

        Returns (allowed, reason).
        """
        if not user_id:
            return False, "missing_user_id"

        if self.postgres_service and self.postgres_service._sessionmaker:
            allowed = await self.postgres_service.reserve_call_slot(
                user_id=user_id,
                alert_id=alert_id,
                daily_limit=self.daily_limit,
            )
            if allowed:
                return True, "ok"
            return False, "daily_limit_reached"

        day_start = utc_day_start()
        key = self._memory_key(user_id, day_start)
        count = self._memory_counts.get(key, 0)
        if count >= self.daily_limit:
            return False, "daily_limit_reached"
        self._memory_counts[key] = count + 1
        return True, "ok"

    def quota_message(self) -> str:
        return (
            f"Daily call limit reached ({self.daily_limit} calls per day). "
            "Try again tomorrow or use SMS/sound alerts."
        )
