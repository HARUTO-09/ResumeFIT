"""Database engine, sessions and the retention job."""

from datetime import timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Analysis, Base, Chunk, CoachMessage, utcnow


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(engine: Engine) -> sessionmaker[Session]:
    # Phase 1 creates tables directly. Move to Alembic migrations before the
    # schema changes in Phase 3 / PostgreSQL.
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def delete_analysis_data(session: Session, analysis_ids: list[str]) -> None:
    """Delete analyses with their coach messages and vector chunks.

    Does not commit: the caller commits, so everything goes in one transaction.
    """
    if not analysis_ids:
        return
    session.execute(delete(Chunk).where(Chunk.analysis_id.in_(analysis_ids)))
    session.execute(delete(CoachMessage).where(CoachMessage.analysis_id.in_(analysis_ids)))
    session.execute(delete(Analysis).where(Analysis.id.in_(analysis_ids)))


def purge_expired(session: Session, retention_days: int) -> int:
    """Delete analyses older than the retention period. Returns analyses removed."""
    cutoff = utcnow() - timedelta(days=retention_days)
    expired = list(session.scalars(select(Analysis.id).where(Analysis.created_at < cutoff)))
    delete_analysis_data(session, expired)
    session.commit()
    return len(expired)
