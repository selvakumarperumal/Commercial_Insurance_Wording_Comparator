"""Password hashing (Argon2) and login tokens (JWT, HS256)."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from commercial_insurance_wording_comparator.config import settings

JWT_ALGORITHM = "HS256"
MIN_SECRET_CHARS = 32

_password_hash = PasswordHash.recommended()
_DUMMY_HASH = _password_hash.hash("dummy password")


def check_secret() -> None:
    """Refuse to start without a strong JWT_SECRET."""
    if len(settings.jwt_secret) < MIN_SECRET_CHARS:
        raise RuntimeError(f"set JWT_SECRET to a random string of at least {MIN_SECRET_CHARS} characters")


def hash_password(password: str) -> str:
    """The Argon2 hash stored for a password."""
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Whether `password` matches `hashed`.

    With no hash (unknown user) a dummy hash is still checked, so the time taken does not reveal which
    emails are registered.
    """
    valid = _password_hash.verify(password, hashed or _DUMMY_HASH)
    return valid and hashed is not None


def create_token(user_id: str) -> str:
    """A signed token for the user that expires after JWT_EXPIRE_MINUTES."""
    expires = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": user_id, "exp": expires}, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> str:
    """The user id in a token; raises jwt.InvalidTokenError if it is forged, malformed or expired."""
    claims = jwt.decode(
        token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]},
    )
    return claims["sub"]
