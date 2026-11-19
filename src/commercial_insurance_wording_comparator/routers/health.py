"""Liveness check."""

from fastapi import APIRouter

from commercial_insurance_wording_comparator.dependencies import RedisClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(r: RedisClient) -> dict[str, str]:
    """The API is up and reaches Redis."""
    await r.ping()
    return {"status": "ok"}
