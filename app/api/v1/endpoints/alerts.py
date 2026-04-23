"""Alert management endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from typing import Union

from app.schemas.alert import (
    CreateAlertRequest, 
    UpdateAlertRequest,
    CreateCandleAlertRequest,
    UpdateCandleAlertRequest,
    AlertResponse
)
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
async def create_alert(request: Union[CreateAlertRequest, CreateCandleAlertRequest]):
    """Create a new alert (price-based or candle-close).
    
    Request body can be either:
    - CreateAlertRequest for price-based alerts (alert_type="price" or omitted)
    - CreateCandleAlertRequest for candle-close alerts (alert_type="candle_close")
    """
    # Validate pair format first
    pair = request.pair.strip()
    if not pair:
        raise HTTPException(status_code=400, detail="Pair name cannot be empty")
    
    # Validate commodity pair format if it contains a colon
    if ':' in pair:
        parts = pair.split(':')
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise HTTPException(
                status_code=400,
                detail="Commodity pair must be in format 'SYMBOL:TYPE' (e.g., 'XAUUSD:CUR', 'HG1:COM')"
            )
    
    # Try to parse as candle alert first (has 'interval' field)
    if hasattr(request, 'interval') and request.interval:
        request.interval = request.interval.strip().lower()
        # Candle-close alert
        if request.channel not in ["email", "sms", "call"]:
            raise HTTPException(status_code=400, detail="Channel must be 'email', 'sms', or 'call'")
        if request.channel == "email" and not request.email:
            raise HTTPException(status_code=400, detail="Email is required for email alerts")
        if request.channel == "sms" and not request.phone:
            raise HTTPException(status_code=400, detail="Phone is required for SMS alerts")
        if request.channel == "call" and not request.phone:
            raise HTTPException(status_code=400, detail="Phone is required for call alerts")
        
        if request.direction not in ["above", "below"]:
            raise HTTPException(status_code=400, detail="Direction must be 'above' or 'below'")
        
        valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        if request.interval not in valid_intervals:
            raise HTTPException(status_code=400, detail=f"Interval must be one of: {', '.join(valid_intervals)}")
        
        try:
            alert = alert_manager.create_candle_alert(
                pair=request.pair,
                interval=request.interval,
                direction=request.direction,
                threshold=request.threshold,
                email=request.email,
                channel=request.channel,
                phone=request.phone,
                custom_message=request.custom_message,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"success": True, "alert": alert.to_dict()}
    else:
        # Price-based alert (legacy)
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
        "active": [a.to_dict() for a in alert_manager.get_active_alerts_sorted()],
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


@router.put("/{alert_id}", response_model=dict)
async def update_alert(alert_id: str, request: Union[UpdateAlertRequest, UpdateCandleAlertRequest]):
    """Update an existing alert (price-based or candle-close).
    
    Supports partial updates - only include fields you want to change.
    """
    alert = alert_manager.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Prepare updates dict from request
    updates = request.model_dump(exclude_unset=True)
    
    # Validate updates based on alert type
    if alert.alert_type == "price":
        # Price alert validation
        if "condition" in updates and updates["condition"] not in ["above", "below", "equal"]:
            raise HTTPException(status_code=400, detail="Condition must be 'above', 'below', or 'equal'")
        
        if "channel" in updates and updates["channel"] not in ["email", "sms", "call"]:
            raise HTTPException(status_code=400, detail="Channel must be 'email', 'sms', or 'call'")
        
        if updates.get("channel") == "email" and not updates.get("email"):
            if not alert.email and not updates.get("email"):
                raise HTTPException(status_code=400, detail="Email is required for email alerts")
        if updates.get("channel") == "sms" and not updates.get("phone"):
            if not alert.phone and not updates.get("phone"):
                raise HTTPException(status_code=400, detail="Phone is required for SMS alerts")
        if updates.get("channel") == "call" and not updates.get("phone"):
            if not alert.phone and not updates.get("phone"):
                raise HTTPException(status_code=400, detail="Phone is required for call alerts")
        
        if "status" in updates and updates["status"] not in ["active", "triggered", "disabled"]:
            raise HTTPException(status_code=400, detail="Status must be 'active', 'triggered', or 'disabled'")
    
    elif alert.alert_type == "candle_close":
        # Candle alert validation
        if "direction" in updates and updates["direction"] not in ["above", "below"]:
            raise HTTPException(status_code=400, detail="Direction must be 'above' or 'below'")
        
        if "channel" in updates and updates["channel"] not in ["email", "sms", "call"]:
            raise HTTPException(status_code=400, detail="Channel must be 'email', 'sms', or 'call'")
        
        if updates.get("channel") == "email" and not updates.get("email"):
            if not alert.email and not updates.get("email"):
                raise HTTPException(status_code=400, detail="Email is required for email alerts")
        if updates.get("channel") == "sms" and not updates.get("phone"):
            if not alert.phone and not updates.get("phone"):
                raise HTTPException(status_code=400, detail="Phone is required for SMS alerts")
        if updates.get("channel") == "call" and not updates.get("phone"):
            if not alert.phone and not updates.get("phone"):
                raise HTTPException(status_code=400, detail="Phone is required for call alerts")
        
        if "status" in updates and updates["status"] not in ["active", "triggered", "disabled"]:
            raise HTTPException(status_code=400, detail="Status must be 'active', 'triggered', or 'disabled'")
    
    # Perform update
    updated_alert = alert_manager.update_alert(alert_id, updates)
    if not updated_alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return {"success": True, "alert": updated_alert.to_dict()}
