"""Sign up, log in and the current user.

    POST /auth/signup   {"email", "password"} -> the new user
    POST /auth/login    form fields username (the email) and password -> {"access_token", "token_type"}
    GET  /auth/me       the logged-in user
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from commercial_insurance_wording_comparator.dependencies import CurrentUser, DbSession
from commercial_insurance_wording_comparator.models import User
from commercial_insurance_wording_comparator.schemas.auth import (
    SignupRequest,
    Token,
    UserOut,
)
from commercial_insurance_wording_comparator.security import create_token
from commercial_insurance_wording_comparator.services.users import (
    EmailTaken,
    authenticate,
    create_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=201)
def signup(body: SignupRequest, session: DbSession) -> UserOut:
    """Create an account; 409 if the email is already registered."""
    try:
        user = create_user(session, body.email, body.password)
    except EmailTaken as exc:
        raise HTTPException(409, "email already registered") from exc

    return UserOut.model_validate(user)


@router.post("/login")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession) -> Token:
    """Exchange email and password for a token; 401 if either is wrong."""
    user = authenticate(session, form.username, form.password)
    if user is None:
        raise HTTPException(401, "wrong email or password", headers={"WWW-Authenticate": "Bearer"})

    return Token(access_token=create_token(user.id))


@router.get("/me")
def me(user_id: CurrentUser, session: DbSession) -> UserOut:
    """The logged-in user."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")

    return UserOut.model_validate(user)
