"""Split text into passages for retrieval (about 200 to 300 tokens, small overlap)."""

from app.core.redaction import redact
from app.core.sections import split_sections, split_units


def chunk_text(text: str, max_words: int = 180, overlap_words: int = 30) -> list[str]:
    """Pack sentence-like units into chunks of at most max_words words.

    Each new chunk starts with the last few units of the previous one, so a
    fact that straddles a boundary is still retrievable.
    """
    units: list[str] = []
    for unit in split_units(text, min_words=1):
        words = unit.split()
        # a single very long unit is cut on word boundaries
        for start in range(0, len(words), max_words):
            units.append(" ".join(words[start : start + max_words]))

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        n = len(unit.split())
        if current and size + n > max_words:
            chunks.append("\n".join(current))
            tail: list[str] = []
            tail_size = 0
            for previous in reversed(current):
                previous_size = len(previous.split())
                if tail_size + previous_size > overlap_words:
                    break
                tail.insert(0, previous)
                tail_size += previous_size
            current, size = tail, tail_size
        current.append(unit)
        size += n
    if current:
        chunks.append("\n".join(current))
    return chunks


def resume_passages(
    resume_text: str, max_words: int = 180, overlap_words: int = 30
) -> list[tuple[str, str]]:
    """(section, text) passages from a resume, with identity removed.

    The header (name, contact details, address) is dropped and the rest is
    redacted, exactly as for scoring, so nothing stored for the coach or sent
    to a language model carries contact details.
    """
    sections = split_sections(resume_text)
    header = sections.pop("header", "")
    body = {name: redact(text, header).text for name, text in sections.items() if text}
    if not body:
        body = {"resume": redact(resume_text, header).text}
    passages: list[tuple[str, str]] = []
    for name, text in body.items():
        passages.extend((name, chunk) for chunk in chunk_text(text, max_words, overlap_words))
    return passages
