"""
Alert management system for price notifications.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
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
    close_price: Optional[float] = None
    
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
                self.alerts = {}
                for alert_id, alert_data in data.items():
                    alert_obj = Alert.from_dict(alert_data)
                    if alert_obj.alert_type == "candle_close":
                        alert_obj.interval = self._normalize_interval(alert_obj.interval)
                    self.alerts[alert_id] = alert_obj
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

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        normalized = str(value).strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _interval_seconds(interval: Optional[str]) -> Optional[int]:
        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }
        return interval_map.get(interval)

    @staticmethod
    def _normalize_interval(interval: Optional[str]) -> Optional[str]:
        if interval is None:
            return None
        return str(interval).strip().lower()

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
            created_at=self._utc_now_iso(),
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
        normalized_interval = self._normalize_interval(interval)
        if self._interval_seconds(normalized_interval) is None:
            raise ValueError("Invalid interval. Must be one of: 1m, 5m, 15m, 30m, 1h, 4h, 1d")

        alert_id = str(uuid.uuid4())
        alert = Alert(
            id=alert_id,
            pair=pair,
            alert_type="candle_close",
            interval=normalized_interval,
            direction=direction,
            threshold=threshold,
            email=email,
            channel=channel,
            phone=phone,
            custom_message=custom_message,
            status="active",
            created_at=self._utc_now_iso(),
            last_evaluated_candle_time=None,
        )
        self.alerts[alert_id] = alert
        self._save_alerts()
        logger.info(f"Created candle-close alert {alert_id} for {pair} {normalized_interval} {direction} {threshold}")
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
            # Use _parse_iso_utc to ensure all datetimes are UTC-aware for comparison
            created_at = self._parse_iso_utc(alert.created_at)
            if created_at is None:
                created_at = datetime.min.replace(tzinfo=timezone.utc)
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

    def update_alert(self, alert_id: str, updates: Dict[str, Any]) -> Optional[Alert]:
        """Update an existing alert with new values.
        
        Args:
            alert_id: ID of alert to update
            updates: Dict of fields to update (target_price, condition, channel, email, phone, custom_message, status)
            
        Returns:
            Updated Alert object or None if not found
        """
        alert = self.get_alert(alert_id)
        if not alert:
            return None
        
        # For price alerts
        if alert.alert_type == "price":
            for key in ["target_price", "condition", "channel", "email", "phone", "custom_message", "status"]:
                if key in updates and updates[key] is not None:
                    setattr(alert, key, updates[key])
        
        # For candle-close alerts
        elif alert.alert_type == "candle_close":
            if "interval" in updates and updates["interval"] is not None:
                normalized_interval = self._normalize_interval(updates["interval"])
                if self._interval_seconds(normalized_interval) is None:
                    raise ValueError("Invalid interval. Must be one of: 1m, 5m, 15m, 30m, 1h, 4h, 1d")
                updates["interval"] = normalized_interval
            for key in ["direction", "threshold", "channel", "email", "phone", "custom_message", "status"]:
                if key in updates and updates[key] is not None:
                    setattr(alert, key, updates[key])
        
        self._save_alerts()
        logger.info(f"Updated alert {alert_id}")
        return alert

    def trigger_alert(self, alert_id: str, current_price: float) -> bool:
        """Mark an alert as triggered."""
        alert = self.get_alert(alert_id)
        if alert:
            alert.status = "triggered"
            alert.triggered_at = self._utc_now_iso()
            alert.last_checked_price = current_price
            alert.close_price = current_price
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
        
        # Create price lookup - handle numeric or string prices safely
        prices = {}
        for item in pairs_data:
            pair_raw = item.get("pair")
            price_raw = item.get("price")
            if not pair_raw or price_raw is None:
                continue
                
            try:
                normalized_pair = self._normalize_pair(pair_raw)
                # Remove commas from price strings before conversion
                price_str = str(price_raw).replace(",", "")
                prices[normalized_pair] = float(price_str)
            except (ValueError, TypeError):
                logger.debug(f"Skipping invalid price data for {pair_raw}: {price_raw}")
                continue

        active_alerts = self.get_active_alerts()
        
        for alert in active_alerts:
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
        """Normalize pair name to a canonical symbol key.
        
        Handles both currency pairs and commodity pairs:
        - Currency: 'EUR/USD' -> 'EURUSD', 'EURUSD' -> 'EURUSD'
        - Commodity: 'XAUUSD:CUR' -> 'XAUUSD', 'HG1:COM' -> 'HG1'
        
        This aligns with PostgresService normalization and ensures consistency
        across the system and diagnostic tools.
        """
        if not pair:
            return ""
        
        # 1. Strip whitespace and convert to uppercase
        pair = str(pair).strip().upper()

        # 2. Remove provider/exchange suffixes like :CUR, :COM, :IDX
        if ":" in pair:
            pair = pair.split(":", 1)[0]
        
        # 3. For currency pairs (6 chars when slash removed), remove the slash
        compact = pair.replace("/", "")
        if len(compact) == 6 and compact.isalpha():
            return compact
            
        # 4. For commodities and others, return canonical uppercase base symbol
        return pair

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
            normalized_interval = self._normalize_interval(candle.get("interval", ""))
            key = (self._normalize_pair(candle.get("pair", "")), normalized_interval)
            # Keep the most recent (first in returned list if query sorts DESC then ASC)
            if key not in candle_lookup:
                candle_lookup[key] = candle

        active_candle_alerts = [
            alert for alert in self.get_active_alerts()
            if alert.alert_type == "candle_close"
        ]
    
        # Check all active candle-close alerts
        for alert in active_candle_alerts:
            normalized_alert_interval = self._normalize_interval(alert.interval)
            key = (self._normalize_pair(alert.pair), normalized_alert_interval)
            if key not in candle_lookup:
                logger.debug(f"No candle data for {alert.pair} {alert.interval}")
                continue
            
            candle = candle_lookup[key]
            try:
                close_price = float(candle.get("close", 0.0))
            except (TypeError, ValueError):
                logger.debug("Invalid candle close value for %s %s", alert.pair, alert.interval)
                continue
            candle_time = candle.get("timestamp")

            candle_start = None
            if isinstance(candle_time, datetime):
                candle_start = candle_time if candle_time.tzinfo else candle_time.replace(tzinfo=timezone.utc)
                candle_start = candle_start.astimezone(timezone.utc)
            else:
                candle_start = self._parse_iso_utc(str(candle_time))

            interval_seconds = self._interval_seconds(alert.interval)
            alert_created_at = self._parse_iso_utc(alert.created_at)

            # If timestamps are parseable, only evaluate candles that closed strictly after alert creation.
            if candle_start and interval_seconds and alert_created_at:
                candle_close_time = candle_start + timedelta(seconds=interval_seconds)
                if candle_close_time <= alert_created_at:
                    # Mark stale pre-creation candle as evaluated to avoid repeated checks.
                    alert.last_evaluated_candle_time = str(candle_time)
                    self._save_alerts()
                    continue
            
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
                alert.triggered_at = self._utc_now_iso()
                alert.last_checked_price = close_price
                alert.close_price = close_price
                alert.last_evaluated_candle_time = str(candle_time)
                self._save_alerts()
                triggered.append({
                    "alert": alert.to_dict(),
                    "current_price": close_price,
                    "close_price": close_price,
                    "candle": {
                        "pair": candle.get("pair"),
                        "interval": normalized_alert_interval,
                        "expected_open": candle_start.isoformat() if candle_start else str(candle_time),
                        "expected_close": (candle_start + timedelta(seconds=interval_seconds)).isoformat() if candle_start and interval_seconds else None,
                    },
                })
        
        return triggered