"""
SMS notification service using SMS Gate (api.sms-gate.app).
"""
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

DEFAULT_SMS_GATE_API_URL = "https://api.sms-gate.app/3rdparty/v1/message"


class SMSService:
    """Handles sending alert SMS via SMS Gate HTTP API."""

    def __init__(
        self,
        username: str,
        password: str,
        api_url: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.username = username.strip()
        self.password = password
        self.api_url = (api_url or os.getenv("SMS_GATE_API_URL") or DEFAULT_SMS_GATE_API_URL).strip()
        self.timeout_seconds = timeout_seconds
        logger.info("SMSService initialized for SMS Gate (user=%s)", self.username)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        cleaned = re.sub(r"[^\d+]", "", (phone or "").strip())
        if not cleaned:
            return ""
        if cleaned.startswith("+"):
            return cleaned
        if cleaned.startswith("00"):
            return f"+{cleaned[2:]}"
        return f"+{cleaned}"

    def _build_message(
        self,
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str,
        alert_type: str,
        triggered_at: str,
        timeframe: str,
    ) -> str:
        condition_text = f"{condition} {target_price}".strip()
        trigger_text = triggered_at or "N/A"
        msg_lines = [
            f"{alert_type.upper()} ALERT",
            f"PAIR: {pair}",
            f"CONDITION: {condition_text}",
            f"CURRENT: {current_price}",
            f"TRIGGERED: {trigger_text}",
        ]
        if timeframe:
            msg_lines.append(f"TIME FRAME: {timeframe}")
        if custom_message:
            msg_lines.append(custom_message)
        return " | ".join(msg_lines)

    def send_price_alert(
        self,
        to_phone: str,
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str = "",
        alert_type: str = "price",
        created_at: str = "",
        triggered_at: str = "",
        timeframe: str = "",
    ) -> bool:
        """Send price alert SMS via SMS Gate."""
        destination = self._normalize_phone(to_phone)
        if not destination:
            logger.error("No valid destination phone number for SMS alert")
            return False

        message = self._build_message(
            pair=pair,
            target_price=target_price,
            current_price=current_price,
            condition=condition,
            custom_message=custom_message,
            alert_type=alert_type,
            triggered_at=triggered_at,
            timeframe=timeframe,
        )

        payload = {
            "message": message,
            "phoneNumbers": [destination],
        }

        try:
            logger.debug("Sending SMS via SMS Gate to %s", destination)
            response = requests.post(
                self.api_url,
                auth=(self.username, self.password),
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )

            if 200 <= response.status_code < 300:
                logger.info("SMS sent to %s: %s alert", destination, pair)
                return True

            logger.error(
                "SMS Gate failed for %s (HTTP %s): %s",
                destination,
                response.status_code,
                response.text[:500],
            )
            return False
        except requests.RequestException as exc:
            logger.error("Failed to send SMS to %s via SMS Gate: %s", destination, exc)
            return False
