"""Apply versioned SQL migrations from scripts/migrations on startup."""
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "migrations"

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(128) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL file into executable statements (simple semicolon split)."""
    statements: list[str] = []
    buffer: list[str] = []

    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            buffer = []
            if statement:
                statements.append(statement.rstrip(";").strip())

    remainder = "\n".join(buffer).strip()
    if remainder:
        statements.append(remainder.rstrip(";").strip())

    return [statement for statement in statements if statement]


async def run_pending_sql_migrations(conn: AsyncConnection) -> list[str]:
    """
    Apply any *.sql files in scripts/migrations not yet recorded in schema_migrations.
    Returns the list of migration versions applied this run.
    """
    if not MIGRATIONS_DIR.is_dir():
        logger.warning("Migrations directory not found: %s", MIGRATIONS_DIR)
        return []

    await conn.execute(text(_CREATE_MIGRATIONS_TABLE))
    result = await conn.execute(text("SELECT version FROM schema_migrations"))
    applied = {row[0] for row in result.fetchall()}

    applied_now: list[str] = []
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)

    for migration_path in migration_files:
        version = migration_path.stem
        if version in applied:
            continue

        raw_sql = migration_path.read_text(encoding="utf-8").strip()
        if not raw_sql:
            logger.warning("Skipping empty migration file: %s", migration_path.name)
            continue

        logger.info("Applying SQL migration: %s", migration_path.name)
        for statement in _split_sql_statements(raw_sql):
            await conn.execute(text(statement))

        await conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": version},
        )
        applied_now.append(version)
        logger.info("Migration applied: %s", version)

    if not applied_now:
        logger.info("Database migrations up to date (%s checked)", len(migration_files))
    else:
        logger.info("Applied %s migration(s): %s", len(applied_now), ", ".join(applied_now))

    return applied_now
