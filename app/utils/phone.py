"""Phone number normalization for alerts."""
import re


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", (phone or "").strip())
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    return f"+{cleaned}"
