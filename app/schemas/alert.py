"""Alert-related Pydantic schemas."""
from typing import Optional
from pydantic import BaseModel, EmailStr


class CreateAlertRequest(BaseModel):
    """Request model for creating a new price alert (legacy live-price mode)."""
    pair: str
    target_price: float
    condition: str  # "above", "below", or "equal"
    channel: str = "email"  # "email", "sms", or "call"
    email: str = ""
    phone: str = ""
    custom_message: str = ""  # Optional custom message for the alert
    alert_type: str = "price"  # "price" for legacy live-price alerts


class CreateCandleAlertRequest(BaseModel):
    """Request model for creating a candle-close threshold alert."""
    pair: str
    interval: str  # "1m", "5m", "15m", "30m", "1h", "4h", "1d"
    direction: str  # "above" or "below"
    threshold: float  # Price level to compare candle close against
    channel: str = "email"  # "email", "sms", or "call"
    email: str = ""
    phone: str = ""
    custom_message: str = ""  # Optional custom message for the alert
    alert_type: str = "candle_close"  # Constant for this request type
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "pair": "EURUSD",
                "target_price": 1.0850,
                "condition": "above",
                "channel": "call",
                "email": "",
                "phone": "+1234567890",
                "custom_message": "Important threshold",
                "alert_type": "price"
            }
        }
    }


class AlertResponse(BaseModel):
    """Response model for alert data (supports both price and candle-close alerts)."""
    id: str
    pair: str
    alert_type: str  # "price" or "candle_close"
    status: str  # "active", "triggered", "disabled"
    channel: str
    email: str = ""
    phone: str = ""
    custom_message: str = ""
    created_at: str
    triggered_at: Optional[str] = None
    last_checked_price: Optional[float] = None
    
    # Legacy price alert fields
    target_price: Optional[float] = None
    condition: Optional[str] = None  # "above", "below", "equal"
    
    # Candle-close alert fields
    interval: Optional[str] = None  # "1m", "5m", "15m", "30m", "1h", "4h", "1d"
    direction: Optional[str] = None  # "above" or "below"
    threshold: Optional[float] = None  # Price level to compare close against
    last_evaluated_candle_time: Optional[str] = None  # When the last candle was checked
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "pair": "EURUSD",
                "target_price": 1.0850,
                "condition": "above",
                "status": "active",
                "channel": "email",
                "email": "user@example.com",
                "phone": "",
                "custom_message": "",
                "created_at": "2024-01-15T10:30:00",
                "triggered_at": None,
                "last_checked_price": 1.0820
            }
        }
    }
