"""Accounts on Firebase (PRD F11): consent at registration, tokens on every protected
route, admin needs a verified email, and account deletion."""

import logging
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")

from firebase_fake import OTHER_PRIVATE_KEY, firebase_token, uid_for  # noqa: E402
from helpers import (  # noqa: E402
    AUTH_SETTINGS,
    JD_TEXT,
    RESUME_TEXT,
    FakeLLM,
    bearer,
    cite_first_passage,
    make_pdf,
    register,
    token_for,
)
from sqlalchemy import func, select  # noqa: E402

from app.models import (  # noqa: E402
    Analysis,
    Chunk,
    CoachMessage,
    Feedback,
    ScoreEvent,
    Usage,
    User,
)

PDF = "application/pdf"

# Every endpoint that needs a registered user, with a minimal request for each.
PROTECTED = [
    ("GET", "/auth/me", None),
    ("DELETE", "/auth/me", None),
    ("POST", "/jd/extract", {"files": {"file": ("jd.pdf", b"%PDF-1.7", PDF)}}),
    ("POST", "/analyze", {"data": {"jd_text": JD_TEXT}}),
    ("GET", "/analyses", None),
    ("GET", "/analyses/an_000000000000", None),
    ("DELETE", "/analyses/an_000000000000", None),
    ("POST", "/coach", {"json": {"analysis_id": "an_000000000000", "question": "Hello there"}}),
    (
        "POST",
        "/feedback",
        {"json": {"target_type": "analysis", "target_id": "an_000000000000", "rating": 5}},
    ),
    ("GET", "/admin/metrics", None),
]


def call(client, method, path, kwargs=None, headers=None):
    return client.request(method, path, headers=headers, **(kwargs or {}))


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code and error["message"]


def count(client, model, *where) -> int:
    with client.app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture(scope="module")
def resume_pdf():
    return make_pdf(RESUME_TEXT)


def new_analysis(client, token, resume_pdf) -> str:
    response = client.post(
        "/analyze",
        files={"resume": ("resume.pdf", resume_pdf, PDF)},
        data={"jd_text": JD_TEXT},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---- public config -----------------------------------------------------------------------
def test_auth_config_is_public(make_api):
    body = make_api().get("/auth/config").json()
    assert body == {
        "project_id": AUTH_SETTINGS["firebase_project_id"],
        "api_key": "test-web-api-key",
        "auth_domain": f"{AUTH_SETTINGS['firebase_project_id']}.firebaseapp.com",
    }


# ---- registration with consent ------------------------------------------------------------
def test_register_creates_the_account_once(make_api):
    client = make_api()
    token = firebase_token("New.Student@Example.com", provider="google.com")
    first = register(client, token)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["email"] == "new.student@example.com"
    assert body["id"].startswith("us_") and body["consent_at"]
    assert body["sign_in_provider"] == "google.com" and body["is_admin"] is False

    again = register(client, token)
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert count(client, User) == 1
    with client.app.state.session_factory() as session:
        assert session.scalars(select(User.firebase_uid)).one() == uid_for(
            "new.student@example.com"
        )


def test_registration_fails_without_consent(make_api):
    client = make_api()
    assert_error(register(client, firebase_token(), consent=False), 422, "consent_required")
    assert count(client, User) == 0


def test_signed_in_but_unregistered_users_are_asked_to_consent(make_api):
    client = make_api()
    response = client.get("/auth/me", headers=bearer(firebase_token()))
    assert_error(response, 403, "registration_required")


def test_me_shows_the_account_and_usage(make_api):
    client = make_api()
    token = token_for(client)
    me = client.get("/auth/me", headers=bearer(token))
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "student@example.com"
    assert me.json()["usage"]["analyses_used"] == 0
    assert me.json()["usage"]["analyses_limit"] == AUTH_SETTINGS["quota_analyses_per_day"]


def test_email_change_in_firebase_is_picked_up(make_api):
    client = make_api()
    uid = uid_for("old@example.com")
    token_for(client, "old@example.com")
    me = client.get("/auth/me", headers=bearer(firebase_token("new@example.com", uid=uid)))
    assert me.json()["email"] == "new@example.com"
    assert count(client, User) == 1


# ---- every protected route needs a valid token -------------------------------------------------
@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED)
def test_protected_routes_reject_requests_without_a_token(make_api, method, path, kwargs):
    response = call(make_api(), method, path, kwargs)
    assert_error(response, 401, "not_authenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED)
def test_protected_routes_reject_bad_tokens(make_api, method, path, kwargs):
    client = make_api()
    token_for(client)
    bad = [
        "garbage",
        firebase_token(lifetime=timedelta(hours=-1)),  # expired
        firebase_token(key=OTHER_PRIVATE_KEY),  # not signed by Firebase
        firebase_token(project_id="another-project"),  # another Firebase project
    ]
    for token in bad:
        assert_error(call(client, method, path, kwargs, bearer(token)), 401, "invalid_token")
    assert_error(
        call(client, method, path, kwargs, {"Authorization": "Basic abc"}), 401, "not_authenticated"
    )


def test_health_and_config_stay_public(make_api):
    client = make_api()
    assert client.get("/health").status_code == 200
    assert client.get("/auth/config").status_code == 200


def test_server_without_firebase_settings_says_so(make_api):
    client = make_api(firebase_project_id="")
    assert_error(
        client.get("/auth/me", headers=bearer(firebase_token())), 503, "auth_not_configured"
    )
    assert client.get("/health").status_code == 200


# ---- admin needs a verified email ----------------------------------------------------------------
def test_admin_needs_a_verified_email(make_api):
    client = make_api(admin_emails="admin@example.com")
    unverified = token_for(client, "admin@example.com", email_verified=False)
    assert client.get("/auth/me", headers=bearer(unverified)).json()["is_admin"] is False
    assert_error(client.get("/admin/metrics", headers=bearer(unverified)), 403, "forbidden")

    verified = firebase_token("admin@example.com", email_verified=True)
    assert client.get("/auth/me", headers=bearer(verified)).json()["is_admin"] is True
    assert client.get("/admin/metrics", headers=bearer(verified)).status_code == 200


# ---- account deletion ----------------------------------------------------------------------------
def test_delete_needs_a_recent_sign_in(make_api):
    client = make_api()
    token_for(client)
    stale = firebase_token(auth_age=timedelta(hours=2))
    assert_error(client.delete("/auth/me", headers=bearer(stale)), 401, "recent_login_required")
    assert count(client, User) == 1


def test_delete_account_removes_everything_of_that_user_only(make_api, resume_pdf):
    client = make_api(FakeLLM(cite_first_passage))
    alice = token_for(client, "alice@example.com")
    bob = token_for(client, "bob@example.com")
    alice_analysis = new_analysis(client, alice, resume_pdf)
    bob_analysis = new_analysis(client, bob, resume_pdf)
    for token, analysis_id in ((alice, alice_analysis), (bob, bob_analysis)):
        answer = client.post(
            "/coach",
            json={"analysis_id": analysis_id, "question": "How do I show deployment?"},
            headers=bearer(token),
        )
        assert answer.status_code == 200, answer.text
        rated = client.post(
            "/feedback",
            json={"target_type": "coach_message", "target_id": answer.json()["id"], "rating": 4},
            headers=bearer(token),
        )
        assert rated.status_code == 201, rated.text
    with client.app.state.session_factory() as session:
        alice_id = session.scalars(select(User.id).where(User.email == "alice@example.com")).one()
    events_before = count(client, ScoreEvent)

    assert client.delete("/auth/me", headers=bearer(alice)).status_code == 204

    assert count(client, User, User.id == alice_id) == 0
    assert count(client, Analysis, Analysis.user_id == alice_id) == 0
    assert count(client, Chunk, Chunk.analysis_id == alice_analysis) == 0
    assert count(client, CoachMessage, CoachMessage.user_id == alice_id) == 0
    assert count(client, Feedback, Feedback.user_id == alice_id) == 0
    assert count(client, Usage, Usage.user_id == alice_id) == 0
    # her Firebase token is still valid, but there is no account behind it any more
    assert_error(client.get("/auth/me", headers=bearer(alice)), 403, "registration_required")

    # Bob is untouched; anonymous score events stay for the drift check
    assert client.get(f"/analyses/{bob_analysis}", headers=bearer(bob)).status_code == 200
    assert count(client, Feedback) == 1
    assert count(client, ScoreEvent) == events_before


def test_auth_logs_carry_no_email(make_api, caplog):
    client = make_api()
    logger = logging.getLogger("resumefit")
    logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger="resumefit"):
            token_for(client, "private.person@example.com")
            client.get("/auth/me", headers=bearer(firebase_token("private.person@example.com")))
    finally:
        logger.propagate = False
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert '"path": "/auth/register"' in logged
    assert "private.person" not in logged and "private-person" not in logged
