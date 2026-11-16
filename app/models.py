"""SQL tables. Phase 1 needs only `analyses`; users, feedback and usage arrive in Phase 3."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not keep time zones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_analysis_id() -> str:
    return f"an_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_analysis_id)
    # Filled in Phase 3 when accounts exist; every query will filter on it.
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    jd_text: Mapped[str] = mapped_column(Text)
    jd_source: Mapped[str] = mapped_column(String(8))  # text | pdf | docx
    # NULL unless the user opted in (F7). The uploaded file itself is never kept.
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    score: Mapped[int] = mapped_column(Integer)
    band: Mapped[str] = mapped_column(String(8))
    components: Mapped[dict] = mapped_column(JSON)
    matched_skills: Mapped[list] = mapped_column(JSON)
    missing_skills: Mapped[list] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)

    model_version: Mapped[str] = mapped_column(String(96))
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
