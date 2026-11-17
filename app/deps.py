"""Request dependencies shared by all routers: database session, signed-in user, admin check.

Every protected request carries `Authorization: Bearer <Firebase ID token>`. The token
is verified against Google's keys for this Firebase project (app/core/security.py),
then mapped to the ResumeFit account registered for that Firebase uid.
"""

from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import FirebaseClaims, KeysUnavailable, TokenError
from app.errors import AppError
from app.models import User

_BEARER = {"WWW-Authenticate": "Bearer"}


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    email_verified: bool
    is_admin: bool
    auth_time: datetime
    sign_in_provider: str


def firebase_identity(request: Request) -> FirebaseClaims:
    """A verified Firebase identity. It may not have a ResumeFit account yet."""
    verifier = request.app.state.verifier
    if verifier is None:
        raise AppError(
            503,
            "auth_not_configured",
            "Sign-in is not configured on this server (RESUMEFIT_FIREBASE_PROJECT_ID is not set).",
        )
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, "not_authenticated", "Sign in to use this endpoint.", headers=_BEARER)
    try:
        return verifier.verify(token.strip())
    except KeysUnavailable:
        raise AppError(
            503, "auth_unavailable", "Sign-in cannot be checked right now. Please try again."
        ) from None
    except TokenError:
        raise AppError(
            401,
            "invalid_token",
            "Your session is invalid or has expired. Please sign in again.",
            headers=_BEARER,
        ) from None


def current_user(
    request: Request,
    claims: FirebaseClaims = Depends(firebase_identity),
    session: Session = Depends(get_session),
) -> CurrentUser:
    """The signed-in user with a ResumeFit account. 403 if they have not registered yet."""
    user = session.scalars(select(User).where(User.firebase_uid == claims.uid)).first()
    if user is None:
        raise AppError(
            403,
            "registration_required",
            "Please read the privacy note and agree to it to finish creating your account.",
        )
    if user.email != claims.email:  # the email was changed in Firebase
        user.email = claims.email
        session.commit()
    return CurrentUser(
        id=user.id,
        email=user.email,
        email_verified=claims.email_verified,
        # An unverified email could belong to anyone, so it never grants admin.
        is_admin=claims.email_verified and claims.email in request.app.state.admin_emails,
        auth_time=claims.auth_time,
        sign_in_provider=claims.sign_in_provider,
    )


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise AppError(403, "forbidden", "This page is for administrators only.")
    return user
