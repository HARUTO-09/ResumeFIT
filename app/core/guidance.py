"""Load the career-guidance corpus from app/data/guidance/*.md.

Each file starts with a small header recording where the text came from:

    ---
    title: Showing deployment experience
    source: Written for ResumeFit by the project author
    version: 1
    ---
    Body text...
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

GUIDANCE_DIR = Path(__file__).resolve().parent.parent / "data" / "guidance"


@dataclass(frozen=True)
class GuidanceDoc:
    slug: str
    title: str
    source: str
    version: str
    text: str


def parse_guidance(slug: str, raw: str) -> GuidanceDoc:
    raw = raw.replace("\r\n", "\n").lstrip("﻿")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError(f"Guidance file {slug!r} has no header block.")
    head, body = raw[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip()
    missing = [key for key in ("title", "source", "version") if not meta.get(key)]
    if missing:
        raise ValueError(f"Guidance file {slug!r} is missing: {', '.join(missing)}.")
    return GuidanceDoc(slug, meta["title"], meta["source"], meta["version"], body.strip())


def load_guidance(directory: Path = GUIDANCE_DIR) -> list[GuidanceDoc]:
    return [
        parse_guidance(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.md"))
    ]


def corpus_fingerprint(docs: list[GuidanceDoc], embedder_name: str, chunking: str) -> str:
    """Changes when any document, the embedder or the chunk settings change."""
    digest = hashlib.sha256(f"{embedder_name}|{chunking}".encode())
    for doc in docs:
        digest.update(f"|{doc.slug}|{doc.version}|{doc.title}|{doc.text}".encode())
    return digest.hexdigest()[:16]
