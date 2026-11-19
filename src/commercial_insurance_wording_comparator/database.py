"""Postgres connection: the engine, table creation and one session per request."""

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from commercial_insurance_wording_comparator.config import settings
from commercial_insurance_wording_comparator.models import User

engine = create_engine(settings.database_url, pool_pre_ping=True)


def init_db() -> None:
    """Create the users table if it does not exist yet."""
    SQLModel.metadata.create_all(engine, tables=[User.__table__])


def get_session() -> Iterator[Session]:
    """A database session for one request."""
    with Session(engine) as session:
        yield session
