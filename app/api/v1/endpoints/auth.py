"""Public authentication endpoints (register / login)."""
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.auth import AuthUserResponse, LoginRequest, RegisterRequest
from app.services.user_auth_service import UserAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

user_auth_service: UserAuthService | None = None


def set_user_auth_service(service: UserAuthService | None) -> None:
    global user_auth_service
    user_auth_service = service


@router.post("/register", response_model=AuthUserResponse)
async def register(request: RegisterRequest):
    if not user_auth_service:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

    try:
        user_id, username = await user_auth_service.register(
            request.username,
            request.password,
        )
    except ValueError as exc:
        message = str(exc)
        if "already taken" in message.lower():
            raise HTTPException(status_code=409, detail=message) from exc
        if "password must be" in message.lower() or "username must be" in message.lower():
            raise HTTPException(status_code=400, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    return AuthUserResponse(user_id=user_id, username=username)


@router.post("/login", response_model=AuthUserResponse)
async def login(request: LoginRequest):
    if not user_auth_service:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

    try:
        user_id, username = await user_auth_service.authenticate(
            request.username,
            request.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return AuthUserResponse(user_id=user_id, username=username)
