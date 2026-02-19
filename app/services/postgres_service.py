"""PostgreSQL integration for historical storage."""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, HistoricalPrice

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
        logger.info("PostgreSQL schema ensured")

    async def insert_snapshots(self, snapshots: Iterable[Dict[str, Any]]) -> int:
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        rows: List[HistoricalPrice] = []
        for snapshot in snapshots:
            observed_at = self._parse_timestamp(snapshot.get("ts"))
            title = snapshot.get("title")
            for pair_data in snapshot.get("pairs", []):
                pair = pair_data.get("pair")
                price = self._parse_price(pair_data.get("price"))
                if not pair or price is None:
                    continue
                rows.append(
                    HistoricalPrice(
                        pair=pair,
                        price=price,
                        source_title=title,
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
            stmt = stmt.where(HistoricalPrice.pair == pair)
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
            interval: Time interval (5m, 15m, 1h, 4h, 1d)
            start: Start datetime filter
            end: End datetime filter
            limit: Max number of candles to return
            
        Returns:
            List of dicts with timestamp, open, high, low, close, volume
        """
        if not self._sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        # Map interval to PostgreSQL interval
        interval_map = {
            "1m": "1 minute",
            "5m": "5 minutes",
            "15m": "15 minutes",
            "30m": "30 minutes",
            "1h": "1 hour",
            "4h": "4 hours",
            "1d": "1 day",
        }
        
        if interval not in interval_map:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {list(interval_map.keys())}")
        
        pg_interval = interval_map[interval]
        
        # Build SQL query for OHLC aggregation
        query = text("""
            WITH candles AS (
                SELECT
                    DATE_TRUNC(:interval_unit, observed_at) AS bucket,
                    (ARRAY_AGG(price ORDER BY observed_at ASC))[1] AS open,
                    MAX(price) AS high,
                    MIN(price) AS low,
                    (ARRAY_AGG(price ORDER BY observed_at DESC))[1] AS close,
                    COUNT(*) AS volume
                FROM historical_prices
                WHERE pair = :pair
                    AND (:start IS NULL OR observed_at >= :start)
                    AND (:end IS NULL OR observed_at <= :end)
                GROUP BY bucket
                ORDER BY bucket DESC
                LIMIT :limit
            )
            SELECT * FROM candles ORDER BY bucket ASC
        """)
        
        # Extract just the time unit for DATE_TRUNC (minute, hour, day)
        interval_unit = pg_interval.split()[-1].rstrip('s')  # '5 minutes' -> 'minute'
        
        params = {
            "pair": pair,
            "interval_unit": interval_unit,
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
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": int(row[5]),
                }
                for row in rows
            ]

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
