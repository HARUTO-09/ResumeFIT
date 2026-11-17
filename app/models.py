"""SQL tables.

Phase 1: analyses. Phase 2: chunks, guidance_docs, coach_messages.
Phase 3: users, feedback, usage, score_events, request_metrics.

Phase 3 only adds tables, so `create_all` upgrades an existing database in place.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not keep time zones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_analysis_id() -> str:
    return f"an_{uuid.uuid4().hex[:12]}"


def new_message_id() -> str:
    return f"cm_{uuid.uuid4().hex[:12]}"


def new_user_id() -> str:
    return f"us_{uuid.uuid4().hex[:12]}"


def new_feedback_id() -> str:
    return f"fb_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_analysis_id)
    # Owner. Every read, list and delete filters on it (PRD F12). Analyses made
    # before Phase 3 have NULL here and are visible to nobody.
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


class User(Base):
    """A ResumeFit account, linked to a Firebase Authentication user.

    Firebase holds the sign-in details (password or Google identity); this row holds
    only the link, the email for display and admin checks, and the consent time.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_user_id)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(254))  # lower-case, kept in step with Firebase
    # When the user agreed to the privacy note. Registration fails without it.
    consent_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Feedback(Base):
    """A 1-5 rating, optionally with a comment, on an analysis or a coach answer (F14).

    When the analysis is deleted the link and the comment are removed but the
    rating, its model version and its date stay, so the admin trend survives.
    Deleting the account deletes the user's feedback entirely.
    """

    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_feedback_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # analysis | coach_message
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    analysis_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)  # redacted
    model_version: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Usage(Base):
    """One row per user per UTC day; powers the daily quotas (F13)."""

    __tablename__ = "usage"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD, UTC
    analyses_count: Mapped[int] = mapped_column(Integer, default=0)
    coach_count: Mapped[int] = mapped_column(Integer, default=0)


class ScoreEvent(Base):
    """Anonymous record of each score, for the weekly drift check.

    No user, analysis, resume or JD link, so it is kept after analyses expire;
    the drift baseline is the first week of these rows.
    """

    __tablename__ = "score_events"
    __table_args__ = (Index("ix_score_events_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    score: Mapped[int] = mapped_column(Integer)
    band: Mapped[str] = mapped_column(String(8))
    sections_missing: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(96))


class RequestMetric(Base):
    """One row per API request: route, status and latency. No user or content."""

    __tablename__ = "request_metrics"
    __table_args__ = (Index("ix_request_metrics_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(80))  # route template, e.g. /analyses/{analysis_id}
    status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quota_hit: Mapped[bool] = mapped_column(Boolean, default=False)
