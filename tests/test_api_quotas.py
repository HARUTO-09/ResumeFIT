"""Daily quotas (PRD F13): over the limit returns 429 with the reset time."""

from datetime import datetime, timedelta, timezone

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

from app import quotas  # noqa: E402
from app.core.llm import LLMUnavailable  # noqa: E402

PDF = "application/pdf"
QUESTION = "How do I show deployment experience for this job?"


@pytest.fixture(scope="module")
def resume_pdf():
    return make_pdf(RESUME_TEXT)


def analyze(client, token, resume_pdf, jd_text=JD_TEXT):
    return client.post(
        "/analyze",
        files={"resume": ("resume.pdf", resume_pdf, PDF)},
        data={"jd_text": jd_text},
        headers=bearer(token),
    )


def ask(client, token, analysis_id):
    return client.post(
        "/coach", json={"analysis_id": analysis_id, "question": QUESTION}, headers=bearer(token)
    )


def assert_quota_error(response, limit):
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "quota_exceeded" and error["limit"] == limit
    reset = datetime.fromisoformat(error["reset_at"])
    now = datetime.now(timezone.utc)
    assert now < reset <= now + timedelta(days=1)
    assert reset.hour == 0 and reset.minute == 0  # midnight UTC
    assert 0 < int(response.headers["Retry-After"]) <= 86_400


def test_analysis_quota(make_api, resume_pdf):
    client = make_api(quota_analyses_per_day=2)
    token = token_for(client)
    assert analyze(client, token, resume_pdf).status_code == 201
    assert analyze(client, token, resume_pdf).status_code == 201
    assert_quota_error(analyze(client, token, resume_pdf), limit=2)

    usage = client.get("/auth/me", headers=bearer(token)).json()["usage"]
    assert usage["analyses_used"] == 2 and usage["analyses_limit"] == 2


def test_failed_analyses_do_not_use_the_quota(make_api, resume_pdf):
    client = make_api(quota_analyses_per_day=1)
    token = token_for(client)
    assert analyze(client, token, resume_pdf, jd_text="too short").status_code == 422
    assert analyze(client, token, resume_pdf).status_code == 201
    assert client.get("/auth/me", headers=bearer(token)).json()["usage"]["analyses_used"] == 1


def test_quotas_are_per_user(make_api, resume_pdf):
    client = make_api(quota_analyses_per_day=1)
    alice, bob = token_for(client, "alice@example.com"), token_for(client, "bob@example.com")
    assert analyze(client, alice, resume_pdf).status_code == 201
    assert_quota_error(analyze(client, alice, resume_pdf), limit=1)
    assert analyze(client, bob, resume_pdf).status_code == 201


def test_quota_resets_the_next_utc_day(make_api, resume_pdf, monkeypatch):
    client = make_api(quota_analyses_per_day=1)
    token = token_for(client)
    assert analyze(client, token, resume_pdf).status_code == 201
    assert analyze(client, token, resume_pdf).status_code == 429

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    monkeypatch.setattr(quotas, "utc_now", lambda: tomorrow)
    assert analyze(client, token, resume_pdf).status_code == 201


def test_coach_quota_and_outages_do_not_count(make_api, resume_pdf):
    llm = FakeLLM(cite_first_passage, error=LLMUnavailable("HTTP 503"))
    client = make_api(llm, quota_coach_per_day=1)
    token = token_for(client)
    analysis_id = analyze(client, token, resume_pdf).json()["id"]

    assert ask(client, token, analysis_id).status_code == 503  # model down: not counted
    llm.error = None
    assert ask(client, token, analysis_id).status_code == 200
    assert_quota_error(ask(client, token, analysis_id), limit=1)
    usage = client.get("/auth/me", headers=bearer(token)).json()["usage"]
    assert usage["coach_used"] == 1 and usage["analyses_used"] == 1
