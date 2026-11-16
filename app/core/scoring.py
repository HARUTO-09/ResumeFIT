"""The two-part match score (F5) and the keyword baseline it is compared with.

    score = 100 * (w_skill * S_skill + w_semantic * S_semantic)

S_skill    = weighted share of JD skills found on the resume; each JD skill is
             weighted by how often the JD mentions it.
S_semantic = for each JD requirement sentence, its best cosine similarity to
             any resume chunk; then the mean over requirements.
"""

import re

import numpy as np

from app.core.params import ScoringParams

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the this to was
    were will with you your we our us they their them he she his her i me my can may must should
    would could not no yes if then than so such these those who whom which what when where how why
    all any both each few more most other some own same too very just also about above after again
    against between into through during before under over out up down off further once here there
    etc eg ie per via within without across including include includes using use used work working
    role job candidate candidates ability able strong good excellent knowledge experience
    understanding skills skill required requirements responsibilities preferred plus years year
    """.split()
)


def skill_overlap(jd_counts: dict[str, int], matched: set[str]) -> float | None:
    """Weighted share of JD skills that are matched. None if the JD names no known skill."""
    total = sum(jd_counts.values())
    if total == 0:
        return None
    return sum(n for skill, n in jd_counts.items() if skill in matched) / total


def best_similarities(req_vectors: np.ndarray, chunk_vectors: np.ndarray) -> np.ndarray:
    """For each requirement, the best cosine similarity to any chunk, clipped to [0, 1]."""
    if len(req_vectors) == 0:
        return np.zeros(0, dtype=np.float32)
    if len(chunk_vectors) == 0:
        return np.zeros(len(req_vectors), dtype=np.float32)
    return np.clip((req_vectors @ chunk_vectors.T).max(axis=1), 0.0, 1.0)


def combine(s_skill: float | None, s_semantic: float, params: ScoringParams) -> int:
    """0-100 score. If the JD names no known skill, the semantic part carries the score."""
    if s_skill is None:
        value = s_semantic
    else:
        value = params.w_skill * s_skill + params.w_semantic * s_semantic
    return int(round(100 * min(max(value, 0.0), 1.0)))


def band_for(score: float, params: ScoringParams) -> str:
    if score >= params.strong_threshold:
        return "strong"
    if score >= params.partial_threshold:
        return "partial"
    return "weak"


def keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-z][a-z0-9+#.]*[a-z0-9+#]|[a-z]", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def keyword_baseline(resume_text: str, jd_text: str) -> float:
    """Baseline for evaluation: share of JD keywords that appear in the resume (0-1)."""
    jd_words = keywords(jd_text)
    if not jd_words:
        return 0.0
    return len(jd_words & keywords(resume_text)) / len(jd_words)
