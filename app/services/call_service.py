"""
Voice call notification service using Twilio.
"""
import logging
import os

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

logger = logging.getLogger(__name__)


class CallService:
    """Handles sending alert calls via Twilio."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.client = Client(account_sid, auth_token)
        self.from_number = from_number
        self.default_to_number = os.getenv("TWILIO_TO_NUMBER", "")
        self.default_message = os.getenv("TWILIO_CUSTOM_MSG", "").strip()
        logger.info("CallService initialized for Twilio voice calls")

    def send_price_alert(
        self,
        to_phone: str,
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str = "",
    ) -> bool:
        """Place a call with a spoken alert message."""
        try:
            destination = to_phone or self.default_to_number
            if not destination:
                logger.error("No destination phone number available for call alert")
                return False

            message = self._build_message(
                pair=pair,
                target_price=target_price,
                current_price=current_price,
                condition=condition,
                custom_message=custom_message,
                default_message=self.default_message,
            )
            response = VoiceResponse()
            response.say(message)

            call = self.client.calls.create(
                to=destination,
                from_=self.from_number,
                twiml=str(response),
            )
            logger.warning("Call initiated to %s (SID: %s)", destination, call.sid)
            return True
        except Exception as e:
            logger.error("Failed to place call to %s: %s", to_phone, e)
            return False

    @staticmethod
    def _build_message(
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str,
        default_message: str,
    ) -> str:
        if custom_message:
            return custom_message
        if default_message:
            return default_message
        return (
            f"Price alert for {pair}. Target {condition} {target_price}. "
            f"Current price is {current_price}."
        )
