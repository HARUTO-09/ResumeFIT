"""Per-user isolation (PRD F12): one user can never read, list, rate, ask about or delete
another user's analyses. Covered for every route that takes an analysis or message id."""

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

from app.models import Analysis, new_analysis_id  # noqa: E402

PDF = "application/pdf"


@pytest.fixture()
def two_users(make_api):
    """Alice owns an analysis and a coach answer; Bob owns nothing yet."""
    client = make_api(FakeLLM(cite_first_passage))
    alice = token_for(client, "alice@example.com")
    bob = token_for(client, "bob@example.com")
    created = client.post(
        "/analyze",
        files={"resume": ("resume.pdf", make_pdf(RESUME_TEXT), PDF)},
        data={"jd_text": JD_TEXT},
        headers=bearer(alice),
    )
    assert created.status_code == 201, created.text
    analysis_id = created.json()["id"]
    answer = client.post(
        "/coach",
        json={"analysis_id": analysis_id, "question": "How do I show deployment experience?"},
        headers=bearer(alice),
    )
    assert answer.status_code == 200, answer.text
    return client, alice, bob, analysis_id, answer.json()["id"]


def assert_not_found(response):
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_list_shows_only_your_own(two_users):
    client, alice, bob, analysis_id, _ = two_users
    assert [a["id"] for a in client.get("/analyses", headers=bearer(alice)).json()] == [analysis_id]
    assert client.get("/analyses", headers=bearer(bob)).json() == []


def test_read_another_users_analysis_is_not_found(two_users):
    client, alice, bob, analysis_id, _ = two_users
    assert_not_found(client.get(f"/analyses/{analysis_id}", headers=bearer(bob)))
    assert client.get(f"/analyses/{analysis_id}", headers=bearer(alice)).status_code == 200


def test_delete_another_users_analysis_is_not_found_and_changes_nothing(two_users):
    client, alice, bob, analysis_id, _ = two_users
    assert_not_found(client.delete(f"/analyses/{analysis_id}", headers=bearer(bob)))
    assert client.get(f"/analyses/{analysis_id}", headers=bearer(alice)).status_code == 200


def test_coach_on_another_users_analysis_is_not_found(two_users):
    client, alice, bob, analysis_id, _ = two_users
    response = client.post(
        "/coach",
        json={"analysis_id": analysis_id, "question": "What does my resume say about Docker?"},
        headers=bearer(bob),
    )
    assert_not_found(response)


@pytest.mark.parametrize("target", ["analysis", "coach_message"])
def test_rating_another_users_items_is_not_found(two_users, target):
    client, alice, bob, analysis_id, message_id = two_users
    target_id = analysis_id if target == "analysis" else message_id
    body = {"target_type": target, "target_id": target_id, "rating": 1}
    assert_not_found(client.post("/feedback", json=body, headers=bearer(bob)))
    assert client.post("/feedback", json=body, headers=bearer(alice)).status_code == 201


def test_bobs_own_work_stays_separate(two_users):
    client, alice, bob, analysis_id, _ = two_users
    created = client.post(
        "/analyze",
        files={"resume": ("resume.pdf", make_pdf(RESUME_TEXT), PDF)},
        data={"jd_text": JD_TEXT},
        headers=bearer(bob),
    )
    bob_id = created.json()["id"]
    assert [a["id"] for a in client.get("/analyses", headers=bearer(bob)).json()] == [bob_id]
    assert [a["id"] for a in client.get("/analyses", headers=bearer(alice)).json()] == [analysis_id]
    assert_not_found(client.get(f"/analyses/{bob_id}", headers=bearer(alice)))


def test_analyses_from_before_accounts_are_visible_to_nobody(two_users):
    """Rows made in Phases 1 and 2 have no owner; they must not leak to any account."""
    client, alice, bob, _, _ = two_users
    legacy_id = new_analysis_id()
    with client.app.state.session_factory() as session:
        session.add(
            Analysis(
                id=legacy_id,
                user_id=None,
                jd_text=JD_TEXT,
                jd_source="text",
                score=50,
                band="partial",
                components={},
                matched_skills=[],
                missing_skills=[],
                report={},
                model_version="matcher-legacy",
                latency_ms=1,
            )
        )
        session.commit()
    for token in (alice, bob):
        assert_not_found(client.get(f"/analyses/{legacy_id}", headers=bearer(token)))
        assert legacy_id not in [
            a["id"] for a in client.get("/analyses", headers=bearer(token)).json()
        ]
