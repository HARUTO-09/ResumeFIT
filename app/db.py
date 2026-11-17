"""Database engine, sessions, deletion and the retention job."""

from datetime import timedelta

from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Analysis,
    Base,
    Chunk,
    CoachMessage,
    Feedback,
    RequestMetric,
    Usage,
    User,
    utcnow,
)


def normalise_database_url(database_url: str) -> str:
    """Use the psycopg 3 driver for PostgreSQL URLs as hosts hand them out.

    Neon and most hosts give `postgresql://...` or `postgres://...`; SQLAlchemy would
    pick psycopg2 for the first and does not know the second.
    """
    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix) :]
    return database_url


def make_engine(database_url: str) -> Engine:
    database_url = normalise_database_url(database_url)
    if database_url.startswith("sqlite"):
        return create_engine(database_url, connect_args={"check_same_thread": False})
    # Serverless Postgres (Neon) suspends when idle and drops open connections:
    # check each pooled connection before use and recycle old ones. Server-side
    # prepared statements are off because Neon's "-pooler" endpoint is PgBouncer.
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        connect_args={"prepare_threshold": None},
    )


def _replace_password_users_table(engine: Engine) -> None:
    """The first Phase 3 draft stored password hashes in `users`; Firebase replaced it.

    An empty table of that shape is dropped so the new one can be created. A non-empty
    one is left alone and startup stops, so no account is lost silently.
    """
    if "users" not in inspect(engine).get_table_names():
        return
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    if "firebase_uid" in columns:
        return
    with engine.begin() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM users")).scalar():
            raise RuntimeError(
                "The database has a 'users' table from the password-based draft of Phase 3 "
                "with accounts in it. Sign-in now uses Firebase; delete those rows "
                "(DELETE FROM users) and restart."
            )
        conn.execute(text("DROP TABLE users"))


def init_db(engine: Engine) -> sessionmaker[Session]:
    # Tables are created directly, on SQLite and on PostgreSQL alike. Phases 2 and 3
    # only added tables, so this also upgrades an older database. Move to Alembic
    # migrations before the next change to an existing table.
    _replace_password_users_table(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def delete_analysis_data(session: Session, analysis_ids: list[str]) -> None:
    """Delete analyses with their coach messages and vector chunks, and unlink their feedback.

    Feedback keeps its rating, model version and date for the admin trend, but loses
    the link to the deleted analysis or message and its free-text comment.
    Does not commit: the caller commits, so everything goes in one transaction.
    """
    if not analysis_ids:
        return
    session.execute(
        update(Feedback)
        .where(Feedback.analysis_id.in_(analysis_ids))
        .values(analysis_id=None, target_id=None, comment=None)
    )
    session.execute(delete(Chunk).where(Chunk.analysis_id.in_(analysis_ids)))
    session.execute(delete(CoachMessage).where(CoachMessage.analysis_id.in_(analysis_ids)))
    session.execute(delete(Analysis).where(Analysis.id.in_(analysis_ids)))


def delete_user_data(session: Session, user_id: str) -> int:
    """Delete an account and everything linked to it. Returns analyses removed.

    Anonymous score events and request metrics carry no user link and stay.
    Does not commit.
    """
    analysis_ids = list(session.scalars(select(Analysis.id).where(Analysis.user_id == user_id)))
    delete_analysis_data(session, analysis_ids)
    session.execute(delete(Feedback).where(Feedback.user_id == user_id))
    session.execute(delete(Usage).where(Usage.user_id == user_id))
    session.execute(delete(CoachMessage).where(CoachMessage.user_id == user_id))
    session.execute(delete(User).where(User.id == user_id))
    return len(analysis_ids)


def purge_expired(session: Session, retention_days: int) -> int:
    """Delete analyses older than the retention period. Returns analyses removed.

    Request metrics and usage rows older than the period go too.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    expired = list(session.scalars(select(Analysis.id).where(Analysis.created_at < cutoff)))
    delete_analysis_data(session, expired)
    session.execute(delete(RequestMetric).where(RequestMetric.created_at < cutoff))
    session.execute(delete(Usage).where(Usage.day < cutoff.date().isoformat()))
    session.commit()
    return len(expired)
