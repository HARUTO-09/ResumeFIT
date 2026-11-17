"""SQL-backed vector store for the coach.

Passages and their embeddings live in the `chunks` table, next to the data
they belong to. That keeps "delete an analysis and its chunks" a single SQL
transaction, and search is an exact dot product over a few dozen vectors,
which needs no index. If the corpus grows to many thousands of passages, put
FAISS or Chroma behind `load_passages` without changing its callers.
"""

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.chunking import chunk_text, resume_passages
from app.core.coach import Passage, passage_id
from app.core.embeddings import Embedder
from app.core.guidance import GuidanceDoc as GuidanceFile
from app.core.guidance import corpus_fingerprint
from app.core.params import CoachParams
from app.models import Chunk, GuidanceDoc


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blobs(blobs: list[bytes]) -> np.ndarray:
    if not blobs:
        return np.zeros((0, 0), dtype=np.float32)
    return np.vstack([np.frombuffer(blob, dtype=np.float32) for blob in blobs])


def sync_guidance(
    session: Session, docs: list[GuidanceFile], embedder: Embedder, params: CoachParams
) -> bool:
    """Make the stored guidance corpus match the files. Returns True if it re-ingested.

    Re-ingestion happens when any file, the embedder or the chunk settings change.
    """
    chunking = f"{params.chunk_words}/{params.chunk_overlap_words}"
    fingerprint = corpus_fingerprint(docs, embedder.name, chunking)
    stored = set(session.scalars(select(GuidanceDoc.fingerprint)))
    count = session.scalar(select(func.count()).select_from(GuidanceDoc))
    if stored == {fingerprint} and count == len(docs):
        return False

    session.execute(delete(Chunk).where(Chunk.source == "guidance"))
    session.execute(delete(GuidanceDoc))
    for doc in docs:
        texts = chunk_text(doc.text, params.chunk_words, params.chunk_overlap_words)
        row = GuidanceDoc(
            slug=doc.slug,
            title=doc.title,
            source=doc.source,
            version=doc.version,
            chunk_count=len(texts),
            fingerprint=fingerprint,
        )
        session.add(row)
        session.flush()  # assigns row.id
        # The title is embedded with the text so a question can match either.
        vectors = embedder.encode([f"{doc.title}\n{text}" for text in texts])
        for ordinal, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
            session.add(
                Chunk(
                    source="guidance",
                    doc_id=row.id,
                    label=doc.title,
                    ordinal=ordinal,
                    text=text,
                    embedding=to_blob(vector),
                    embedder=embedder.name,
                )
            )
    session.commit()
    return True


def add_analysis_chunks(
    session: Session,
    analysis_id: str,
    resume_text: str,
    jd_text: str,
    embedder: Embedder,
    params: CoachParams,
) -> int:
    """Store redacted resume passages and JD passages for one analysis.

    Does not commit: the caller commits them together with the analysis row.
    """
    items = [
        ("resume", section, text)
        for section, text in resume_passages(
            resume_text, params.chunk_words, params.chunk_overlap_words
        )
    ]
    items += [
        ("jd", "job description", text)
        for text in chunk_text(jd_text, params.chunk_words, params.chunk_overlap_words)
    ]
    vectors = embedder.encode([f"{label}\n{text}" for _, label, text in items])
    for ordinal, ((source, label, text), vector) in enumerate(zip(items, vectors, strict=True)):
        session.add(
            Chunk(
                source=source,
                analysis_id=analysis_id,
                label=label,
                ordinal=ordinal,
                text=text,
                embedding=to_blob(vector),
                embedder=embedder.name,
            )
        )
    return len(items)


def load_passages(
    session: Session, analysis_id: str, embedder: Embedder
) -> tuple[list[Passage], np.ndarray]:
    """Everything the coach may search for this analysis: its resume, its JD, the guidance."""
    rows = session.scalars(
        select(Chunk)
        .where((Chunk.analysis_id == analysis_id) | (Chunk.source == "guidance"))
        .order_by(Chunk.id)
    ).all()

    # Chunks embedded by a different model (the setting changed) are re-embedded once.
    stale = [row for row in rows if row.embedder != embedder.name]
    if stale:
        vectors = embedder.encode([f"{row.label}\n{row.text}" for row in stale])
        for row, vector in zip(stale, vectors, strict=True):
            row.embedding = to_blob(vector)
            row.embedder = embedder.name
        session.commit()

    passages = [
        Passage(id=passage_id(r.source, r.id), source=r.source, label=r.label, text=r.text)
        for r in rows
    ]
    return passages, from_blobs([r.embedding for r in rows])
