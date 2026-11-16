"""Plain dataclasses for limits and scoring parameters.

The API builds these from environment settings (app/config.py); tests build
them directly. All numbers are defaults from the PRD and are meant to be tuned.
"""

from dataclasses import dataclass

MB = 1024 * 1024


@dataclass(frozen=True)
class DocumentLimits:
    resume_max_bytes: int = 5 * MB
    resume_max_pages: int = 5
    resume_min_chars: int = 200
    jd_max_bytes: int = 5 * MB
    jd_max_pages: int = 10
    jd_min_chars: int = 200
    jd_max_chars: int = 10_000
    # A DOCX is a zip archive: cap what it may expand to (zip-bomb guard).
    docx_max_uncompressed_bytes: int = 50 * MB
    # Share of non-space characters that must be letters or digits.
    min_text_ratio: float = 0.6


@dataclass(frozen=True)
class ScoringParams:
    w_skill: float = 0.5
    w_semantic: float = 0.5
    strong_threshold: int = 70
    partial_threshold: int = 45
    # A resume phrase this similar to a JD skill counts as a synonym match.
    synonym_threshold: float = 0.80
    # Projects / experience similarity below this gets a suggestion.
    weak_section_threshold: float = 0.35
    # Skill overlap below this gets a skills-section suggestion.
    weak_skill_overlap: float = 0.5
    max_requirements: int = 60

    def __post_init__(self) -> None:
        if abs(self.w_skill + self.w_semantic - 1.0) > 1e-6:
            raise ValueError("w_skill + w_semantic must equal 1")
