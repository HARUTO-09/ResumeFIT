"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
"""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.admin import record_request
from app.admin import router as admin_router
from app.auth import router as auth_router
from app.config import Settings, get_settings
from app.core.embeddings import Embedder, EmbeddingCache, build_embedder
from app.core.guidance import load_guidance
from app.core.llm import LLM, build_llm
from app.core.security import FirebaseVerifier
from app.core.skills import load_skills
from app.db import init_db, make_engine, purge_expired
from app.errors import AppError
from app.logging_utils import log_event, setup_logging
from app.routes import router
from app.store import sync_guidance

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}
_FROM_SETTINGS = object()


def create_app(
    settings: Settings | None = None,
    embedder: Embedder | None = None,
    llm: LLM | None | object = _FROM_SETTINGS,
) -> FastAPI:
    """Build the app. Tests pass an embedder and an llm (None means retrieval-only)."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        state = app.state
        state.settings = settings
        state.limits = settings.limits()
        state.scoring = settings.scoring()
        state.session_factory = init_db(engine)
        state.skills_db = load_skills()
        # The embedding model loads once, here, not per request.
        state.embedder = embedder or build_embedder(
            settings.embedding_backend, settings.embedding_model
        )
        state.jd_cache = EmbeddingCache()
        state.coach = settings.coach()
        state.monitoring = settings.monitoring()
        state.admin_emails = settings.admin_email_set()
        if settings.firebase_project_id:
            state.verifier = FirebaseVerifier(
                settings.firebase_project_id, jwks_url=settings.firebase_jwks_url
            )
        else:  # /health still works; protected endpoints answer 503 until it is set
            state.verifier = None
            log_event("auth_not_configured", note="RESUMEFIT_FIREBASE_PROJECT_ID is not set")
        if llm is _FROM_SETTINGS:
            state.llm = build_llm(
                settings.llm_provider,
                settings.llm_base_url,
                settings.llm_model,
                settings.llm_api_key,
                settings.llm_timeout_s,
            )
        else:
            state.llm = llm
        with state.session_factory() as session:
            removed = purge_expired(session, settings.retention_days)
            reingested = sync_guidance(session, load_guidance(), state.embedder, state.coach)
        log_event(
            "startup",
            embedder=state.embedder.name,
            llm=state.llm.name if state.llm is not None else "retrieval-only",
            expired_removed=removed,
            guidance_reingested=reingested,
            admins=len(state.admin_emails),
            firebase_project=settings.firebase_project_id or None,
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="ResumeFit",
        version=__version__,
        description="Scores a resume against a job description and explains the gaps. "
        "The score is a guide to improving a resume, not a hiring decision, and it can be wrong.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # unexpected failure: same error shape, no details leaked
            request.state.error_code = "internal_error"
            log_event("unhandled_exception", request_id=request_id, type=type(exc).__name__)
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "Something went wrong."}},
            )
        response.headers["X-Request-ID"] = request_id
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_code = getattr(request.state, "error_code", None)
        log_event(
            "request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
            error_code=error_code,
            **getattr(request.state, "log", {}),
        )
        # Admin metrics: one row per request to a known route (the route template,
        # so /analyses/an_1 and /analyses/an_2 count together). Unknown URLs are skipped.
        route = request.scope.get("route")
        session_factory = getattr(request.app.state, "session_factory", None)
        if route is not None and session_factory is not None:
            await run_in_threadpool(
                record_request,
                session_factory,
                request.method,
                getattr(route, "path", request.url.path),
                response.status_code,
                latency_ms,
                error_code,
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        request.state.error_code = exc.code
        return JSONResponse(status_code=exc.status, content=exc.body(), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        request.state.error_code = "invalid_input"
        errors = exc.errors()
        first = errors[0] if errors else {"loc": (), "msg": "Invalid input."}
        field = ".".join(str(part) for part in first["loc"] if part != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return JSONResponse(
            status_code=422, content={"error": {"code": "invalid_input", "message": message}}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        request.state.error_code = code
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail)}},
        )

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    return app


app = create_app()
