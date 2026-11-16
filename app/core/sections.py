"""Split resume text into sections and text into scoreable units (F3)."""

import re

CORE_SECTIONS = ("skills", "projects", "experience", "education")

_HEADINGS: dict[str, tuple[str, ...]] = {
    "skills": (
        "skills",
        "technical skills",
        "key skills",
        "core skills",
        "skills summary",
        "skills and tools",
        "skills & tools",
        "core competencies",
        "technologies",
        "tech stack",
        "technical proficiency",
        "tools and technologies",
    ),
    "projects": (
        "projects",
        "academic projects",
        "personal projects",
        "key projects",
        "project experience",
        "selected projects",
        "major projects",
        "mini projects",
    ),
    "experience": (
        "experience",
        "work experience",
        "professional experience",
        "internships",
        "internship",
        "internship experience",
        "employment",
        "employment history",
        "work history",
        "industry experience",
    ),
    "education": (
        "education",
        "academic background",
        "academics",
        "qualifications",
        "educational qualifications",
        "academic qualifications",
        "academic details",
    ),
    "other": (
        "summary",
        "professional summary",
        "objective",
        "career objective",
        "profile",
        "about me",
        "certifications",
        "certificates",
        "achievements",
        "awards",
        "publications",
        "extracurricular",
        "extracurricular activities",
        "activities",
        "positions of responsibility",
        "leadership",
        "volunteering",
        "languages",
        "interests",
        "hobbies",
        "courses",
        "coursework",
        "relevant coursework",
        "references",
        "declaration",
        "personal details",
    ),
}
_HEADING_LOOKUP = {alias: name for name, aliases in _HEADINGS.items() for alias in aliases}

_BULLET = re.compile(r"^\s*(?:[•●▪■◦‣·*\-–—➢►]|\(?\d{1,2}[.)])\s+")
_TERMINAL = (".", "!", "?", ":", ";")
_WRAP_LENGTH = 70  # a line at least this long was probably wrapped by the layout


def _heading_name(line: str) -> str | None:
    cleaned = re.sub(r"[^a-z& ]", " ", line.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or len(cleaned) > 40:
        return None
    return _HEADING_LOOKUP.get(cleaned)


def split_sections(text: str) -> dict[str, str]:
    """Return {"header": ..., "skills": ..., ...}.

    "header" is everything before the first heading (name and contact details).
    Sections that share a name are concatenated. Unknown headings land in "other".
    """
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        name = _heading_name(line)
        if name:
            current = name
            sections.setdefault(current, [])
            continue
        sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def missing_sections(sections: dict[str, str]) -> list[str]:
    return [name for name in CORE_SECTIONS if not sections.get(name)]


def split_units(text: str, min_words: int = 3) -> list[str]:
    """Turn free text into sentence-like units.

    Joins lines broken by PDF layout, turns bullets into their own units, then
    splits on sentence ends. Used for JD requirements and resume chunks alike,
    so the same text scores the same whether it arrived pasted or from a file.
    """
    units: list[str] = []
    current = ""
    prev_len = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                units.append(current)
            current, prev_len = "", 0
            continue
        is_bullet = bool(_BULLET.match(raw))
        line = _BULLET.sub("", raw).strip() if is_bullet else line
        continues = (
            current
            and not is_bullet
            and not current.endswith(_TERMINAL)
            and (line[0].islower() or prev_len >= _WRAP_LENGTH)
        )
        if continues:
            current = f"{current} {line}"
        else:
            if current:
                units.append(current)
            current = line
        prev_len = len(raw.strip())
    if current:
        units.append(current)

    sentences: list[str] = []
    for unit in units:
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", unit):
            part = part.strip(" \t-")
            if len(part.split()) >= min_words:
                sentences.append(part)
    return sentences
