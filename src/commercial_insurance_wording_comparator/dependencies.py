"""Values the endpoints receive through FastAPI's Depends: the database session, Redis and the logged-in user."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlmodel import Session

from commercial_insurance_wording_comparator.database import get_session
from commercial_insurance_wording_comparator.security import decode_token

_bearer = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_redis(request: Request) -> Redis:
    """The app's Redis client, opened at startup."""
    return request.app.state.redis


def _user_id(token: str) -> str:
    """The user id in a token; 401 if the token is bad or expired."""
    try:
        return decode_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc


def current_user(token: Annotated[str, Depends(_bearer)]) -> str:
    """The logged-in user's id, from the `Authorization: Bearer <token>` header."""
    return _user_id(token)


def current_user_from_query(token: Annotated[str, Query()]) -> str:
    """The logged-in user's id, from `?token=`; for Server-Sent Events, because EventSource cannot send headers."""
    return _user_id(token)


DbSession = Annotated[Session, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[str, Depends(current_user)]
StreamUser = Annotated[str, Depends(current_user_from_query)]
