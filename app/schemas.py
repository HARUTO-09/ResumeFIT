"""Response models (these also drive the OpenAPI docs at /docs)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    # allow field names such as model_version
    model_config = ConfigDict(protected_namespaces=())


class HealthOut(_Model):
    status: str
    model_version: str
    embedding_backend: str


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
