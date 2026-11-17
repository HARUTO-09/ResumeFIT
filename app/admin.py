"""Admin metrics (PRD F15) and the per-request metrics they are built from.

GET /admin/metrics shows, for the last N days (default 7): request volume,
p50/p95 latency per endpoint, error rates, quota hits, active users and usage,
the score distribution, the rating trend, and the drift check that compares
the latest week's scores with the first week's.
"""

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import monitoring
from app.core.params import MonitoringParams
from app.deps import CurrentUser, get_session, require_admin
from app.logging_utils import log_event
from app.models import Feedback, RequestMetric, ScoreEvent, Usage, utcnow
from app.schemas import AdminMetricsOut

router = APIRouter(prefix="/admin", tags=["admin"])

# Endpoints whose latency the PRD sets targets for; others are still counted.
LATENCY_PATHS = ("/analyze", "/coach", "/jd/extract")
NOT_RECORDED = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def record_request(
    session_factory: sessionmaker[Session],
    method: str,
    path: str,
    status: int,
    latency_ms: int,
    error_code: str | None,
) -> None:
    """Store one request's metadata. Never raises: metrics must not break a request."""
    if path in NOT_RECORDED:
        return
    try:
        with session_factory() as session:
            session.add(
                RequestMetric(
                    method=method,
                    path=path[:80],
                    status=status,
                    latency_ms=latency_ms,
                    error_code=error_code,
                    quota_hit=error_code == "quota_exceeded",
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 - log and carry on
        log_event("metrics_write_failed", type=type(exc).__name__)


def _drift(session: Session, now: datetime, params: MonitoringParams) -> dict:
    """First week of score events against the latest week."""
    first = session.scalars(select(ScoreEvent.created_at).order_by(ScoreEvent.created_at)).first()
    window = timedelta(days=7)
    if first is None:
        return {"status": "insufficient_data", "reasons": ["no scores recorded yet"]}
    baseline_end = first + window
    current_start = now - window
    if current_start < baseline_end:
        result = {
            "status": "insufficient_data",
            "reasons": ["needs two separate weeks of scores: a baseline week and a recent week"],
        }
    else:
        baseline = session.execute(
            select(ScoreEvent.score, ScoreEvent.model_version).where(
                ScoreEvent.created_at >= first, ScoreEvent.created_at < baseline_end
            )
        ).all()
        current = session.execute(
            select(ScoreEvent.score, ScoreEvent.model_version).where(
                ScoreEvent.created_at >= current_start
            )
        ).all()
        result = monitoring.drift_check(
            [r.score for r in baseline], [r.score for r in current], params
        )
        base_models = sorted({r.model_version for r in baseline})
        current_models = sorted({r.model_version for r in current})
        result["baseline_models"] = base_models
        result["current_models"] = current_models
        if base_models != current_models:
            result["reasons"].append(
                "the model version changed between the two weeks, so some shift is expected"
            )
    result["baseline_week"] = {"from": first.isoformat(), "to": baseline_end.isoformat()}
    result["current_week"] = {"from": current_start.isoformat(), "to": now.isoformat()}
    return result


def build_metrics(session: Session, params: MonitoringParams, now: datetime | None = None) -> dict:
    now = now or utcnow()  # naive UTC, like the stored timestamps
    since = now - timedelta(days=params.window_days)
    days = monitoring.days_between(since.date(), now.date())

    # ---- requests -------------------------------------------------------------------
    requests = session.execute(
        select(
            RequestMetric.created_at,
            RequestMetric.path,
            RequestMetric.status,
            RequestMetric.latency_ms,
            RequestMetric.quota_hit,
        ).where(RequestMetric.created_at >= since)
    ).all()
    latencies: dict[str, list[float]] = defaultdict(list)
    for r in requests:
        # latency targets are about successful work, not fast rejections
        if r.path in LATENCY_PATHS and r.status < 400:
            latencies[r.path].append(r.latency_ms)
    quota_times = [r.created_at for r in requests if r.quota_hit]
    by_path: dict[str, int] = defaultdict(int)
    for r in requests:
        by_path[r.path] += 1

    # ---- usage ------------------------------------------------------------------------
    usage_rows = session.scalars(select(Usage).where(Usage.day >= since.date().isoformat())).all()
    per_user: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for u in usage_rows:
        per_user[u.user_id][0] += u.analyses_count
        per_user[u.user_id][1] += u.coach_count
    top_users = sorted(per_user.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:10]

    # ---- scores ------------------------------------------------------------------------
    scores = session.execute(
        select(ScoreEvent.score, ScoreEvent.band, ScoreEvent.sections_missing).where(
            ScoreEvent.created_at >= since
        )
    ).all()

    # ---- ratings -----------------------------------------------------------------------
    ratings = session.execute(
        select(Feedback.created_at, Feedback.rating, Feedback.target_type).where(
            Feedback.created_at >= since
        )
    ).all()

    rating_block = monitoring.rating_summary(
        [(r.created_at, r.rating, r.target_type) for r in ratings], days, params
    )
    drift = _drift(session, now, params)
    error_block = monitoring.error_rates([r.status for r in requests])

    flags = []
    if drift.get("status") == "drift":
        flags.append("Score drift: " + "; ".join(drift["reasons"]))
    if rating_block["flag"]:
        flags.append(f"Average rating {rating_block['mean']} is below {params.rating_flag_below:g}")
    if error_block["server_error_rate"] and error_block["server_error_rate"] > 0.01:
        flags.append(f"Server error rate is {error_block['server_error_rate']:.1%}")

    return {
        "generated_at": now.replace(tzinfo=timezone.utc),
        "window": {
            "days": params.window_days,
            "from": since.replace(tzinfo=timezone.utc).isoformat(),
            "to": now.replace(tzinfo=timezone.utc).isoformat(),
        },
        "requests": {
            **error_block,
            "by_path": dict(sorted(by_path.items())),
            "latency": monitoring.latency_summary(latencies),
        },
        "quota_hits": {
            "total": len(quota_times),
            "by_day": monitoring.daily_counts(quota_times, days),
        },
        "usage": {
            "active_users": len(per_user),
            "analyses": sum(v[0] for v in per_user.values()),
            "coach_messages": sum(v[1] for v in per_user.values()),
            # pseudonymous ids only; no emails on this page
            "top_users": [
                {"user_id": uid, "analyses": a, "coach_messages": c} for uid, (a, c) in top_users
            ],
        },
        "scores": monitoring.score_summary(
            [s.score for s in scores],
            [s.band for s in scores],
            [s.sections_missing for s in scores],
        ),
        "ratings": rating_block,
        "drift": drift,
        "flags": flags,
    }


@router.get("/metrics", response_model=AdminMetricsOut)
def metrics(
    request: Request,
    days: int | None = Query(default=None, ge=1, le=90, description="Window length in days"),
    admin: CurrentUser = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Quality, latency and usage for the last N days. Administrators only."""
    params = request.app.state.monitoring
    if days is not None:
        params = replace(params, window_days=days)
    return build_metrics(session, params)
