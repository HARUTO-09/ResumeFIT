"""Skill extraction from a curated list, plus embedding match for synonyms (F4)."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.embeddings import Embedder

SKILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "skills.json"

# A skill may not touch these characters, so "java" does not match inside
# "javascript", "c" does not match "c++" or "c#", and "r" does not match "R&D".
_BOUNDARY = r"A-Za-z0-9+#&"


@dataclass(frozen=True)
class SkillsDB:
    patterns: dict[str, tuple[re.Pattern, ...]]  # canonical -> compiled alias patterns
    implies: dict[str, tuple[str, ...]]

    @property
    def names(self) -> list[str]:
        return list(self.patterns)


def _compile(alias: str) -> re.Pattern:
    case_sensitive = alias.startswith("cs:")
    body = alias[3:] if case_sensitive else alias
    escaped = r"\s+".join(re.escape(part) for part in body.split())
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(rf"(?<![{_BOUNDARY}]){escaped}(?![{_BOUNDARY}])", flags)


def build_skills_db(raw: dict) -> SkillsDB:
    patterns = {}
    for canonical, aliases in raw["skills"].items():
        names = list(aliases)
        # the canonical name matches too, unless a case-sensitive alias replaces it
        if not any(a.startswith("cs:") and a[3:].lower() == canonical for a in aliases):
            names.insert(0, canonical)
        patterns[canonical] = tuple(_compile(a) for a in names)
    implies = {k: tuple(v) for k, v in raw.get("implies", {}).items()}
    return SkillsDB(patterns=patterns, implies=implies)


@lru_cache(maxsize=1)
def load_skills() -> SkillsDB:
    return build_skills_db(json.loads(SKILLS_PATH.read_text(encoding="utf-8")))


def _prepare(text: str) -> str:
    return re.sub(r"[‐‑‒–—]", "-", text)


def count_skills(text: str, db: SkillsDB) -> dict[str, int]:
    """Canonical skill -> number of mentions in the text (aliases included)."""
    text = _prepare(text)
    counts: dict[str, int] = {}
    for canonical, patterns in db.patterns.items():
        spans: set[tuple[int, int]] = set()
        for pattern in patterns:
            spans.update(m.span() for m in pattern.finditer(text))
        # overlapping aliases ("AI" inside "AI models") are one mention
        mentions, last_end = 0, -1
        for start, end in sorted(spans):
            if start >= last_end:
                mentions += 1
            last_end = max(last_end, end)
        if mentions:
            counts[canonical] = mentions
    return counts


def resume_skills(text: str, db: SkillsDB) -> set[str]:
    """Skills on the resume, including general skills implied by specific ones."""
    found = set(count_skills(text, db))
    frontier = list(found)
    while frontier:
        for implied in db.implies.get(frontier.pop(), ()):
            if implied not in found:
                found.add(implied)
                frontier.append(implied)
    return found


def candidate_phrases(skills_section: str) -> list[str]:
    """Short items from the resume's skills section, e.g. "Containerisation"."""
    phrases: list[str] = []
    for line in skills_section.splitlines():
        line = line.split(":", 1)[-1]  # drop labels such as "Languages:"
        for item in re.split(r"[,;|•●▪·/]|\s-\s", line):
            item = item.strip(" .()-")
            if 2 < len(item) <= 40 and len(item.split()) <= 4:
                phrases.append(item)
    return list(dict.fromkeys(phrases))


def synonym_matches(
    wanted: list[str], phrases: list[str], embedder: Embedder, threshold: float
) -> list[dict]:
    """JD skills the alias list missed but a resume phrase means the same thing.

    Returns [{"skill", "resume_phrase", "similarity"}] for pairs above threshold.
    """
    if not wanted or not phrases:
        return []
    sims = embedder.encode(wanted) @ embedder.encode(phrases).T
    matches = []
    for i, skill in enumerate(wanted):
        j = int(np.argmax(sims[i]))
        if sims[i, j] >= threshold:
            matches.append(
                {
                    "skill": skill,
                    "resume_phrase": phrases[j],
                    "similarity": round(float(sims[i, j]), 3),
                }
            )
    return matches
