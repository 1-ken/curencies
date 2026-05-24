"""Admin OTP generation and verification via SMS."""
import os
import secrets
from datetime import datetime, timezone

from app.services.redis_service import RedisService
from app.services.sms_service import SMSService
from app.utils.phone import normalize_phone

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+254707879716").strip()
ADMIN_OTP_TTL_SECONDS = int(os.getenv("ADMIN_OTP_TTL_SECONDS", "300"))
ADMIN_OTP_RATE_LIMIT_SECONDS = int(os.getenv("ADMIN_OTP_RATE_LIMIT_SECONDS", "60"))


class AdminOtpService:
    def __init__(self, redis: RedisService | None, sms: SMSService | None) -> None:
        self._redis = redis
        self._sms = sms

    @staticmethod
    def is_admin_phone(phone: str) -> bool:
        normalized_input = normalize_phone(phone)
        normalized_admin = normalize_phone(ADMIN_PHONE)
        return bool(normalized_input and normalized_admin and normalized_input == normalized_admin)

    async def request_otp(self, phone: str) -> None:
        if not self.is_admin_phone(phone):
            raise ValueError("Invalid credentials")

        if not self._redis or not self._sms:
            raise RuntimeError("OTP service unavailable")

        normalized = normalize_phone(phone)
        rate_key = f"admin:otp:rate:{normalized}"
        otp_key = f"admin:otp:{normalized}"

        client = self._redis.client
        if await client.exists(rate_key):
            raise ValueError("Please wait before requesting another code")

        code = f"{secrets.randbelow(1_000_000):06d}"
        await client.setex(otp_key, ADMIN_OTP_TTL_SECONDS, code)
        await client.setex(rate_key, ADMIN_OTP_RATE_LIMIT_SECONDS, "1")

        sent = self._sms.send_plain_message(
            to_phone=normalized,
            message=f"FX Alert admin login code: {code}. Expires in {ADMIN_OTP_TTL_SECONDS // 60} minutes.",
        )
        if not sent:
            await client.delete(otp_key)
            raise RuntimeError("Failed to send OTP SMS")

    async def verify_otp(self, phone: str, code: str) -> bool:
        if not self.is_admin_phone(phone):
            return False

        if not self._redis:
            return False

        normalized = normalize_phone(phone)
        otp_key = f"admin:otp:{normalized}"
        stored = await self._redis.client.get(otp_key)
        if not stored or stored.strip() != (code or "").strip():
            return False

        await self._redis.client.delete(otp_key)
        return True
