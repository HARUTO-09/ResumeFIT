"""Feedback (PRD F14), admin metrics (F15), request metrics and the drift check."""

from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")

from helpers import (  # noqa: E402
    JD_TEXT,
    RESUME_TEXT,
    FakeLLM,
    bearer,
    cite_first_passage,
    make_pdf,
    token_for,
)
from sqlalchemy import func, select  # noqa: E402

from app.db import purge_expired  # noqa: E402
from app.models import (  # noqa: E402
    Analysis,
    CoachMessage,
    Feedback,
    RequestMetric,
    ScoreEvent,
    Usage,
    utcnow,
)

PDF = "application/pdf"
ADMIN = "admin@example.com"


@pytest.fixture(scope="module")
def resume_pdf():
    return make_pdf(RESUME_TEXT)


def analyze(client, token, resume_pdf):
    response = client.post(
        "/analyze",
        files={"resume": ("resume.pdf", resume_pdf, PDF)},
        data={"jd_text": JD_TEXT},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def rate(client, token, target_type, target_id, rating, comment=None):
    body = {"target_type": target_type, "target_id": target_id, "rating": rating}
    if comment is not None:
        body["comment"] = comment
    return client.post("/feedback", json=body, headers=bearer(token))


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# ---- feedback ---------------------------------------------------------------------------
def test_rate_an_analysis_then_change_the_rating(make_api, resume_pdf):
    client = make_api()
    token = token_for(client)
    analysis = analyze(client, token, resume_pdf)

    first = rate(client, token, "analysis", analysis["id"], 4, "Useful gap list")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["rating"] == 4 and body["comment"] == "Useful gap list"
    assert body["model_version"] == analysis["model_version"]

    again = rate(client, token, "analysis", analysis["id"], 2)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == body["id"] and again.json()["rating"] == 2
    assert again.json()["comment"] is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Feedback)) == 1


def test_rate_a_coach_answer_with_its_model_version(make_api, resume_pdf):
    client = make_api(FakeLLM(cite_first_passage))
    token = token_for(client)
    analysis_id = analyze(client, token, resume_pdf)["id"]
    answer = client.post(
        "/coach",
        json={"analysis_id": analysis_id, "question": "How do I show deployment experience?"},
        headers=bearer(token),
    ).json()
    rated = rate(client, token, "coach_message", answer["id"], 5)
    assert rated.status_code == 201, rated.text
    assert rated.json()["model_version"] == answer["model_version"]

    # the student's own question is not a rateable answer
    with client.app.state.session_factory() as session:
        question_id = session.scalars(
            select(CoachMessage.id).where(CoachMessage.role == "user")
        ).one()
    assert_error(rate(client, token, "coach_message", question_id, 5), 404, "not_found")


def test_feedback_comment_is_redacted(make_api, resume_pdf):
    client = make_api()
    token = token_for(client)
    analysis_id = analyze(client, token, resume_pdf)["id"]
    body = rate(
        client, token, "analysis", analysis_id, 3, "Call me on 98765 43210 or asha@example.com"
    ).json()
    assert "98765" not in body["comment"] and "asha@example.com" not in body["comment"]
    assert "[PHONE]" in body["comment"] and "[EMAIL]" in body["comment"]


@pytest.mark.parametrize(
    "body",
    [
        {"target_type": "analysis", "target_id": "an_x", "rating": 0},
        {"target_type": "analysis", "target_id": "an_x", "rating": 6},
        {"target_type": "resume", "target_id": "an_x", "rating": 3},
        {"target_type": "analysis", "target_id": "an_x", "rating": 3, "comment": "x" * 1001},
    ],
)
def test_feedback_validation(make_api, body):
    client = make_api()
    token = token_for(client)
    assert_error(client.post("/feedback", json=body, headers=bearer(token)), 422, "invalid_input")


def test_unknown_target_is_not_found(make_api):
    client = make_api()
    token = token_for(client)
    assert_error(rate(client, token, "analysis", "an_missing", 3), 404, "not_found")
    assert_error(rate(client, token, "coach_message", "cm_missing", 3), 404, "not_found")


def test_deleting_an_analysis_keeps_the_rating_but_drops_the_link_and_comment(make_api, resume_pdf):
    client = make_api()
    token = token_for(client)
    analysis_id = analyze(client, token, resume_pdf)["id"]
    rate(client, token, "analysis", analysis_id, 2, "The projects advice was vague")
    assert client.delete(f"/analyses/{analysis_id}", headers=bearer(token)).status_code == 204
    with client.app.state.session_factory() as session:
        row = session.scalars(select(Feedback)).one()
    assert row.rating == 2 and row.model_version.startswith("matcher-")
    assert row.target_id is None and row.analysis_id is None and row.comment is None


# ---- admin metrics ---------------------------------------------------------------------------
def test_admin_metrics_are_for_admins_only(make_api):
    client = make_api(admin_emails=ADMIN)
    student = token_for(client, "student@example.com")
    assert_error(client.get("/admin/metrics"), 401, "not_authenticated")
    assert_error(client.get("/admin/metrics", headers=bearer(student)), 403, "forbidden")

    admin = token_for(client, "Admin@Example.com")
    assert client.get("/auth/me", headers=bearer(admin)).json()["is_admin"] is True
    assert client.get("/admin/metrics", headers=bearer(admin)).status_code == 200


def test_admin_metrics_reflect_activity(make_api, resume_pdf):
    client = make_api(FakeLLM(cite_first_passage), admin_emails=ADMIN, quota_analyses_per_day=2)
    student = token_for(client, "student@example.com")
    first = analyze(client, student, resume_pdf)
    analyze(client, student, resume_pdf)
    over = client.post(
        "/analyze",
        files={"resume": ("resume.pdf", resume_pdf, PDF)},
        data={"jd_text": JD_TEXT},
        headers=bearer(student),
    )
    assert over.status_code == 429
    client.get(f"/analyses/{first['id']}", headers=bearer(student))
    answer = client.post(
        "/coach",
        json={"analysis_id": first["id"], "question": "How do I show deployment experience?"},
        headers=bearer(student),
    ).json()
    rate(client, student, "analysis", first["id"], 4)
    rate(client, student, "coach_message", answer["id"], 2)

    admin = token_for(client, ADMIN)
    response = client.get("/admin/metrics", headers=bearer(admin))
    assert response.status_code == 200, response.text
    m = response.json()

    assert m["window"]["days"] == 7
    assert m["requests"]["requests"] >= 6
    assert m["requests"]["by_path"]["/analyze"] == 3
    # route templates, not raw URLs: no analysis ids in the metrics
    assert "/analyses/{analysis_id}" in m["requests"]["by_path"]
    assert not any(first["id"] in path for path in m["requests"]["by_path"])
    assert m["requests"]["latency"]["/analyze"]["n"] == 2  # the 429 is not a latency sample
    assert m["requests"]["latency"]["/coach"]["n"] == 1
    assert m["quota_hits"]["total"] == 1
    assert sum(day["count"] for day in m["quota_hits"]["by_day"]) == 1

    assert m["usage"]["active_users"] == 1
    assert m["usage"]["analyses"] == 2 and m["usage"]["coach_messages"] == 1
    assert m["usage"]["top_users"][0]["analyses"] == 2
    assert "student@example.com" not in response.text  # no emails on the admin page

    assert m["scores"]["count"] == 2
    assert sum(m["scores"]["bands"].values()) == 2
    assert sum(b["count"] for b in m["scores"]["histogram"]) == 2

    assert m["ratings"]["count"] == 2 and m["ratings"]["mean"] == 3.0
    assert m["ratings"]["by_target"]["analysis"] == {"count": 1, "mean": 4.0}
    assert m["drift"]["status"] == "insufficient_data"
    assert isinstance(m["flags"], list)


def test_admin_window_parameter(make_api):
    client = make_api(admin_emails=ADMIN)
    admin = token_for(client, ADMIN)
    one_day = client.get("/admin/metrics?days=1", headers=bearer(admin))
    assert one_day.status_code == 200 and one_day.json()["window"]["days"] == 1
    assert_error(client.get("/admin/metrics?days=0", headers=bearer(admin)), 422, "invalid_input")


def _add_scores(client, start_days_ago: int, scores: list[int], model="matcher-test"):
    now = utcnow()
    with client.app.state.session_factory() as session:
        for i, score in enumerate(scores):
            when = now - timedelta(days=start_days_ago) + timedelta(hours=i % 120)
            session.add(
                ScoreEvent(
                    created_at=when,
                    score=score,
                    band="partial",
                    sections_missing=0,
                    model_version=model,
                )
            )
        session.commit()


def test_drift_check_flags_a_shift_from_the_first_week(make_api):
    client = make_api(admin_emails=ADMIN)
    admin = token_for(client, ADMIN)
    _add_scores(client, 21, [40 + (i % 7) for i in range(30)])  # baseline week, mean ~43
    _add_scores(client, 6, [65 + (i % 7) for i in range(30)])  # latest week, mean ~68
    m = client.get("/admin/metrics", headers=bearer(admin)).json()
    assert m["drift"]["status"] == "drift", m["drift"]
    assert m["drift"]["mean_shift"] > 10
    assert any(flag.startswith("Score drift") for flag in m["flags"])


def test_drift_check_is_quiet_when_scores_are_stable(make_api):
    client = make_api(admin_emails=ADMIN)
    admin = token_for(client, ADMIN)
    _add_scores(client, 21, [50 + (i % 9) for i in range(30)])
    _add_scores(client, 6, [50 + (i % 9) for i in range(30)])
    m = client.get("/admin/metrics", headers=bearer(admin)).json()
    assert m["drift"]["status"] == "ok", m["drift"]
    assert not any(flag.startswith("Score drift") for flag in m["flags"])


def test_low_average_rating_is_flagged(make_api, resume_pdf):
    client = make_api(admin_emails=ADMIN)
    student = token_for(client)
    for _ in range(5):
        rate(client, student, "analysis", analyze(client, student, resume_pdf)["id"], 2)
    admin = token_for(client, ADMIN)
    m = client.get("/admin/metrics", headers=bearer(admin)).json()
    assert m["ratings"]["flag"] is True
    assert any("Average rating" in flag for flag in m["flags"])


def test_retention_keeps_score_events_but_drops_old_metrics_and_usage(make_api, resume_pdf):
    client = make_api()
    token = token_for(client)
    analyze(client, token, resume_pdf)
    old = utcnow() - timedelta(days=40)
    with client.app.state.session_factory() as session:
        for model in (Analysis, RequestMetric, ScoreEvent):
            for row in session.scalars(select(model)):
                row.created_at = old
        for row in session.scalars(select(Usage)):
            row.day = old.date().isoformat()
        session.commit()
        assert purge_expired(session, retention_days=30) == 1
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0
        assert session.scalar(select(func.count()).select_from(Usage)) == 0
        assert session.scalar(select(func.count()).select_from(ScoreEvent)) == 1
        # rows written after the purge (this session's own requests) are fine
        assert (
            session.scalar(
                select(func.count())
                .select_from(RequestMetric)
                .where(RequestMetric.created_at < utcnow() - timedelta(days=30))
            )
            == 0
        )
