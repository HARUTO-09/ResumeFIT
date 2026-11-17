"""Accounts (PRD F11) on top of Firebase Authentication.

Firebase does sign-up and sign-in (email and password, or Google) in the UI and
issues an ID token. This router only:
- publishes the public Firebase settings the UI needs (GET /auth/config);
- creates the ResumeFit account for a Firebase user once they consent to the
  privacy note (POST /auth/register);
- shows the account and today's quota use (GET /auth/me);
- deletes the account and all its data (DELETE /auth/me).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import FirebaseClaims
from app.db import delete_user_data
from app.deps import CurrentUser, current_user, firebase_identity, get_session
from app.errors import AppError
from app.models import User, utcnow
from app.quotas import usage_today
from app.schemas import AuthConfigOut, MeOut, RegisterIn, UsageOut, UserOut

router = APIRouter(prefix="/auth", tags=["accounts"])


def _user_out(user: User, email_verified: bool, is_admin: bool, provider: str) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=email_verified,
        is_admin=is_admin,
        sign_in_provider=provider,
        consent_at=user.consent_at,
        created_at=user.created_at,
    )


@router.get("/config", response_model=AuthConfigOut)
def config(request: Request):
    """Public Firebase web settings for the UI. These values are not secrets."""
    s = request.app.state.settings
    return AuthConfigOut(
        project_id=s.firebase_project_id,
        api_key=s.firebase_api_key,
        auth_domain=s.firebase_auth_domain or f"{s.firebase_project_id}.firebaseapp.com",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    request: Request,
    body: RegisterIn,
    response: Response,
    claims: FirebaseClaims = Depends(firebase_identity),
    session: Session = Depends(get_session),
):
    """Create the ResumeFit account for this Firebase user. Needs consent to the privacy note.

    Calling it again for an existing account returns that account (200).
    """
    admins = request.app.state.admin_emails
    is_admin = claims.email_verified and claims.email in admins
    existing = session.scalars(select(User).where(User.firebase_uid == claims.uid)).first()
    if existing is not None:
        response.status_code = 200
        return _user_out(existing, claims.email_verified, is_admin, claims.sign_in_provider)
    if not body.consent:
        raise AppError(
            422,
            "consent_required",
            "Please read the privacy note and agree to it to create your account.",
        )
    now = utcnow()
    user = User(firebase_uid=claims.uid, email=claims.email, consent_at=now, created_at=now)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:  # a parallel request registered the same uid first
        session.rollback()
        user = session.scalars(select(User).where(User.firebase_uid == claims.uid)).one()
        response.status_code = 200
    request.state.log = {"action": "register", "provider": claims.sign_in_provider}
    return _user_out(user, claims.email_verified, is_admin, claims.sign_in_provider)


@router.get("/me", response_model=MeOut)
def me(
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """The signed-in user and today's quota use."""
    settings = request.app.state.settings
    row = session.get(User, user.id)
    return MeOut(
        **_user_out(row, user.email_verified, user.is_admin, user.sign_in_provider).model_dump(),
        usage=UsageOut(
            **usage_today(
                session, user.id, settings.quota_analyses_per_day, settings.quota_coach_per_day
            )
        ),
    )


@router.delete("/me", status_code=204, response_class=Response)
def delete_account(
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Delete the ResumeFit account and all its data.

    Needs a recent sign-in (5 minutes by default), so a token left in an open browser
    cannot be used to wipe someone's data. The Firebase sign-in itself is removed by
    the UI right after this, with the same token.
    """
    limit = request.app.state.settings.recent_login_seconds
    age = (datetime.now(timezone.utc) - user.auth_time).total_seconds()
    if age > limit:
        raise AppError(
            401,
            "recent_login_required",
            f"For safety, sign in again (within the last {limit // 60} minutes) "
            "before deleting your account.",
        )
    removed = delete_user_data(session, user.id)
    session.commit()
    request.state.log = {"action": "account_deleted", "analyses_removed": removed}
    return Response(status_code=204)
