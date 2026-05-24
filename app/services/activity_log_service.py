"""Fire-and-forget user activity logging."""
import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import Request

from app.services.postgres_service import PostgresService
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

postgres_service: PostgresService | None = None


def set_postgres_service(service: PostgresService | None) -> None:
    global postgres_service
    postgres_service = service


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    value = request.headers.get("user-agent", "")
    return value[:512] if value else None


async def log_activity(
    event_type: str,
    *,
    user_id: str | None = None,
    request: Request | None = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    if not postgres_service:
        return

    try:
        await postgres_service.insert_activity_log(
            id=str(uuid4()),
            user_id=user_id,
            event_type=event_type,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("Activity log insert failed (%s): %s", event_type, exc)
