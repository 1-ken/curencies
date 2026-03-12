"""Integration-style tests for data endpoint resilience paths."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from app.api.v1.endpoints import data


class _TimeoutObserver:
    async def snapshot(self, _majors):
        await data.asyncio.sleep(0.05)
        return {"pairs": [{"pair": "EURUSD", "price": "1.1000"}], "ts": datetime.now(timezone.utc).isoformat()}


class _EmptyObserver:
    async def snapshot(self, _majors):
        return {"pairs": [], "ts": datetime.now(timezone.utc).isoformat()}


class _DataObserver:
    async def snapshot(self, _majors):
        return {
            "pairs": [{"pair": "EURUSD", "price": "1.1000"}],
            "ts": datetime.now(timezone.utc).isoformat(),
        }


class DataEndpointIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._originals = {
            "observer": data.observer,
            "snapshot_timeout": data.SNAPSHOT_TIMEOUT_SECONDS,
            "stream_interval": data.STREAM_INTERVAL,
            "max_snapshot_failures": data.MAX_SNAPSHOT_FAILURES,
            "snapshot_failure_count": data.snapshot_failure_count,
            "last_snapshot_ts": data.last_snapshot_ts,
        }

        data.SNAPSHOT_TIMEOUT_SECONDS = 0.01
        data.STREAM_INTERVAL = 1.0
        data.MAX_SNAPSHOT_FAILURES = 4
        data.snapshot_failure_count = 0
        data.last_snapshot_ts = None

    def tearDown(self):
        data.observer = self._originals["observer"]
        data.SNAPSHOT_TIMEOUT_SECONDS = self._originals["snapshot_timeout"]
        data.STREAM_INTERVAL = self._originals["stream_interval"]
        data.MAX_SNAPSHOT_FAILURES = self._originals["max_snapshot_failures"]
        data.snapshot_failure_count = self._originals["snapshot_failure_count"]
        data.last_snapshot_ts = self._originals["last_snapshot_ts"]

    async def test_snapshot_timeout_returns_504(self):
        data.observer = _TimeoutObserver()

        response = await data.snapshot()

        self.assertEqual(response.status_code, 504)
        payload = json.loads(response.body)
        self.assertEqual(payload.get("error"), "Snapshot request timed out")

    async def test_snapshot_empty_payload_returns_503(self):
        data.observer = _EmptyObserver()

        response = await data.snapshot()

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.body)
        self.assertEqual(payload.get("error"), "No fresh market data available")

    async def test_stream_health_status_transitions(self):
        data.observer = _DataObserver()

        # Healthy: no failures and fresh timestamp
        data.snapshot_failure_count = 0
        data.last_snapshot_ts = datetime.now(timezone.utc).isoformat()
        healthy_response = await data.stream_health()
        healthy = json.loads(healthy_response.body)
        self.assertEqual(healthy.get("status"), "healthy")

        # Degraded: failures below threshold with known timestamp
        data.snapshot_failure_count = 1
        data.last_snapshot_ts = datetime.now(timezone.utc).isoformat()
        degraded_response = await data.stream_health()
        degraded = json.loads(degraded_response.body)
        self.assertEqual(degraded.get("status"), "degraded")

        # Stale: failures at threshold
        data.snapshot_failure_count = data.MAX_SNAPSHOT_FAILURES
        data.last_snapshot_ts = datetime.now(timezone.utc).isoformat()
        stale_by_failure_response = await data.stream_health()
        stale_by_failure = json.loads(stale_by_failure_response.body)
        self.assertEqual(stale_by_failure.get("status"), "stale")

        # Stale: timestamp too old even with low failure count
        data.snapshot_failure_count = 1
        data.last_snapshot_ts = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()
        stale_by_age_response = await data.stream_health()
        stale_by_age = json.loads(stale_by_age_response.body)
        self.assertEqual(stale_by_age.get("status"), "stale")


if __name__ == "__main__":
    unittest.main()
