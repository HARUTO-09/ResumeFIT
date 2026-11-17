"""Response models (these also drive the OpenAPI docs at /docs)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    # allow field names such as model_version
    model_config = ConfigDict(protected_namespaces=())


class HealthOut(_Model):
    status: str
    model_version: str
    embedding_backend: str
    coach_model_version: str
    guidance_docs: int


class MissingSkill(_Model):
    skill: str
    jd_mentions: int


class Suggestion(_Model):
    section: str
    text: str


class SemanticMatch(_Model):
    skill: str
    resume_phrase: str
    similarity: float


class AnalysisOut(_Model):
    id: str
    score: int
    band: str
    components: dict[str, float | None]
    matched_skills: list[str]
    missing_skills: list[MissingSkill]
    suggestions: list[Suggestion]
    sections_found: list[str]
    sections_missing: list[str]
    semantic_matches: list[SemanticMatch]
    notes: list[str]
    jd_source: str
    resume_text_stored: bool
    model_version: str
    latency_ms: int
    created_at: datetime


class AnalysisSummary(_Model):
    id: str
    score: int
    band: str
    jd_source: str
    jd_preview: str
    model_version: str
    created_at: datetime


class JDExtractOut(_Model):
    text: str
    source: str
    char_count: int
    warning: str | None = None


class CoachIn(_Model):
    analysis_id: str
    question: str


class Citation(_Model):
    id: str
    source: str
    label: str
    text: str


class CoachOut(_Model):
    id: str
    analysis_id: str
    # answered | retrieval_only | not_in_sources | declined
    status: str
    answer: str
    citations: list[Citation]
    reason: str | None = None
    model_version: str
    latency_ms: int


# ---- accounts (Phase 3) -------------------------------------------------------------
class AuthConfigOut(_Model):
    project_id: str
    api_key: str
    auth_domain: str


class RegisterIn(_Model):
    consent: bool = Field(
        description="The user has read the privacy note and agrees to their data being "
        "processed as it describes. Registration fails without it."
    )


class UserOut(_Model):
    id: str
    email: str
    email_verified: bool
    is_admin: bool
    sign_in_provider: str
    consent_at: datetime
    created_at: datetime


class UsageOut(_Model):
    day: str
    analyses_used: int
    analyses_limit: int
    coach_used: int
    coach_limit: int
    resets_at: datetime


class MeOut(UserOut):
    usage: UsageOut


# ---- feedback (Phase 3) -------------------------------------------------------------
class FeedbackIn(_Model):
    target_type: Literal["analysis", "coach_message"]
    target_id: str = Field(max_length=32)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(_Model):
    id: str
    target_type: str
    target_id: str
    rating: int
    comment: str | None
    model_version: str
    created_at: datetime
    updated_at: datetime


# ---- admin (Phase 3) ----------------------------------------------------------------
class AdminMetricsOut(_Model):
    generated_at: datetime
    window: dict[str, Any]
    requests: dict[str, Any]
    quota_hits: dict[str, Any]
    usage: dict[str, Any]
    scores: dict[str, Any]
    ratings: dict[str, Any]
    drift: dict[str, Any]
    flags: list[str]
