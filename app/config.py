"""Settings read from environment variables (prefix RESUMEFIT_) or a .env file.

Every limit and threshold in the PRD is a default here, so it can be changed
without touching code. See .env.example.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.params import MB, CoachParams, DocumentLimits, MonitoringParams, ScoringParams


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESUMEFIT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./resumefit.db"

    # "sentence-transformers" (real model) or "hashing" (no download; tests and CI)
    embedding_backend: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    resume_max_mb: int = 5
    resume_max_pages: int = 5
    jd_max_mb: int = 5
    jd_max_pages: int = 10
    jd_min_chars: int = 200
    jd_max_chars: int = 10_000

    w_skill: float = 0.5
    w_semantic: float = 0.5
    strong_threshold: int = 70
    partial_threshold: int = 45
    synonym_threshold: float = 0.80
    weak_section_threshold: float = 0.35

    # Coach (Phase 2). "none" = retrieval-only: passages are shown, no text is generated.
    # "openai-compatible" = any server that offers the chat-completions HTTP format.
    llm_provider: str = "none"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: float = 8.0
    coach_top_k: int = 5
    coach_min_similarity: float = 0.25

    # Accounts (Phase 3): sign-in is done by Firebase Authentication; the API only
    # verifies Firebase ID tokens. The web API key and auth domain are public values
    # that the UI needs; the API hands them out at /auth/config.
    firebase_project_id: str = ""
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    # Google's public keys for Firebase tokens. Only tests point this elsewhere.
    firebase_jwks_url: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    # Deleting the account needs a sign-in at most this many seconds old.
    recent_login_seconds: int = 300
    # Comma-separated emails that may open /admin/metrics (the email must be verified).
    admin_emails: str = ""

    # Daily quotas per user (PRD F13). Days are UTC.
    quota_analyses_per_day: int = 20
    quota_coach_per_day: int = 50

    # Monitoring (PRD section 11): starting thresholds.
    metrics_window_days: int = 7
    drift_mean_shift: float = 10.0
    drift_ks_alpha: float = 0.01
    drift_min_samples: int = 20
    rating_flag_below: float = 3.5

    # Browser origins allowed to call the API (the web front end), comma-separated,
    # e.g. "http://localhost:5500,https://resumefit.vercel.app". Empty = no CORS.
    cors_origins: str = ""

    retention_days: int = 30
    log_level: str = "INFO"

    def limits(self) -> DocumentLimits:
        return DocumentLimits(
            resume_max_bytes=self.resume_max_mb * MB,
            resume_max_pages=self.resume_max_pages,
            jd_max_bytes=self.jd_max_mb * MB,
            jd_max_pages=self.jd_max_pages,
            jd_min_chars=self.jd_min_chars,
            jd_max_chars=self.jd_max_chars,
        )

    def scoring(self) -> ScoringParams:
        return ScoringParams(
            w_skill=self.w_skill,
            w_semantic=self.w_semantic,
            strong_threshold=self.strong_threshold,
            partial_threshold=self.partial_threshold,
            synonym_threshold=self.synonym_threshold,
            weak_section_threshold=self.weak_section_threshold,
        )

    def coach(self) -> CoachParams:
        return CoachParams(top_k=self.coach_top_k, min_similarity=self.coach_min_similarity)

    def monitoring(self) -> MonitoringParams:
        return MonitoringParams(
            window_days=self.metrics_window_days,
            drift_mean_shift=self.drift_mean_shift,
            drift_ks_alpha=self.drift_ks_alpha,
            drift_min_samples=self.drift_min_samples,
            rating_flag_below=self.rating_flag_below,
        )

    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    def admin_email_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.admin_emails.split(",") if e.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
