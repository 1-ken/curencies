"""Public authentication endpoints (register / login)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import get_current_user_id
from app.schemas.auth import AuthUserResponse, GoogleSyncRequest, LoginRequest, RegisterRequest
from app.services.activity_log_service import log_activity
from app.services.postgres_service import PostgresService
from app.services.user_auth_service import UserAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

user_auth_service: UserAuthService | None = None
postgres_service: PostgresService | None = None


def set_user_auth_service(service: UserAuthService | None) -> None:
    global user_auth_service
    user_auth_service = service


def set_postgres_service(service: PostgresService | None) -> None:
    global postgres_service
    postgres_service = service


@router.post("/register", response_model=AuthUserResponse)
async def register(body: RegisterRequest, request: Request):
    if not user_auth_service:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

    try:
        user_id, username = await user_auth_service.register(
            body.username,
            body.password,
        )
    except ValueError as exc:
        message = str(exc)
        if "already taken" in message.lower():
            raise HTTPException(status_code=409, detail=message) from exc
        if "password must be" in message.lower() or "username must be" in message.lower():
            raise HTTPException(status_code=400, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    await log_activity(
        "register",
        user_id=user_id,
        request=request,
        metadata={"username": username},
    )
    return AuthUserResponse(user_id=user_id, username=username)


@router.post("/login", response_model=AuthUserResponse)
async def login(body: LoginRequest, request: Request):
    if not user_auth_service:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

    try:
        user_id, username = await user_auth_service.authenticate(
            body.username,
            body.password,
        )
    except ValueError as exc:
        await log_activity(
            "login_failed",
            request=request,
            metadata={"username": body.username},
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    await log_activity(
        "login_success",
        user_id=user_id,
        request=request,
        metadata={"username": username},
    )
    return AuthUserResponse(user_id=user_id, username=username)


@router.post("/oauth/google-sync", response_model=AuthUserResponse)
async def google_sync(
    body: GoogleSyncRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")

    canonical_user_id = await postgres_service.upsert_google_user(
        user_id=user_id,
        google_sub=body.google_sub,
        email=body.email,
        display_name=body.display_name,
        avatar_url=body.avatar_url,
    )

    async with postgres_service._sessionmaker() as session:
        from sqlalchemy import select
        from app.models.user import User

        result = await session.execute(select(User).where(User.user_id == canonical_user_id))
        user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=500, detail="Failed to sync Google user")

    await log_activity(
        "google_oauth",
        user_id=user.user_id,
        request=http_request,
        metadata={"email": body.email},
    )
    return AuthUserResponse(user_id=user.user_id, username=user.username)
