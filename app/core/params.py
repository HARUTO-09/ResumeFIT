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


@dataclass(frozen=True)
class CoachParams:
    top_k: int = 5
    # Passages less similar to the question than this are not used. Untuned;
    # the right value depends on the embedding model.
    min_similarity: float = 0.25
    # Guidance documents: about 200 to 300 tokens per chunk, with a small overlap.
    chunk_words: int = 180
    chunk_overlap_words: int = 30
    # Resume and JD passages are about one bullet or sentence each, so a question
    # about one fact matches that line instead of a whole section. On the draft
    # eval set (17 Nov 2026) this took hit rate at 5 from 11/20 to 18/20.
    document_chunk_words: int = 25
    document_chunk_overlap_words: int = 5
    # Keep a place for the best resume passage and the best JD passage when they
    # clear the floor, so longer guidance passages cannot crowd out the student's
    # own documents. With the small document chunks this gave 20/20 on the same set.
    reserve_user_sources: bool = True
    question_min_chars: int = 5
    question_max_chars: int = 500
