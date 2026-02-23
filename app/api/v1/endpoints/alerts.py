"""Alert management endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.schemas.alert import CreateAlertRequest, AlertResponse
from app.services.alert_service import AlertManager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    responses={404: {"description": "Not found"}},
)

# Global alert manager instance
alert_manager: AlertManager = None


def set_alert_manager(manager: AlertManager):
    """Set the global alert manager instance."""
    global alert_manager
    alert_manager = manager


@router.post("", response_model=dict)
async def create_alert(request: CreateAlertRequest):
    """Create a new price alert."""
    if request.condition not in ["above", "below", "equal"]:
        raise HTTPException(status_code=400, detail="Condition must be 'above', 'below', or 'equal'")
    
    if request.channel not in ["email", "sms", "call"]:
        raise HTTPException(status_code=400, detail="Channel must be 'email', 'sms', or 'call'")
    if request.channel == "email" and not request.email:
        raise HTTPException(status_code=400, detail="Email is required for email alerts")
    if request.channel == "sms" and not request.phone:
        raise HTTPException(status_code=400, detail="Phone is required for SMS alerts")
    if request.channel == "call" and not request.phone:
        raise HTTPException(status_code=400, detail="Phone is required for call alerts")

    alert = alert_manager.create_alert(
        pair=request.pair,
        target_price=request.target_price,
        condition=request.condition,
        email=request.email,
        channel=request.channel,
        phone=request.phone,
        custom_message=request.custom_message,
    )
    return {"success": True, "alert": alert.to_dict()}


@router.get("", response_model=dict)
async def get_alerts():
    """Get all alerts."""
    all_alerts = alert_manager.get_all_alerts()
    return {
        "total": len(all_alerts),
        "active": [a.to_dict() for a in all_alerts if a.status == "active"],
        "triggered": [a.to_dict() for a in all_alerts if a.status == "triggered"],
        "all": [a.to_dict() for a in all_alerts],
    }


@router.get("/{alert_id}", response_model=dict)
async def get_alert(alert_id: str):
    """Get specific alert."""
    alert = alert_manager.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert.to_dict()


@router.delete("/{alert_id}", response_model=dict)
async def delete_alert(alert_id: str):
    """Delete an alert."""
    if alert_manager.delete_alert(alert_id):
        return {"success": True, "message": "Alert deleted"}
    raise HTTPException(status_code=404, detail="Alert not found")
