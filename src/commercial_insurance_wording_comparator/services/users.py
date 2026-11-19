"""Creating and authenticating users."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from commercial_insurance_wording_comparator.models import User
from commercial_insurance_wording_comparator.security import (
    hash_password,
    verify_password,
)


class EmailTaken(Exception):
    """The email is already registered."""


def create_user(session: Session, email: str, password: str) -> User:
    """Store a new user; raise EmailTaken if the email (in any letter case) is registered."""
    user = User(email=email.lower(), password_hash=hash_password(password))
    session.add(user)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise EmailTaken(email) from exc

    session.refresh(user)
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    """The user with this email and password, or None if either is wrong."""
    user = session.exec(select(User).where(User.email == email.lower())).first()
    valid = verify_password(password, user.password_hash if user else None)

    return user if valid else None
