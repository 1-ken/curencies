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
    """Alert configuration - supports both price and candle-close modes."""
    id: str
    pair: str
    status: str  # "active", "triggered", "disabled"
    created_at: str
    alert_type: str = "price"  # "price" (legacy) or "candle_close"
    channel: str = "email"  # "email", "sms", or "call"
    email: str = ""
    phone: str = ""
    custom_message: str = ""
    triggered_at: Optional[str] = None
    last_checked_price: Optional[float] = None
    
    # Price alert fields (for alert_type="price")
    target_price: Optional[float] = None
    condition: Optional[str] = None  # "above", "below", "equal"
    
    # Candle-close alert fields (for alert_type="candle_close")
    interval: Optional[str] = None  # "1m", "5m", "15m", "30m", "1h", "4h", "1d"
    direction: Optional[str] = None  # "above" or "below"
    threshold: Optional[float] = None  # Price level to compare candle close against
    last_evaluated_candle_time: Optional[str] = None  # Timestamp of last checked candle

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Alert":
        # Handle backward compatibility: old alerts without alert_type default to "price"
        if "alert_type" not in data:
            data["alert_type"] = "price"
        return Alert(**{k: v for k, v in data.items() if k in Alert.__dataclass_fields__})


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
        """Create a new legacy price alert (alert_type='price')."""
        alert_id = str(uuid.uuid4())
        alert = Alert(
            id=alert_id,
            pair=pair,
            alert_type="price",
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
        logger.info(f"Created price alert {alert_id} for {pair} at {target_price}")
        return alert

    def create_candle_alert(
        self,
        pair: str,
        interval: str,
        direction: str,
        threshold: float,
        email: str = "",
        channel: str = "email",
        phone: str = "",
        custom_message: str = "",
    ) -> Alert:
        """Create a new candle-close threshold alert (alert_type='candle_close')."""
        alert_id = str(uuid.uuid4())
        alert = Alert(
            id=alert_id,
            pair=pair,
            alert_type="candle_close",
            interval=interval,
            direction=direction,
            threshold=threshold,
            email=email,
            channel=channel,
            phone=phone,
            custom_message=custom_message,
            status="active",
            created_at=datetime.now().isoformat(),
            last_evaluated_candle_time=None,
        )
        self.alerts[alert_id] = alert
        self._save_alerts()
        logger.info(f"Created candle-close alert {alert_id} for {pair} {interval} {direction} {threshold}")
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
    def check_candle_alerts(self, ohlc_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Check candle-close threshold alerts against latest closed candles.
        
        Args:
            ohlc_data: List of OHLC candle dicts with keys:
                       pair, interval, timestamp, open, high, low, close, volume
        
        Returns:
            List of triggered alerts with their data.
        """
        triggered = []
        
        # Build lookup: (pair, interval) -> latest candle
        candle_lookup: Dict[tuple, Dict[str, Any]] = {}
        for candle in ohlc_data:
            key = (self._normalize_pair(candle.get("pair", "")), candle.get("interval", ""))
            # Keep the most recent (first in returned list if query sorts DESC then ASC)
            if key not in candle_lookup:
                candle_lookup[key] = candle
        
        # Check all active candle-close alerts
        for alert in self.get_active_alerts():
            if alert.alert_type != "candle_close":
                continue
            
            key = (self._normalize_pair(alert.pair), alert.interval)
            if key not in candle_lookup:
                logger.debug(f"No candle data for {alert.pair} {alert.interval}")
                continue
            
            candle = candle_lookup[key]
            close_price = candle.get("close", 0.0)
            candle_time = candle.get("timestamp")
            
            # Skip if we already evaluated this exact candle for this alert
            if alert.last_evaluated_candle_time == str(candle_time):
                continue
            
            should_trigger = False
            if alert.direction == "above" and close_price >= alert.threshold:
                should_trigger = True
            elif alert.direction == "below" and close_price <= alert.threshold:
                should_trigger = True
            
            if should_trigger:
                logger.warning(
                    "⚠️  CANDLE ALERT TRIGGERED: %s %s %s close=%s threshold=%s",
                    alert.pair, alert.interval, alert.direction, close_price, alert.threshold
                )
                # Mark as triggered and save evaluation timestamp
                alert.status = "triggered"
                alert.triggered_at = datetime.now().isoformat()
                alert.last_checked_price = close_price
                alert.last_evaluated_candle_time = str(candle_time)
                self._save_alerts()
                triggered.append({
                    "alert": alert.to_dict(),
                    "current_price": close_price,
                })
            else:
                # Update last evaluated candle time even if not triggered (for next iteration)
                alert.last_evaluated_candle_time = str(candle_time)
                self._save_alerts()
        
        return triggered