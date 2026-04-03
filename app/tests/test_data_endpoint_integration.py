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


class _HistoryRow:
    def __init__(self, pair: str, price: float, observed_at: datetime):
        self.pair = pair
        self.price = price
        self.observed_at = observed_at


class _MetricRow:
    def __init__(
        self,
        observed_at: datetime,
        ws_subscriber_count: int,
        queue_subscriber_count: int,
        snapshot_failure_count: int,
        stream_status: str,
    ):
        self.observed_at = observed_at
        self.ws_subscriber_count = ws_subscriber_count
        self.queue_subscriber_count = queue_subscriber_count
        self.snapshot_failure_count = snapshot_failure_count
        self.stream_status = stream_status


class _OHLCPostgresService:
    async def query_ohlc(self, pair, interval, start, end, limit):
        return [
            {
                "timestamp": datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc),
                "open": 1.1,
                "high": 1.2,
                "low": 1.0,
                "close": 1.15,
                "volume": 42,
            }
        ]


class _BucketPriceRow:
    def __init__(self, price: float):
        self.price = price


class _StreamOHLCPostgresService:
    async def query_history(self, pair, start, end, limit, descending):
        return [_BucketPriceRow(1.1), _BucketPriceRow(1.12), _BucketPriceRow(1.11)]


class _HistoryPostgresService:
    def __init__(self):
        self.last_query_start = None
        self.last_metrics_query_start = None

    async def query_history(self, pair, start, end, limit, descending):
        self.last_query_start = start
        return [
            _HistoryRow(
                pair="EURUSD",
                price=1.1000,
                observed_at=start,
            )
        ]

    async def query_stream_metrics(self, start, end, limit, descending):
        self.last_metrics_query_start = start
        return [
            _MetricRow(
                observed_at=start,
                ws_subscriber_count=3,
                queue_subscriber_count=2,
                snapshot_failure_count=0,
                stream_status="healthy",
            )
        ]


class DataEndpointIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._originals = {
            "observer": data.observer,
            "postgres_service": data.postgres_service,
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
        data.postgres_service = self._originals["postgres_service"]
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

    async def test_historical_data_enforces_14_day_retention_floor(self):
        fake_pg = _HistoryPostgresService()
        data.postgres_service = fake_pg

        response = await data.historical_data(start=None, end=None, limit=100)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload.get("count"), 1)

        observed_at = datetime.fromisoformat(payload["items"][0]["observed_at"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        self.assertGreaterEqual(observed_at, cutoff - timedelta(seconds=2))
        self.assertIsNotNone(fake_pg.last_query_start)
        self.assertGreaterEqual(fake_pg.last_query_start, cutoff - timedelta(seconds=2))

    async def test_stream_metrics_enforce_14_day_retention_floor(self):
        fake_pg = _HistoryPostgresService()
        data.postgres_service = fake_pg

        response = await data.historical_stream_metrics(start=None, end=None, limit=100)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload.get("count"), 1)

        observed_at = datetime.fromisoformat(payload["items"][0]["observed_at"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        self.assertGreaterEqual(observed_at, cutoff - timedelta(seconds=2))
        self.assertIsNotNone(fake_pg.last_metrics_query_start)
        self.assertGreaterEqual(fake_pg.last_metrics_query_start, cutoff - timedelta(seconds=2))

    async def test_historical_ohlc_includes_expected_open_close(self):
        data.postgres_service = _OHLCPostgresService()

        response = await data.historical_ohlc(pair="EURUSD", interval="4H", limit=10)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload.get("interval"), "4h")
        self.assertEqual(payload.get("count"), 1)
        candle = payload["candles"][0]
        self.assertIn("expected_open", candle)
        self.assertIn("expected_close", candle)

    async def test_stream_ohlc_metadata_includes_expected_open_close(self):
        data.postgres_service = _StreamOHLCPostgresService()

        ohlc = await data._build_stream_ohlc_for_pair("EURUSD", 1.13, "15m")

        self.assertIsNotNone(ohlc)
        self.assertIn("expected_open", ohlc)
        self.assertIn("expected_close", ohlc)


if __name__ == "__main__":
    unittest.main()
