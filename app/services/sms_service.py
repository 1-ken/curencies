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
            
            # Defensive response parsing - handle multiple response structures
            if not response:
                logger.error(f"Empty response from SMS API for {to_phone}")
                return False
            
            # Try to get status safely with fallbacks
            if isinstance(response, dict):
                # Check for Africa's Talking success response structure
                sms_data = response.get('SMSMessageData', {})
                recipients = sms_data.get('Recipients', [])
                if recipients and len(recipients) > 0:
                    recipient = recipients[0]
                    if recipient.get('statusCode') == 101:  # 101 = delivered/queued
                        logger.info(f"✓ SMS sent to {to_phone}: {pair} alert")
                        return True
                
                # Fallback: check status fields with safe access
                status = response.get('status')
                status_code = response.get('statusCode') or response.get('status_code')
                if status == "Success" or status_code == 200:
                    logger.info(f"✓ SMS sent to {to_phone}: {pair} alert")
                    return True
                
                logger.warning(f"SMS may have failed for {to_phone}. Status: {status}, Code: {status_code}")
                logger.debug(f"Full response: {response}")
                return False
            else:
                logger.warning(f"Unexpected response type for {to_phone}: {type(response)}")
                return False
        except KeyError as e:
            logger.error(f"Missing key in SMS response for {to_phone}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return False
