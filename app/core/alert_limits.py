"""Limits for alert fields (custom messages, etc.)."""
CUSTOM_MESSAGE_MAX_CHARS = 500
CALL_CUSTOM_MESSAGE_MAX_CHARS = 600


def validate_custom_message_for_channel(channel: str, custom_message: str) -> None:
    """Raise ValueError if custom_message exceeds channel limits."""
    if not custom_message:
        return
    if channel == "call" and len(custom_message) > CALL_CUSTOM_MESSAGE_MAX_CHARS:
        raise ValueError(
            f"Custom message for call alerts must be {CALL_CUSTOM_MESSAGE_MAX_CHARS} characters or less "
            f"(about one minute when spoken)."
        )
    if channel != "call" and len(custom_message) > CUSTOM_MESSAGE_MAX_CHARS:
        raise ValueError(
            f"Custom message must be {CUSTOM_MESSAGE_MAX_CHARS} characters or less."
        )


def truncate_call_custom_message(message: str) -> str:
    """Truncate call spoken text to the TTS-safe limit."""
    if not message:
        return message
    if len(message) <= CALL_CUSTOM_MESSAGE_MAX_CHARS:
        return message
    return message[:CALL_CUSTOM_MESSAGE_MAX_CHARS].rstrip()
