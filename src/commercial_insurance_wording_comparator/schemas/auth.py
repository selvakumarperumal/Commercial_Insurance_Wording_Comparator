"""Bodies of the /auth endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    """Body of POST /auth/signup."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """A user as the API shows it, without the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: datetime


class Token(BaseModel):
    """Response of POST /auth/login."""

    access_token: str
    token_type: str = "bearer"
