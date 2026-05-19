"""Application configuration."""
import os

NEXTAUTH_SECRET = os.getenv("NEXTAUTH_SECRET", "").strip()
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
