"""Tests for per-user daily call quotas."""
import unittest

from app.core.alert_limits import CALL_DAILY_LIMIT_PER_USER
from app.services.call_quota_service import CallQuotaService


class TestCallQuotaMemory(unittest.IsolatedAsyncioTestCase):
    async def test_allows_up_to_daily_limit(self) -> None:
        quota = CallQuotaService(postgres_service=None, daily_limit=3)
        user_id = "user-a"

        for _ in range(3):
            allowed, reason = await quota.reserve_call_slot(user_id, "alert-1")
            self.assertTrue(allowed, reason)

        allowed, reason = await quota.reserve_call_slot(user_id, "alert-2")
        self.assertFalse(allowed)
        self.assertEqual(reason, "daily_limit_reached")
        self.assertEqual(await quota.get_calls_today(user_id), 3)

    async def test_users_are_isolated(self) -> None:
        quota = CallQuotaService(postgres_service=None, daily_limit=CALL_DAILY_LIMIT_PER_USER)

        for _ in range(CALL_DAILY_LIMIT_PER_USER):
            allowed, _ = await quota.reserve_call_slot("user-a", "a")
            self.assertTrue(allowed)

        allowed, _ = await quota.reserve_call_slot("user-b", "b")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
