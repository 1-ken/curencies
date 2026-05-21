"""Alert delivery channel constants."""
VALID_ALERT_CHANNELS = ("email", "sms", "call", "sound")


def validate_alert_channel(channel: str) -> None:
    if channel not in VALID_ALERT_CHANNELS:
        raise ValueError(
            f"Channel must be one of: {', '.join(VALID_ALERT_CHANNELS)}"
        )


def channel_requires_email(channel: str) -> bool:
    return channel == "email"


def channel_requires_phone(channel: str) -> bool:
    return channel in ("sms", "call")
