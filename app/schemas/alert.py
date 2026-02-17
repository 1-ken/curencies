"""Alert-related Pydantic schemas."""
from typing import Optional
from pydantic import BaseModel, EmailStr


class CreateAlertRequest(BaseModel):
    """Request model for creating a new price alert."""
    pair: str
    target_price: float
    condition: str  # "above", "below", or "equal"
    channel: str = "email"  # "email" or "sms"
    email: str = ""
    phone: str = ""
    custom_message: str = ""  # Optional custom message for the alert
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "pair": "EURUSD",
                "target_price": 1.0850,
                "condition": "above",
                "channel": "email",
                "email": "user@example.com",
                "phone": "",
                "custom_message": "Important threshold"
            }
        }
    }


class AlertResponse(BaseModel):
    """Response model for alert data."""
    id: str
    pair: str
    target_price: float
    condition: str
    status: str  # "active", "triggered", "disabled"
    channel: str
    email: str = ""
    phone: str = ""
    custom_message: str = ""
    created_at: str
    triggered_at: Optional[str] = None
    last_checked_price: Optional[float] = None
    
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
