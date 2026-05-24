"""Authentication request/response schemas."""
from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class AuthUserResponse(BaseModel):
    user_id: str
    username: str


class GoogleSyncRequest(BaseModel):
    google_sub: str = Field(..., min_length=1, max_length=128)
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
