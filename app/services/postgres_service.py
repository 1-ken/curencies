"""PostgreSQL integration for historical storage."""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, HistoricalPrice, StreamMetric

logger = logging.getLogger(__name__)


class PostgresService:
    def __init__(self, dsn: str, maintenance_db: str = "postgres") -> None:
        self.dsn = dsn
        self.maintenance_db = maintenance_db
        self._engine: Optional[AsyncEngine] = None
        self._sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

    async def connect(self) -> None:
        await self._ensure_database_exists()
        self._engine = create_async_engine(self.dsn, pool_pre_ping=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        logger.info("PostgreSQL engine created")

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
            logger.info("PostgreSQL engine disposed")

    async def init_models(self) -> None:
        if not self._engine:
            raise RuntimeError("PostgreSQL engine not initialized")
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            current_pair_length = await conn.scalar(
                text(
                    """
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_name = 'historical_prices'
                      AND column_name = 'pair'
                    """
                )
            )
            if current_pair_length is not None and int(current_pair_length) < 64:
                await conn.execute(
                    text("ALTER TABLE historical_prices ALTER COLUMN pair TYPE VARCHAR(64)")
                )
                logger.info(
                    "Migrated historical_prices.pair column from VARCHAR(%s) to VARCHAR(64)",
                    current_pair_length,
                )
            source_title_exists = await conn.scalar(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'historical_prices'
                      AND column_name = 'source_title'
                    """
                )
            )
            if source_title_exists:
                await conn.execute(
                    text("ALTER TABLE historical_prices DROP COLUMN IF EXISTS source_title")
                )
                logger.info("Dropped legacy historical_prices.source_title column")
        logger.info("PostgreSQL schema ensured")

    async def insert_snapshots(self, snapshots: Iterable[Dict[str, Any]]) -> int:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        rows: List[HistoricalPrice] = []
        for snapshot in snapshots:
            observed_at = self._parse_timestamp(snapshot.get("ts"))
            for pair_data in snapshot.get("pairs", []):
                pair = self._normalize_pair(pair_data.get("pair"))
                price = self._parse_price(pair_data.get("price"))
                if not pair or price is None:
                    continue
                rows.append(
                    HistoricalPrice(
                        pair=pair,
                        price=price,
                        observed_at=observed_at,
                    )
                )

        if not rows:
            return 0

        async with self._sessionmaker() as session:
            session.add_all(rows)
            await session.commit()
        return len(rows)

    async def query_history(
        self,
        pair: Optional[str],
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
        descending: bool,
    ) -> List[HistoricalPrice]:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        stmt = select(HistoricalPrice)
        if pair:
            pair_variants = self._pair_variants(pair)
            stmt = stmt.where(HistoricalPrice.pair.in_(pair_variants))
        if start:
            stmt = stmt.where(HistoricalPrice.observed_at >= start)
        if end:
            stmt = stmt.where(HistoricalPrice.observed_at <= end)
        if descending:
            stmt = stmt.order_by(HistoricalPrice.observed_at.desc())
        else:
            stmt = stmt.order_by(HistoricalPrice.observed_at.asc())
        stmt = stmt.limit(limit)

        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def insert_stream_metric(
        self,
        *,
        observed_at: datetime,
        ws_subscriber_count: int,
        queue_subscriber_count: int,
        snapshot_failure_count: int,
        stream_status: str,
    ) -> None:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        row = StreamMetric(
            observed_at=observed_at,
            ws_subscriber_count=max(0, int(ws_subscriber_count)),
            queue_subscriber_count=max(0, int(queue_subscriber_count)),
            snapshot_failure_count=max(0, int(snapshot_failure_count)),
            stream_status=(stream_status or "healthy")[:32],
        )

        async with self._sessionmaker() as session:
            session.add(row)
            await session.commit()

    async def query_stream_metrics(
        self,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
        descending: bool,
    ) -> List[StreamMetric]:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        stmt = select(StreamMetric)
        if start:
            stmt = stmt.where(StreamMetric.observed_at >= start)
        if end:
            stmt = stmt.where(StreamMetric.observed_at <= end)
        if descending:
            stmt = stmt.order_by(StreamMetric.observed_at.desc())
        else:
            stmt = stmt.order_by(StreamMetric.observed_at.asc())
        stmt = stmt.limit(limit)

        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_old_data(self, days_to_keep: int = 14) -> Dict[str, int]:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        retention_days = max(1, int(days_to_keep))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        async with self._sessionmaker() as session:
            historical_result = await session.execute(
                delete(HistoricalPrice).where(HistoricalPrice.observed_at < cutoff)
            )
            metrics_result = await session.execute(
                delete(StreamMetric).where(StreamMetric.observed_at < cutoff)
            )
            await session.commit()

        historical_deleted = max(0, int(historical_result.rowcount or 0))
        metrics_deleted = max(0, int(metrics_result.rowcount or 0))
        return {
            "historical_deleted": historical_deleted,
            "metrics_deleted": metrics_deleted,
            "retention_days": retention_days,
        }

    async def query_ohlc(
        self,
        pair: str,
        interval: str,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query OHLC candlestick data aggregated by interval.
        
        Args:
            pair: Currency pair (e.g., EURUSD)
            interval: Time interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            start: Start datetime filter
            end: End datetime filter
            limit: Max number of candles to return
            
        Returns:
            List of dicts with timestamp, open, high, low, close, volume
        """
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        # Map interval to seconds for epoch-based bucketing
        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        
        if interval not in interval_map:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {list(interval_map.keys())}")
        
        interval_seconds = interval_map[interval]
        
        pair_variants = self._pair_variants(pair)
        pair_0 = pair_variants[0]
        pair_1 = pair_variants[1] if len(pair_variants) > 1 else pair_0
        pair_2 = pair_variants[2] if len(pair_variants) > 2 else pair_0

        # Build SQL query for OHLC aggregation using epoch-based bucketing
        # This correctly handles multi-minute intervals like 5m, 15m, 30m
        query = text("""
            WITH candles AS (
                SELECT
                    TO_TIMESTAMP((EXTRACT(EPOCH FROM observed_at)::bigint / :interval_seconds) * :interval_seconds) AS bucket,
                    (ARRAY_AGG(price ORDER BY observed_at ASC))[1] AS open,
                    MAX(price) AS high,
                    MIN(price) AS low,
                    (ARRAY_AGG(price ORDER BY observed_at DESC))[1] AS close,
                    COUNT(*) AS volume
                FROM historical_prices
                WHERE (pair = :pair_0 OR pair = :pair_1 OR pair = :pair_2)
                    AND (CAST(:start AS TIMESTAMP) IS NULL OR observed_at >= CAST(:start AS TIMESTAMP))
                    AND (CAST(:end AS TIMESTAMP) IS NULL OR observed_at <= CAST(:end AS TIMESTAMP))
                GROUP BY bucket
                ORDER BY bucket DESC
                LIMIT :limit
            )
            SELECT * FROM candles ORDER BY bucket ASC
        """)
        
        params = {
            "pair_0": pair_0,
            "pair_1": pair_1,
            "pair_2": pair_2,
            "interval_seconds": interval_seconds,
            "start": start,
            "end": end,
            "limit": limit,
        }
        
        async with self._sessionmaker() as session:
            result = await session.execute(query, params)
            rows = result.fetchall()
            
            return [
                {
                    "timestamp": row[0],
                    "open": float(row[1]) if row[1] is not None else None,
                    "high": float(row[2]) if row[2] is not None else None,
                    "low": float(row[3]) if row[3] is not None else None,
                    "close": float(row[4]) if row[4] is not None else None,
                    "volume": int(row[5]) if row[5] is not None else 0,
                }
                for row in rows
            ]

    async def get_latest_closed_candle(
        self,
        pair: str,
        interval: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent fully closed candle for a pair and interval.
        
        A candle is considered closed once the current time has passed its bucket end.
        For example, with a 15m interval, the candle closes 15 minutes after its start time.
        
        Args:
            pair: Currency pair (e.g., EURUSD)
            interval: Time interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            
        Returns:
            Dict with timestamp, open, high, low, close, volume, or None if no data
        """
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")
        
        # Map interval to seconds for epoch-based bucketing
        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        
        if interval not in interval_map:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {list(interval_map.keys())}")
        
        interval_seconds = interval_map[interval]
        
        pair_variants = self._pair_variants(pair)
        pair_0 = pair_variants[0]
        pair_1 = pair_variants[1] if len(pair_variants) > 1 else pair_0
        pair_2 = pair_variants[2] if len(pair_variants) > 2 else pair_0

        # Query: Get the candle that is fully closed (before the current bucket)
        query = text("""
            SELECT
                TO_TIMESTAMP((EXTRACT(EPOCH FROM observed_at)::bigint / :interval_seconds) * :interval_seconds) AS bucket,
                (ARRAY_AGG(price ORDER BY observed_at ASC))[1] AS open,
                MAX(price) AS high,
                MIN(price) AS low,
                (ARRAY_AGG(price ORDER BY observed_at DESC))[1] AS close,
                COUNT(*) AS volume
            FROM historical_prices
            WHERE (pair = :pair_0 OR pair = :pair_1 OR pair = :pair_2)
                AND observed_at < TO_TIMESTAMP((EXTRACT(EPOCH FROM NOW())::bigint / :interval_seconds) * :interval_seconds)
            GROUP BY bucket
            ORDER BY bucket DESC
            LIMIT 1
        """)
        
        params = {
            "pair_0": pair_0,
            "pair_1": pair_1,
            "pair_2": pair_2,
            "interval_seconds": interval_seconds,
        }
        
        async with self._sessionmaker() as session:
            result = await session.execute(query, params)
            row = result.fetchone()
            
            if not row:
                return None
            
            return {
                "pair": pair,
                "interval": interval,
                "timestamp": row[0],
                "open": float(row[1]) if row[1] is not None else None,
                "high": float(row[2]) if row[2] is not None else None,
                "low": float(row[3]) if row[3] is not None else None,
                "close": float(row[4]) if row[4] is not None else None,
                "volume": int(row[5]) if row[5] is not None else 0,
            }

    async def get_latest_closed_candles_for_alerts(
        self,
        alerts: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Get latest closed candles for all candle-type alerts.
        
        Args:
            alerts: List of alert dicts with 'pair' and 'interval' keys
            
        Returns:
            List of candle dicts with pair, interval, and OHLC data
        """
        candles = []
        for alert in alerts:
            try:
                candle = await self.get_latest_closed_candle(
                    pair=alert.get("pair"),
                    interval=alert.get("interval"),
                )
                if candle:
                    candles.append(candle)
            except Exception as e:
                logger.error(f"Failed to get candle for {alert.get('pair')} {alert.get('interval')}: {e}")
        return candles

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_price(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _normalize_pair(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        pair = str(value).strip()
        if not pair:
            return None

        compact = pair.upper().replace("/", "")
        if len(compact) == 6 and compact.isalpha():
            return compact
        return pair

    @classmethod
    def _pair_variants(cls, value: Optional[str]) -> List[str]:
        normalized = cls._normalize_pair(value)
        if not normalized:
            return []

        variants = [normalized]
        compact = normalized.upper().replace("/", "")
        if len(compact) == 6 and compact.isalpha():
            slash_pair = f"{compact[:3]}/{compact[3:]}"
            if slash_pair not in variants:
                variants.append(slash_pair)
            if compact not in variants:
                variants.append(compact)
        return variants

    async def _ensure_database_exists(self) -> None:
        url = make_url(self.dsn)
        target_db = url.database or ""
        if not target_db:
            return

        safe_db = self._safe_identifier(target_db)
        admin_url = url.set(database=self.maintenance_db)
        admin_engine = create_async_engine(admin_url, pool_pre_ping=True)

        try:
            async with admin_engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": safe_db},
                )
                exists = result.scalar() is not None
                if not exists:
                    async with admin_engine.connect() as create_conn:
                        autocommit_conn = await create_conn.execution_options(
                            isolation_level="AUTOCOMMIT"
                        )
                        await autocommit_conn.execute(text(f"CREATE DATABASE {safe_db}"))
                    logger.info("Created PostgreSQL database %s", safe_db)
        except OperationalError as exc:
            logger.warning("Unable to verify/create database: %s", exc)
            raise
        finally:
            await admin_engine.dispose()

    @staticmethod
    def _safe_identifier(name: str) -> str:
        if not re.match(r"^[A-Za-z0-9_]+$", name):
            raise ValueError("Invalid database name")
        return name
