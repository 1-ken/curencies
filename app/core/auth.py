"""NextAuth-compatible JWT validation for API and WebSocket access."""
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import AUTH_DISABLED, NEXTAUTH_SECRET

_bearer = HTTPBearer(auto_error=False)


def decode_access_token(token: str) -> str:
    """Validate HS256 API token and return the user id (sub claim)."""
    if not NEXTAUTH_SECRET:
        raise HTTPException(
            status_code=500,
            detail="NEXTAUTH_SECRET is not configured on the observer API",
        )

    try:
        payload = jwt.decode(
            token,
            NEXTAUTH_SECRET,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    return str(sub)


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Require a valid Bearer token unless AUTH_DISABLED is set."""
    if AUTH_DISABLED:
        return "dev-user"

    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    return decode_access_token(credentials.credentials)


def verify_ws_access_token(token: Optional[str]) -> str:
    """Validate WebSocket access_token query parameter."""
    if AUTH_DISABLED:
        return "dev-user"

    if not token:
        raise ValueError("Missing access_token")

    try:
        return decode_access_token(token)
    except HTTPException as exc:
        raise ValueError(exc.detail) from exc
