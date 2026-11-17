"""SQL tables. Phase 1: analyses. Phase 2: chunks, guidance_docs, coach_messages.

Users, feedback and usage arrive in Phase 3.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not keep time zones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_analysis_id() -> str:
    return f"an_{uuid.uuid4().hex[:12]}"


def new_message_id() -> str:
    return f"cm_{uuid.uuid4().hex[:12]}"


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


class GuidanceDoc(Base):
    """Provenance for every document in the coach's guidance corpus."""

    __tablename__ = "guidance_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(300))
    version: Mapped[str] = mapped_column(String(32))
    chunk_count: Mapped[int] = mapped_column(Integer)
    # Hash of the whole corpus + embedder + chunk settings at ingestion time.
    fingerprint: Mapped[str] = mapped_column(String(32))


class Chunk(Base):
    """The vector store: one passage and its embedding.

    Guidance chunks have doc_id set; resume and JD chunks have analysis_id set
    and are deleted with that analysis. Resume chunks hold redacted text only.
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(8))  # resume | jd | guidance
    analysis_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(200))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)  # float32 vector
    embedder: Mapped[str] = mapped_column(String(64))


class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_message_id)
    analysis_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    cited_passage_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
