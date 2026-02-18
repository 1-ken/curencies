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
