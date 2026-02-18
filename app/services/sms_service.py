"""
SMS notification service using Africa's Talking.
"""
import logging
import os
from typing import List

import africastalking

logger = logging.getLogger(__name__)


class SMSService:
    """Handles sending alert SMS via Africa's Talking."""

    def __init__(self, username: str, api_key: str):
        africastalking.initialize(username, api_key)
        self.sms = africastalking.SMS
        self.username = username
        # Optional: Sender ID if configured in Africa's Talking
        self.sender_id = os.getenv("AFRICASTALKING_SENDER_ID", "")
        logger.info(f"SMSService initialized for username: {username}")

    def send_price_alert(
        self,
        to_phone: str,
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str = "",
    ) -> bool:
        """Send price alert SMS."""
        try:
            msg_lines = [
                f"ALERT: {pair} {condition} {target_price}",
                f"Current: {current_price}",
            ]
            if custom_message:
                msg_lines.append(custom_message)
            msg = " | ".join(msg_lines)

            params = {}
            if self.sender_id:
                params["from_"] = self.sender_id

            logger.debug(f"Sending SMS to {to_phone}: {msg}")
            response = self.sms.send(msg, [to_phone], **params)
            
            # Check response status
            if response["status"] == "error" or response["statusCode"] != 200:
                logger.error(f"SMS API error for {to_phone}: {response}")
                return False
            
            logger.warning(f"✓ SMS sent to {to_phone}: {pair} alert")
            return True
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return False
