"""
Alert management system for price notifications.
"""
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
import uuid

logger = logging.getLogger(__name__)

ALERTS_FILE = "alerts.json"


@dataclass
class Alert:
    """Price alert configuration."""
    id: str
    pair: str
    target_price: float
    condition: str  # "above", "below", or "equal"
    status: str  # "active", "triggered", "disabled"
    created_at: str
    email: str = ""
    channel: str = "email"  # "email" or "sms"
    phone: str = ""
    custom_message: str = ""
    triggered_at: Optional[str] = None
    last_checked_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Alert":
        return Alert(**data)


class AlertManager:
    """Manages price alerts and persistence."""

    def __init__(self, file_path: str = ALERTS_FILE):
        self.file_path = file_path
        self.alerts: Dict[str, Alert] = {}
        self._load_alerts()

    def _load_alerts(self) -> None:
        """Load alerts from file."""
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
                self.alerts = {
                    alert_id: Alert.from_dict(alert_data)
                    for alert_id, alert_data in data.items()
                }
            logger.info(f"Loaded {len(self.alerts)} alerts")
        except FileNotFoundError:
            logger.info("No existing alerts file, starting fresh")
            self.alerts = {}

    def _save_alerts(self) -> None:
        """Save alerts to file."""
        with open(self.file_path, "w") as f:
            json.dump(
                {alert_id: alert.to_dict() for alert_id, alert in self.alerts.items()},
                f,
                indent=2,
            )

    def create_alert(
        self,
        pair: str,
        target_price: float,
        condition: str,
        email: str = "",
        channel: str = "email",
        phone: str = "",
        custom_message: str = "",
    ) -> Alert:
        """Create a new alert."""
        alert_id = str(uuid.uuid4())
        alert = Alert(
            id=alert_id,
            pair=pair,
            target_price=target_price,
            condition=condition,
            email=email,
            channel=channel,
            phone=phone,
            custom_message=custom_message,
            status="active",
            created_at=datetime.now().isoformat(),
        )
        self.alerts[alert_id] = alert
        self._save_alerts()
        logger.info(f"Created alert {alert_id} for {pair} at {target_price}")
        return alert

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get alert by ID."""
        return self.alerts.get(alert_id)

    def get_all_alerts(self) -> List[Alert]:
        """Get all alerts."""
        return list(self.alerts.values())

    def _sort_alerts_by_recency(self, alerts: List[Alert]) -> List[Alert]:
        """Sort alerts by created_at (desc) and id (desc) for stable recency ordering."""
        def sort_key(alert: Alert) -> tuple:
            try:
                created_at = datetime.fromisoformat(alert.created_at)
            except (TypeError, ValueError):
                created_at = datetime.min
            return (created_at, alert.id)

        return sorted(alerts, key=sort_key, reverse=True)

    def get_active_alerts(self) -> List[Alert]:
        """Get only active alerts."""
        return [a for a in self.alerts.values() if a.status == "active"]

    def get_active_alerts_sorted(self) -> List[Alert]:
        """Get active alerts ordered by most recent creation time."""
        return self._sort_alerts_by_recency(self.get_active_alerts())

    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert."""
        if alert_id in self.alerts:
            del self.alerts[alert_id]
            self._save_alerts()
            logger.info(f"Deleted alert {alert_id}")
            return True
        return False

    def trigger_alert(self, alert_id: str, current_price: float) -> bool:
        """Mark an alert as triggered."""
        alert = self.get_alert(alert_id)
        if alert:
            alert.status = "triggered"
            alert.triggered_at = datetime.now().isoformat()
            alert.last_checked_price = current_price
            self._save_alerts()
            logger.info(f"Triggered alert {alert_id} at price {current_price}")
            return True
        return False

    def check_alerts(self, pairs_data: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Check if any active alerts should be triggered.
        Returns list of triggered alerts with their data.
        """
        triggered = []
        
        # Create price lookup - remove commas from price strings first
        # Normalize pair names: remove slashes, convert to uppercase
        prices = {}
        for item in pairs_data:
            normalized_pair = self._normalize_pair(item["pair"])
            prices[normalized_pair] = float(item["price"].replace(",", ""))
        
        for alert in self.get_active_alerts():
            normalized_alert_pair = self._normalize_pair(alert.pair)
            
            if normalized_alert_pair not in prices:
                continue
            
            current_price = prices[normalized_alert_pair]
            alert.last_checked_price = current_price
            
            should_trigger = False
            if alert.condition == "above" and current_price >= alert.target_price:
                should_trigger = True
            elif alert.condition == "below" and current_price <= alert.target_price:
                should_trigger = True
            elif alert.condition == "equal":
                # Use tolerance of 0.0001 for "equal" condition (matches within 1 pip)
                tolerance = 0.0001
                if abs(current_price - alert.target_price) <= tolerance:
                    should_trigger = True
            
            if should_trigger:
                logger.warning(
                    "⚠️  ALERT TRIGGERED: %s %s %s | Current Price: %s",
                    alert.pair, alert.condition, alert.target_price, current_price
                )
                self.trigger_alert(alert.id, current_price)
                triggered.append({
                    "alert": alert.to_dict(),
                    "current_price": current_price,
                })
        
        return triggered

    @staticmethod
    def _normalize_pair(pair: str) -> str:
        """Normalize pair name: remove slashes, convert to uppercase.
        
        Examples: 'EUR/USD' -> 'EURUSD', 'eurusd' -> 'EURUSD', 'EURUSD' -> 'EURUSD'
        """
        return pair.replace("/", "").upper()
