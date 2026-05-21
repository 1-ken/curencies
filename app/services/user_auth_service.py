"""Username/password registration and authentication."""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select

from app.core.passwords import hash_password, verify_password
from app.models.user import User
from app.services.postgres_service import PostgresService

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")


class UserAuthService:
    def __init__(self, postgres: PostgresService) -> None:
        self._postgres = postgres

    @staticmethod
    def validate_username(username: str) -> str:
        normalized = (username or "").strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Username must be 3-32 characters and contain only letters, numbers, underscores, or dots"
            )
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters")

    async def username_exists(self, username: str) -> bool:
        normalized = self.validate_username(username)
        row = await self._get_user_by_username(normalized)
        return row is not None

    async def register(self, username: str, password: str) -> Tuple[str, str]:
        normalized_username = self.validate_username(username)
        self.validate_password(password)

        if await self.username_exists(normalized_username):
            raise ValueError("Username already taken")

        user_id = str(uuid.uuid4())
        user = User(
            user_id=user_id,
            username=normalized_username,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc),
        )

        sessionmaker = self._postgres._sessionmaker
        if not sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        async with sessionmaker() as session:
            session.add(user)
            await session.commit()

        await self._postgres.get_or_create_user_state(user_id)
        return user_id, normalized_username

    async def authenticate(self, username: str, password: str) -> Tuple[str, str]:
        normalized_username = self.validate_username(username)
        user = await self._get_user_by_username(normalized_username)
        if user is None or not verify_password(password, user.password_hash):
            raise ValueError("Invalid username or password")
        return user.user_id, user.username

    async def _get_user_by_username(self, username: str) -> Optional[User]:
        sessionmaker = self._postgres._sessionmaker
        if not sessionmaker:
            raise RuntimeError("PostgreSQL session not initialized")

        async with sessionmaker() as session:
            stmt = select(User).where(User.username == username)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
