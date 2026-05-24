"""Admin JWT verification for metrics endpoints."""
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET") or os.getenv("NEXTAUTH_SECRET") or "change-admin-secret"
ADMIN_JWT_ALGORITHM = "HS256"
ADMIN_TOKEN_EXPIRE_MINUTES = int(os.getenv("ADMIN_TOKEN_EXPIRE_MINUTES", "480"))

admin_bearer = HTTPBearer(auto_error=False)


def create_admin_token() -> str:
    payload = {
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ADMIN_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ADMIN_JWT_ALGORITHM)


def verify_admin_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid admin token") from exc

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


async def get_admin_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer),
) -> Dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return verify_admin_token(credentials.credentials)
