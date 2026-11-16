"""Database engine, sessions and the retention job."""

from datetime import timedelta

from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Analysis, Base, utcnow


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(engine: Engine) -> sessionmaker[Session]:
    # Phase 1 creates tables directly. Move to Alembic migrations before the
    # schema changes in Phase 3 / PostgreSQL.
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def purge_expired(session: Session, retention_days: int) -> int:
    """Delete analyses older than the retention period. Returns rows removed."""
    cutoff = utcnow() - timedelta(days=retention_days)
    result = session.execute(delete(Analysis).where(Analysis.created_at < cutoff))
    session.commit()
    return result.rowcount or 0
