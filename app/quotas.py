"""Daily per-user quotas (PRD F13): analyses and coach messages, counted per UTC day.

A request is checked before any work is done and counted only when it succeeds,
in the same transaction as its result. Two requests racing at the very edge of
the limit can both pass; for a class-scale service that is accepted.
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Usage

KINDS = {
    "analyses": ("analyses_count", "analyses"),
    "coach": ("coach_count", "coach messages"),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def today(now: datetime | None = None) -> str:
    return (now or utc_now()).date().isoformat()


def resets_at(now: datetime | None = None) -> datetime:
    now = now or utc_now()
    return datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=timezone.utc)


def get_usage(session: Session, user_id: str, day: str) -> Usage:
    """Today's usage row, created on first use."""
    row = session.get(Usage, (user_id, day))
    if row is not None:
        return row
    session.add(Usage(user_id=user_id, day=day, analyses_count=0, coach_count=0))
    try:
        session.commit()
    except IntegrityError:  # another request created it first
        session.rollback()
    return session.get(Usage, (user_id, day))


def check_quota(session: Session, user_id: str, kind: str, limit: int) -> str:
    """Raise 429 with the reset time if the user has used today's allowance.

    Returns the UTC day the use will be counted against.
    """
    column, label = KINDS[kind]
    now = utc_now()
    day = today(now)
    used = getattr(get_usage(session, user_id, day), column)
    if used >= limit:
        reset = resets_at(now)
        raise AppError(
            429,
            "quota_exceeded",
            f"You have used all {limit} {label} for today. The limit resets at {reset:%H:%M} UTC.",
            extra={"limit": limit, "used": used, "reset_at": reset.isoformat()},
            headers={"Retry-After": str(max(1, int((reset - now).total_seconds())))},
        )
    return day


def count_use(session: Session, user_id: str, kind: str, day: str) -> None:
    """Add one use. Atomic in SQL; does not commit (the caller commits with its result)."""
    column, _ = KINDS[kind]
    session.execute(
        update(Usage)
        .where(Usage.user_id == user_id, Usage.day == day)
        .values({column: getattr(Usage, column) + 1})
    )


def usage_today(session: Session, user_id: str, analyses_limit: int, coach_limit: int) -> dict:
    now = utc_now()
    row = session.get(Usage, (user_id, today(now)))
    return {
        "day": today(now),
        "analyses_used": row.analyses_count if row else 0,
        "analyses_limit": analyses_limit,
        "coach_used": row.coach_count if row else 0,
        "coach_limit": coach_limit,
        "resets_at": resets_at(now),
    }
