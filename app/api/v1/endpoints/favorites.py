"""User favorite pairs endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import get_current_user_id
from app.services.activity_log_service import log_activity
from app.services.postgres_service import PostgresService

router = APIRouter(prefix="/me/favorites", tags=["favorites"])

postgres_service: PostgresService | None = None


def set_postgres_service(service: PostgresService | None) -> None:
    global postgres_service
    postgres_service = service


class FavoritePairRequest(BaseModel):
    pair: str = Field(..., min_length=1, max_length=64)


class FavoritesResponse(BaseModel):
    pairs: list[str]


@router.get("", response_model=FavoritesResponse)
async def list_favorites(user_id: str = Depends(get_current_user_id)):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    pairs = await postgres_service.list_user_favorites(user_id)
    return FavoritesResponse(pairs=pairs)


@router.post("", response_model=FavoritesResponse)
async def add_favorite(
    request: FavoritePairRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    await postgres_service.add_user_favorite(user_id, request.pair)
    await log_activity(
        "favorite_add",
        user_id=user_id,
        request=http_request,
        metadata={"pair": request.pair},
    )
    pairs = await postgres_service.list_user_favorites(user_id)
    return FavoritesResponse(pairs=pairs)


@router.delete("/{pair}", response_model=FavoritesResponse)
async def remove_favorite(
    pair: str,
    http_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    if not postgres_service:
        raise HTTPException(status_code=503, detail="Database unavailable")
    await postgres_service.remove_user_favorite(user_id, pair)
    await log_activity(
        "favorite_remove",
        user_id=user_id,
        request=http_request,
        metadata={"pair": pair},
    )
    pairs = await postgres_service.list_user_favorites(user_id)
    return FavoritesResponse(pairs=pairs)
