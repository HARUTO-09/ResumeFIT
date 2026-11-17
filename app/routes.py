"""Endpoints: /health, /jd/extract, /analyze, /analyses (Phase 1), /coach (Phase 2)
and /feedback (Phase 3). Accounts live in app/auth.py, admin metrics in app/admin.py.

Everything except /health needs a signed-in user (see app/auth.py), and every
analysis, coach message and feedback lookup is filtered by that user's id, so
one user can never read, list, rate or delete another's data (PRD F12).

Handlers are plain `def` functions, so FastAPI runs them in a thread pool and
the CPU-bound parsing and embedding work does not block the event loop.
"""

import time

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.coach import COACH_VERSION, answer_question
from app.core.documents import normalise_text, read_jd_file, read_resume, validate_jd_text
from app.core.llm import LLMUnavailable
from app.core.pipeline import analyze_texts, model_version
from app.core.redaction import redact
from app.db import delete_analysis_data
from app.deps import CurrentUser, current_user, get_session
from app.errors import AppError
from app.models import (
    Analysis,
    CoachMessage,
    Feedback,
    GuidanceDoc,
    ScoreEvent,
    new_analysis_id,
    utcnow,
)
from app.quotas import check_quota, count_use
from app.schemas import (
    AnalysisOut,
    AnalysisSummary,
    Citation,
    CoachIn,
    CoachOut,
    FeedbackIn,
    FeedbackOut,
    HealthOut,
    JDExtractOut,
)
from app.store import add_analysis_chunks, load_passages

router = APIRouter()

JD_SOURCES = ("text", "pdf", "docx")


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


def get_analysis_or_404(session: Session, analysis_id: str, user_id: str) -> Analysis:
    """The one shared ownership check. Another user's analysis is reported as not found,
    so its existence is not revealed."""
    row = session.get(Analysis, analysis_id)
    if row is None or row.user_id != user_id:
        raise AppError(404, "not_found", "Analysis not found.")
    return row


def coach_model_version(state) -> str:
    llm_name = state.llm.name if state.llm is not None else "retrieval-only"
    return f"coach-{COACH_VERSION}+{state.embedder.name}+{llm_name}"


@router.get("/health", response_model=HealthOut)
def health(request: Request, session: Session = Depends(get_session)):
    state = request.app.state
    return HealthOut(
        status="ok",
        model_version=model_version(state.embedder),
        embedding_backend=state.settings.embedding_backend,
        coach_model_version=coach_model_version(state),
        guidance_docs=session.scalar(select(func.count()).select_from(GuidanceDoc)) or 0,
    )


@router.post("/jd/extract", response_model=JDExtractOut)
def jd_extract(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(current_user),
):
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
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    state = request.app.state
    limits = state.limits
    started = time.perf_counter()
    quota_day = check_quota(session, user.id, "analyses", state.settings.quota_analyses_per_day)

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
        id=new_analysis_id(),
        user_id=user.id,
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
    # Redacted resume passages and JD passages for the coach, saved with the analysis
    # in one transaction and deleted with it.
    add_analysis_chunks(session, row.id, resume_text, jd_clean, state.embedder, state.coach)
    # Anonymous copy of the score for the weekly drift check; kept after the analysis expires.
    session.add(
        ScoreEvent(
            score=result.score,
            band=result.band,
            sections_missing=len(result.sections_missing),
            model_version=result.model_version,
        )
    )
    count_use(session, user.id, "analyses", quota_day)
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
def list_analyses(
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
    limit: int = 50,
):
    limit = max(1, min(limit, 200))
    rows = session.scalars(
        select(Analysis)
        .where(Analysis.user_id == user.id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(limit)
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
def read_analysis(
    analysis_id: str,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    return to_out(get_analysis_or_404(session, analysis_id, user.id))


@router.delete("/analyses/{analysis_id}", status_code=204, response_class=Response)
def delete_analysis(
    analysis_id: str,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    row = get_analysis_or_404(session, analysis_id, user.id)
    # The analysis, its coach messages and its vector chunks go in one transaction;
    # feedback on it is unlinked (see app/db.py).
    delete_analysis_data(session, [row.id])
    session.commit()
    return Response(status_code=204)


@router.post("/coach", response_model=CoachOut)
def coach(
    request: Request,
    body: CoachIn,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Ask a question about one analysis. Answers come only from the sources, with citations."""
    state = request.app.state
    params = state.coach
    started = time.perf_counter()

    row = get_analysis_or_404(session, body.analysis_id, user.id)
    question = normalise_text(body.question)
    if not params.question_min_chars <= len(question) <= params.question_max_chars:
        raise AppError(
            422,
            "question_length",
            f"The question must be {params.question_min_chars} to "
            f"{params.question_max_chars} characters.",
        )
    quota_day = check_quota(session, user.id, "coach", state.settings.quota_coach_per_day)

    passages, vectors = load_passages(session, row.id, state.embedder)
    try:
        result = answer_question(question, passages, vectors, state.embedder, state.llm, params)
    except LLMUnavailable as exc:
        request.state.log = {"analysis_id": row.id, "llm_problem": str(exc)}
        raise AppError(
            503,
            "llm_unavailable",
            "The coach's language model cannot be reached right now. "
            "The matcher still works; please try the coach again later.",
        ) from None

    version = coach_model_version(state)
    cited_ids = [p.id for p in result.citations]
    # Contact details typed into a question are not stored.
    session.add(
        CoachMessage(
            analysis_id=row.id, user_id=user.id, role="user", content=redact(question).text
        )
    )
    reply = CoachMessage(
        analysis_id=row.id,
        user_id=user.id,
        role="assistant",
        content=result.answer,
        cited_passage_ids=cited_ids,
        status=result.status,
        model_version=version,
    )
    session.add(reply)
    # A failed model call (503 above) is not counted against the quota.
    count_use(session, user.id, "coach", quota_day)
    session.commit()

    request.state.log = {
        "analysis_id": row.id,
        "coach_status": result.status,
        "coach_reason": result.reason,
        "retrieved": len(result.retrieved),
        "cited": len(cited_ids),
        "model_version": version,
    }
    return CoachOut(
        id=reply.id,
        analysis_id=row.id,
        status=result.status,
        answer=result.answer,
        citations=[
            Citation(id=p.id, source=p.source, label=p.label, text=p.text) for p in result.citations
        ],
        reason=result.reason,
        model_version=version,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def feedback(
    body: FeedbackIn,
    response: Response,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Rate one of your analyses or coach answers from 1 to 5 (PRD F14).

    Rating the same item again updates the earlier rating (200 instead of 201).
    The comment is optional; contact details in it are redacted before storage.
    """
    if body.target_type == "analysis":
        analysis = get_analysis_or_404(session, body.target_id, user.id)
        analysis_id, model_version = analysis.id, analysis.model_version
    else:
        message = session.get(CoachMessage, body.target_id)
        if message is None or message.user_id != user.id or message.role != "assistant":
            raise AppError(404, "not_found", "Coach answer not found.")
        analysis_id, model_version = message.analysis_id, message.model_version or "unknown"

    comment = None
    if body.comment and body.comment.strip():
        comment = redact(normalise_text(body.comment)).text

    now = utcnow()
    row = session.scalars(
        select(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.target_type == body.target_type,
            Feedback.target_id == body.target_id,
        )
    ).first()
    if row is None:
        row = Feedback(
            user_id=user.id,
            target_type=body.target_type,
            target_id=body.target_id,
            analysis_id=analysis_id,
            created_at=now,
        )
        session.add(row)
    else:
        response.status_code = 200
    row.rating = body.rating
    row.comment = comment
    row.model_version = model_version
    row.updated_at = now
    session.commit()
    return FeedbackOut(
        id=row.id,
        target_type=row.target_type,
        target_id=row.target_id,
        rating=row.rating,
        comment=row.comment,
        model_version=row.model_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
