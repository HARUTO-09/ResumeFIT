"""End-to-end matcher: resume text + JD text -> score, skills and gap report.

No LLM call and no I/O happens here, which keeps the matcher fast and testable.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from app import __version__
from app.core import scoring
from app.core.embeddings import Embedder, EmbeddingCache
from app.core.params import ScoringParams
from app.core.redaction import redact
from app.core.sections import missing_sections, split_sections, split_units
from app.core.skills import (
    SkillsDB,
    candidate_phrases,
    count_skills,
    resume_skills,
    synonym_matches,
)

SCORED_SECTIONS = ("projects", "experience")


def model_version(embedder: Embedder) -> str:
    return f"matcher-{__version__}+{embedder.name}"


@dataclass
class MatchResult:
    score: int
    band: str
    components: dict
    matched_skills: list[str]
    missing_skills: list[dict]
    suggestions: list[dict]
    sections_found: list[str]
    sections_missing: list[str]
    semantic_matches: list[dict]
    notes: list[str] = field(default_factory=list)
    model_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def analyze_texts(
    resume_text: str,
    jd_text: str,
    embedder: Embedder,
    skills_db: SkillsDB,
    params: ScoringParams | None = None,
    cache: EmbeddingCache | None = None,
) -> MatchResult:
    params = params or ScoringParams()
    notes: list[str] = []

    # ---- resume: sections, then drop identity before anything is scored ----
    sections = split_sections(resume_text)
    header = sections.pop("header", "")
    absent = missing_sections(sections)
    # Name, contact details and location live in the header; they are never
    # part of the scoring input (PRD: fairness / counterfactual name test).
    body = {name: redact(text, header).text for name, text in sections.items() if text}
    if not body:
        # No headings recognised: score the whole document rather than fail.
        body = {"other": redact(resume_text, header).text}
        notes.append("No section headings were recognised, so the resume was scored as one block.")
    resume_body = "\n".join(body.values())

    chunks: list[str] = []
    chunk_section: list[str] = []
    for name, text in body.items():
        for unit in split_units(text):
            chunks.append(unit)
            chunk_section.append(name)

    # ---- skills --------------------------------------------------------------
    jd_counts = count_skills(jd_text, skills_db)
    have = resume_skills(resume_body, skills_db)
    matched = {s for s in jd_counts if s in have}
    unmatched = [s for s in jd_counts if s not in matched]
    semantic = synonym_matches(
        unmatched,
        candidate_phrases(body.get("skills", "")),
        embedder,
        params.synonym_threshold,
    )
    matched |= {m["skill"] for m in semantic}

    s_skill = scoring.skill_overlap(jd_counts, matched)
    if s_skill is None:
        notes.append(
            "The job description names no skill from the curated list, "
            "so the score uses semantic similarity only."
        )

    # ---- semantic similarity ---------------------------------------------------
    requirements = split_units(jd_text, min_words=4)[: params.max_requirements]
    if not requirements:
        requirements = [jd_text]
    req_vec = cache.encode(embedder, requirements) if cache else embedder.encode(requirements)
    chunk_vec = embedder.encode(chunks)
    best = scoring.best_similarities(req_vec, chunk_vec)
    s_semantic = float(best.mean()) if len(best) else 0.0

    components: dict = {
        "skill_overlap": None if s_skill is None else round(s_skill, 3),
        "semantic_similarity": round(s_semantic, 3),
    }
    section_arr = np.array(chunk_section)
    section_best: dict[str, np.ndarray] = {}
    for name in SCORED_SECTIONS:
        if name in body:
            section_best[name] = scoring.best_similarities(req_vec, chunk_vec[section_arr == name])
            components[f"{name}_similarity"] = round(float(section_best[name].mean()), 3)

    score = scoring.combine(s_skill, s_semantic, params)

    # ---- gap report (F6) --------------------------------------------------------
    missing = sorted(
        ({"skill": s, "jd_mentions": n} for s, n in jd_counts.items() if s not in matched),
        key=lambda item: (-item["jd_mentions"], item["skill"]),
    )
    top_missing = ", ".join(m["skill"] for m in missing[:5])
    suggestions: list[dict] = []

    if "skills" in absent:
        suggestions.append(
            {
                "section": "skills",
                "text": "No skills section was found. Add one with a clear heading such as "
                '"Skills" so screening tools can read it.'
                + (f" Skills this JD asks for: {top_missing}." if top_missing else ""),
            }
        )
    elif s_skill is not None and s_skill < params.weak_skill_overlap and top_missing:
        suggestions.append(
            {
                "section": "skills",
                "text": f"The JD stresses skills your resume does not show: {top_missing}. "
                "List the ones you really have, and back each with a project or experience line.",
            }
        )

    for name in SCORED_SECTIONS:
        if name in absent:
            suggestions.append(
                {
                    "section": name,
                    "text": f"No {name} section was found. If you have relevant {name}, "
                    f'add it under a clear "{name.title()}" heading.',
                }
            )
        elif components[f"{name}_similarity"] < params.weak_section_threshold:
            weakest = requirements[int(np.argmin(section_best[name]))]
            suggestions.append(
                {
                    "section": name,
                    "text": f"Your {name} section says little about this JD requirement: "
                    f'"{_snippet(weakest)}" If you have done related work, add or reword '
                    "a bullet to show it, with the tool used and the result.",
                }
            )

    if "education" in absent:
        suggestions.append(
            {
                "section": "education",
                "text": "No education section was found. Add your degree, institution and year.",
            }
        )

    return MatchResult(
        score=score,
        band=scoring.band_for(score, params),
        components=components,
        matched_skills=sorted(matched),
        missing_skills=missing,
        suggestions=suggestions,
        sections_found=[n for n in ("skills", "projects", "experience", "education") if n in body],
        sections_missing=absent,
        semantic_matches=semantic,
        notes=notes,
        model_version=model_version(embedder),
    )
