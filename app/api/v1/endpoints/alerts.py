"""Alert management endpoints."""
import logging
from typing import Union

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.core.alert_limits import validate_custom_message_for_channel
from app.core.channels import (
    channel_requires_email,
    channel_requires_phone,
    validate_alert_channel,
)
from app.utils.phone import normalize_phone
from app.schemas.alert import (
    CreateAlertRequest,
    UpdateAlertRequest,
    CreateCandleAlertRequest,
    UpdateCandleAlertRequest,
    AlertResponse,
    AlertListResponse,
    CreateUpdateAlertResponse,
    DeleteAlertResponse,
)
from app.services.alert_service import AlertManager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    responses={404: {"description": "Not found"}},
)

alert_manager: AlertManager = None


def _validate_channel_fields(channel: str, email: str, phone: str) -> None:
    try:
        validate_alert_channel(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel_requires_email(channel) and not email:
        raise HTTPException(status_code=400, detail="Email is required for email alerts")
    if channel_requires_phone(channel) and not phone:
        detail = "Phone is required for SMS alerts" if channel == "sms" else "Phone is required for call alerts"
        raise HTTPException(status_code=400, detail=detail)


def _prepare_alert_fields(channel: str, email: str, phone: str, custom_message: str) -> tuple[str, str, str]:
    """Normalize phone and validate custom message for the channel."""
    try:
        validate_custom_message_for_channel(channel, custom_message or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_phone = normalize_phone(phone) if channel in ("sms", "call") else (phone or "")
    return email or "", normalized_phone, custom_message or ""


def _validate_channel_update(channel: str, email: str | None, phone: str | None, alert) -> None:
    try:
        validate_alert_channel(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel_requires_email(channel) and not (email or alert.email):
        raise HTTPException(status_code=400, detail="Email is required for email alerts")
    if channel_requires_phone(channel) and not (phone or alert.phone):
        detail = "Phone is required for SMS alerts" if channel == "sms" else "Phone is required for call alerts"
        raise HTTPException(status_code=400, detail=detail)


def set_alert_manager(manager: AlertManager):
    """Set the global alert manager instance."""
    global alert_manager
    alert_manager = manager


@router.post("", response_model=CreateUpdateAlertResponse)
async def create_alert(
    request: Union[CreateAlertRequest, CreateCandleAlertRequest],
    user_id: str = Depends(get_current_user_id),
):
    """Create a new alert (price-based or candle-close)."""
    pair = request.pair.strip()
    if not pair:
        raise HTTPException(status_code=400, detail="Pair name cannot be empty")

    if ":" in pair:
        parts = pair.split(":")
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise HTTPException(
                status_code=400,
                detail="Commodity pair must be in format 'SYMBOL:TYPE' (e.g., 'XAUUSD:CUR', 'HG1:COM')",
            )

    if hasattr(request, "interval") and request.interval:
        request.interval = request.interval.strip().lower()
        _validate_channel_fields(request.channel, request.email, request.phone)
        email, phone, custom_message = _prepare_alert_fields(
            request.channel, request.email, request.phone, request.custom_message
        )

        if request.direction not in ["above", "below"]:
            raise HTTPException(status_code=400, detail="Direction must be 'above' or 'below'")

        valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        if request.interval not in valid_intervals:
            raise HTTPException(
                status_code=400,
                detail=f"Interval must be one of: {', '.join(valid_intervals)}",
            )

        try:
            alert = await alert_manager.create_candle_alert(
                pair=request.pair,
                interval=request.interval,
                direction=request.direction,
                threshold=request.threshold,
                user_id=user_id,
                email=email,
                channel=request.channel,
                phone=phone,
                custom_message=custom_message,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"success": True, "alert": alert.to_dict()}

    if request.condition not in ["above", "below", "equal"]:
        raise HTTPException(status_code=400, detail="Condition must be 'above', 'below', or 'equal'")

    _validate_channel_fields(request.channel, request.email, request.phone)
    email, phone, custom_message = _prepare_alert_fields(
        request.channel, request.email, request.phone, request.custom_message
    )

    alert = await alert_manager.create_alert(
        pair=request.pair,
        target_price=request.target_price,
        condition=request.condition,
        user_id=user_id,
        email=email,
        channel=request.channel,
        phone=phone,
        custom_message=custom_message,
    )
    return {"success": True, "alert": alert.to_dict()}


@router.get("", response_model=AlertListResponse)
async def get_alerts(user_id: str = Depends(get_current_user_id)):
    """Get alerts for the authenticated user."""
    all_alerts = alert_manager.get_all_alerts_for_user(user_id)
    return {
        "total": len(all_alerts),
        "active": [a.to_dict() for a in alert_manager.get_active_alerts_sorted_for_user(user_id)],
        "triggered": [a.to_dict() for a in all_alerts if a.status == "triggered"],
        "all": [a.to_dict() for a in all_alerts],
    }


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, user_id: str = Depends(get_current_user_id)):
    """Get a specific alert owned by the user."""
    if not alert_manager.is_alert_owned_by(alert_id, user_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    alert = alert_manager.get_alert(alert_id)
    return alert.to_dict()


@router.delete("/{alert_id}", response_model=DeleteAlertResponse)
async def delete_alert(alert_id: str, user_id: str = Depends(get_current_user_id)):
    """Delete an alert owned by the user."""
    if await alert_manager.delete_alert(alert_id, user_id=user_id):
        return {"success": True, "message": "Alert deleted"}
    raise HTTPException(status_code=404, detail="Alert not found")


@router.put("/{alert_id}", response_model=CreateUpdateAlertResponse)
async def update_alert(
    alert_id: str,
    request: Union[UpdateAlertRequest, UpdateCandleAlertRequest],
    user_id: str = Depends(get_current_user_id),
):
    """Update an existing alert owned by the user."""
    alert = alert_manager.get_alert(alert_id)
    if not alert or alert.user_id != user_id:
        raise HTTPException(status_code=404, detail="Alert not found")

    updates = request.model_dump(exclude_unset=True)
    updates.pop("user_id", None)

    effective_channel = updates.get("channel", alert.channel)
    if "custom_message" in updates:
        try:
            validate_custom_message_for_channel(effective_channel, updates["custom_message"] or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "phone" in updates and effective_channel in ("sms", "call"):
        updates["phone"] = normalize_phone(updates["phone"] or "")

    if alert.alert_type == "price":
        if "condition" in updates and updates["condition"] not in ["above", "below", "equal"]:
            raise HTTPException(status_code=400, detail="Condition must be 'above', 'below', or 'equal'")
        if "channel" in updates:
            _validate_channel_update(
                updates["channel"],
                updates.get("email"),
                updates.get("phone"),
                alert,
            )
        if "status" in updates and updates["status"] not in ["active", "triggered", "disabled"]:
            raise HTTPException(status_code=400, detail="Status must be 'active', 'triggered', or 'disabled'")

    elif alert.alert_type == "candle_close":
        if "direction" in updates and updates["direction"] not in ["above", "below"]:
            raise HTTPException(status_code=400, detail="Direction must be 'above' or 'below'")
        if "channel" in updates:
            _validate_channel_update(
                updates["channel"],
                updates.get("email"),
                updates.get("phone"),
                alert,
            )
        if "status" in updates and updates["status"] not in ["active", "triggered", "disabled"]:
            raise HTTPException(status_code=400, detail="Status must be 'active', 'triggered', or 'disabled'")

    updated_alert = await alert_manager.update_alert(alert_id, updates, user_id=user_id)
    if not updated_alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return {"success": True, "alert": updated_alert.to_dict()}
