"""Admin OTP and metrics endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.admin_auth import create_admin_token, get_admin_principal
from app.services.admin_otp_service import AdminOtpService
from app.services.postgres_service import PostgresService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

postgres_service: PostgresService | None = None
admin_otp_service: AdminOtpService | None = None


def set_admin_services(
    postgres: PostgresService | None,
    otp_service: AdminOtpService | None,
) -> None:
    global postgres_service, admin_otp_service
    postgres_service = postgres
    admin_otp_service = otp_service


class AdminOtpRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=32)


class AdminOtpVerifyRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=32)
    code: str = Field(..., min_length=4, max_length=8)


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/otp/request")
async def request_admin_otp(request: AdminOtpRequest):
    if not admin_otp_service:
        raise HTTPException(status_code=503, detail="Admin OTP service unavailable")

    try:
        await admin_otp_service.request_otp(request.phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid credentials") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True}


@router.post("/otp/verify", response_model=AdminTokenResponse)
async def verify_admin_otp(request: AdminOtpVerifyRequest):
    if not admin_otp_service:
        raise HTTPException(status_code=503, detail="Admin OTP service unavailable")

    verified = await admin_otp_service.verify_otp(request.phone, request.code)
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    return AdminTokenResponse(access_token=create_admin_token())


@router.get("/metrics/overview")
async def admin_metrics_overview(_admin=Depends(get_admin_principal)):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await postgres_service.get_admin_metrics_overview()


@router.get("/metrics/extended")
async def admin_metrics_extended(_admin=Depends(get_admin_principal)):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await postgres_service.get_admin_metrics_extended()


@router.get("/metrics/users")
async def admin_metrics_users(_admin=Depends(get_admin_principal)):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"items": await postgres_service.list_users_for_admin()}


@router.get("/alerts")
async def admin_alerts_list(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _admin=Depends(get_admin_principal),
):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {
        "items": await postgres_service.list_alerts_for_admin(
            status=status,
            limit=min(max(limit, 1), 200),
            offset=max(offset, 0),
        )
    }


@router.get("/activity")
async def admin_activity_list(
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _admin=Depends(get_admin_principal),
):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {
        "items": await postgres_service.list_activity_logs(
            event_type=event_type,
            limit=min(max(limit, 1), 200),
            offset=max(offset, 0),
        )
    }


@router.get("/users/{user_id}")
async def admin_user_detail(user_id: str, _admin=Depends(get_admin_principal)):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    detail = await postgres_service.get_user_detail_for_admin(user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    return detail


@router.get("/system/health")
async def admin_system_health(_admin=Depends(get_admin_principal)):
    """Lightweight health summary for admin overview."""
    from sqlalchemy import text

    checks: dict[str, str] = {}
    if postgres_service and postgres_service._sessionmaker:
        try:
            async with postgres_service._sessionmaker() as session:
                await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = str(exc)
    else:
        checks["postgres"] = "unavailable"

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
