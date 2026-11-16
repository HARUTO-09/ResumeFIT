"""Phase 1 endpoints: /health, /jd/extract, /analyze, /analyses.

Handlers are plain `def` functions, so FastAPI runs them in a thread pool and
the CPU-bound parsing and embedding work does not block the event loop.
"""

import time

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.documents import read_jd_file, read_resume, validate_jd_text
from app.core.pipeline import analyze_texts, model_version
from app.errors import AppError
from app.models import Analysis
from app.schemas import AnalysisOut, AnalysisSummary, HealthOut, JDExtractOut

router = APIRouter()

JD_SOURCES = ("text", "pdf", "docx")


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most one byte past the limit, so an oversized upload is never fully loaded."""
    return upload.file.read(max_bytes + 1)


def to_out(row: Analysis) -> AnalysisOut:
    report = row.report or {}
    return AnalysisOut(
        id=row.id,
        score=row.score,
        band=row.band,
        components=row.components,
        matched_skills=row.matched_skills,
        missing_skills=row.missing_skills,
        suggestions=report.get("suggestions", []),
        sections_found=report.get("sections_found", []),
        sections_missing=report.get("sections_missing", []),
        semantic_matches=report.get("semantic_matches", []),
        notes=report.get("notes", []),
        jd_source=row.jd_source,
        resume_text_stored=row.resume_text is not None,
        model_version=row.model_version,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
    )


def get_analysis_or_404(session: Session, analysis_id: str) -> Analysis:
    # Phase 3: this becomes the one shared ownership check (filter on user_id).
    row = session.get(Analysis, analysis_id)
    if row is None:
        raise AppError(404, "not_found", "Analysis not found.")
    return row


@router.get("/health", response_model=HealthOut)
def health(request: Request):
    state = request.app.state
    return HealthOut(
        status="ok",
        model_version=model_version(state.embedder),
        embedding_backend=state.settings.embedding_backend,
    )


@router.post("/jd/extract", response_model=JDExtractOut)
def jd_extract(request: Request, file: UploadFile = File(...)):
    """Read a JD file and return its text for preview and editing. Nothing is stored."""
    limits = request.app.state.limits
    text, source = read_jd_file(read_upload(file, limits.jd_max_bytes), limits)
    warning = None
    if len(text) > limits.jd_max_chars:
        warning = (
            f"The extracted text has {len(text)} characters; the limit is "
            f"{limits.jd_max_chars}. Trim it before scoring."
        )
    return JDExtractOut(text=text, source=source, char_count=len(text), warning=warning)


@router.post("/analyze", response_model=AnalysisOut, status_code=201)
def analyze(
    request: Request,
    resume: UploadFile = File(..., description="Resume as a PDF"),
    jd_text: str | None = Form(None, description="Job description as pasted text"),
    jd_file: UploadFile | None = File(None, description="Job description as PDF or DOCX"),
    jd_source: str | None = Form(
        None, description="Where edited jd_text came from: text, pdf or docx"
    ),
    store_resume_text: bool = Form(False, description="Opt in to storing the resume text"),
    session: Session = Depends(get_session),
):
    state = request.app.state
    limits = state.limits
    started = time.perf_counter()

    has_text = bool(jd_text and jd_text.strip())
    has_file = jd_file is not None and bool(jd_file.filename)
    if has_text == has_file:
        raise AppError(
            422,
            "jd_input",
            "Provide the job description as exactly one of jd_text or jd_file "
            + ("(both were sent)." if has_text else "(neither was sent)."),
        )
    if jd_source is not None and jd_source not in JD_SOURCES:
        raise AppError(422, "jd_source", "jd_source must be one of: text, pdf, docx.")

    resume_text = read_resume(read_upload(resume, limits.resume_max_bytes), limits)
    if has_file:
        raw_jd, source = read_jd_file(read_upload(jd_file, limits.jd_max_bytes), limits)
    else:
        raw_jd, source = jd_text, jd_source or "text"
    jd_clean = validate_jd_text(raw_jd, limits)

    result = analyze_texts(
        resume_text,
        jd_clean,
        embedder=state.embedder,
        skills_db=state.skills_db,
        params=state.scoring,
        cache=state.jd_cache,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    row = Analysis(
        jd_text=jd_clean,
        jd_source=source,
        resume_text=resume_text if store_resume_text else None,
        score=result.score,
        band=result.band,
        components=result.components,
        matched_skills=result.matched_skills,
        missing_skills=result.missing_skills,
        report={
            "suggestions": result.suggestions,
            "sections_found": result.sections_found,
            "sections_missing": result.sections_missing,
            "semantic_matches": result.semantic_matches,
            "notes": result.notes,
        },
        model_version=result.model_version,
        latency_ms=latency_ms,
    )
    session.add(row)
    session.commit()

    request.state.log = {
        "analysis_id": row.id,
        "score": row.score,
        "band": row.band,
        "jd_source": source,
        "model_version": row.model_version,
        "sections_missing": result.sections_missing,
    }
    return to_out(row)


@router.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(session: Session = Depends(get_session), limit: int = 50):
    limit = max(1, min(limit, 200))
    rows = session.scalars(
        select(Analysis).order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit)
    ).all()
    return [
        AnalysisSummary(
            id=r.id,
            score=r.score,
            band=r.band,
            jd_source=r.jd_source,
            jd_preview=r.jd_text[:120],
            model_version=r.model_version,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def read_analysis(analysis_id: str, session: Session = Depends(get_session)):
    return to_out(get_analysis_or_404(session, analysis_id))


@router.delete("/analyses/{analysis_id}", status_code=204, response_class=Response)
def delete_analysis(analysis_id: str, session: Session = Depends(get_session)):
    row = get_analysis_or_404(session, analysis_id)
    # Phase 2: also delete this analysis's vector chunks here, in the same step.
    session.delete(row)
    session.commit()
    return Response(status_code=204)
