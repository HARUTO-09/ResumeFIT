import logging
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from helpers import (  # noqa: E402
    AUTH_SETTINGS,
    JD_TEXT,
    LEGACY_DOC,
    RESUME_TEXT,
    make_docx,
    make_pages_pdf,
    make_pdf,
    make_scanned_pdf,
    sign_in,
)

from app.config import Settings  # noqa: E402
from app.db import purge_expired  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Analysis, utcnow  # noqa: E402

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def client(tmp_path, embedder):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        embedding_backend="hashing",
        **AUTH_SETTINGS,
    )
    with TestClient(create_app(settings, embedder=embedder)) as c:
        sign_in(c)  # Phase 3: every endpoint but /health needs a signed-in user
        yield c


@pytest.fixture(scope="module")
def resume_pdf():
    return make_pdf(RESUME_TEXT)


def post_analysis(client, resume_pdf, **data):
    data = data or {"jd_text": JD_TEXT}
    return client.post("/analyze", files={"resume": ("resume.pdf", resume_pdf, PDF)}, data=data)


def assert_error(response, status: int, code: str | None = None):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) >= {"code", "message"} and error["message"]
    if code:
        assert error["code"] == code


# ---- happy paths -----------------------------------------------------------------
def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["model_version"].startswith("matcher-")


def test_analyze_with_pasted_jd(client, resume_pdf):
    response = post_analysis(client, resume_pdf)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"].startswith("an_")
    assert 0 <= body["score"] <= 100 and body["band"] in ("strong", "partial", "weak")
    assert "skill_overlap" in body["components"]
    assert "python" in body["matched_skills"]
    assert all({"skill", "jd_mentions"} <= set(m) for m in body["missing_skills"])
    assert body["jd_source"] == "text"
    assert body["resume_text_stored"] is False
    assert response.headers["X-Request-ID"]


def test_same_jd_as_text_pdf_and_docx_scores_within_two_points(client, resume_pdf):
    scores = [post_analysis(client, resume_pdf).json()["score"]]
    for name, data, mime, source in (
        ("jd.pdf", make_pdf(JD_TEXT), PDF, "pdf"),
        ("jd.docx", make_docx(JD_TEXT), DOCX, "docx"),
    ):
        response = client.post(
            "/analyze",
            files={"resume": ("resume.pdf", resume_pdf, PDF), "jd_file": (name, data, mime)},
        )
        assert response.status_code == 201, response.text
        assert response.json()["jd_source"] == source
        scores.append(response.json()["score"])
    assert max(scores) - min(scores) <= 2, scores


def test_jd_extract_preview_then_analyze_with_edited_text(client, resume_pdf):
    docx = make_docx(JD_TEXT, table=[["Location", "Hyderabad"]])
    preview = client.post("/jd/extract", files={"file": ("jd.docx", docx, DOCX)})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["source"] == "docx" and "Location | Hyderabad" in body["text"]
    assert body["char_count"] == len(body["text"]) and body["warning"] is None
    assert client.get("/analyses").json() == []  # extract stores nothing

    edited = body["text"].replace("Location | Hyderabad", "")
    response = post_analysis(client, resume_pdf, jd_text=edited, jd_source="docx")
    assert response.status_code == 201 and response.json()["jd_source"] == "docx"


# ---- persistence, read, list, delete (F7, F8) ---------------------------------------
def test_read_list_delete(client, resume_pdf):
    first = post_analysis(client, resume_pdf).json()["id"]
    second = post_analysis(client, resume_pdf).json()["id"]

    listing = client.get("/analyses").json()
    assert [row["id"] for row in listing] == [second, first] or {row["id"] for row in listing} == {
        first,
        second,
    }
    assert client.get(f"/analyses/{first}").json()["id"] == first

    assert client.delete(f"/analyses/{first}").status_code == 204
    assert_error(client.get(f"/analyses/{first}"), 404, "not_found")
    assert_error(client.delete(f"/analyses/{first}"), 404, "not_found")
    assert [row["id"] for row in client.get("/analyses").json()] == [second]


def test_resume_text_is_stored_only_on_opt_in(client, resume_pdf):
    default_id = post_analysis(client, resume_pdf).json()["id"]
    opted = post_analysis(client, resume_pdf, jd_text=JD_TEXT, store_resume_text="true").json()
    assert opted["resume_text_stored"] is True
    with client.app.state.session_factory() as session:
        assert session.get(Analysis, default_id).resume_text is None
        assert "PyTorch" in session.get(Analysis, opted["id"]).resume_text


def test_retention_job_removes_old_analyses(client, resume_pdf):
    old_id = post_analysis(client, resume_pdf).json()["id"]
    new_id = post_analysis(client, resume_pdf).json()["id"]
    with client.app.state.session_factory() as session:
        session.get(Analysis, old_id).created_at = utcnow() - timedelta(days=31)
        session.commit()
        assert purge_expired(session, retention_days=30) == 1
    assert client.get(f"/analyses/{old_id}").status_code == 404
    assert client.get(f"/analyses/{new_id}").status_code == 200


# ---- validation and error paths -----------------------------------------------------
def test_jd_must_be_exactly_one_of_text_or_file(client, resume_pdf):
    files = {"resume": ("resume.pdf", resume_pdf, PDF)}
    assert_error(client.post("/analyze", files=files), 422, "jd_input")
    both = {**files, "jd_file": ("jd.pdf", make_pdf(JD_TEXT), PDF)}
    assert_error(client.post("/analyze", files=both, data={"jd_text": JD_TEXT}), 422, "jd_input")


def test_missing_resume_uses_the_error_shape(client):
    assert_error(client.post("/analyze", data={"jd_text": JD_TEXT}), 422, "invalid_input")


def test_jd_length_limits(client, resume_pdf):
    assert_error(post_analysis(client, resume_pdf, jd_text="too short"), 422, "jd_too_short")
    assert_error(post_analysis(client, resume_pdf, jd_text="word " * 3000), 422, "jd_too_long")


def test_bad_jd_source(client, resume_pdf):
    response = post_analysis(client, resume_pdf, jd_text=JD_TEXT, jd_source="fax")
    assert_error(response, 422, "jd_source")


def test_unsupported_and_unsafe_files(client, resume_pdf):
    text_as_pdf = {"resume": ("resume.pdf", b"plain text " * 100, PDF)}
    assert_error(
        client.post("/analyze", files=text_as_pdf, data={"jd_text": JD_TEXT}),
        415,
        "unsupported_type",
    )

    def with_jd(name, data):
        files = {"resume": ("resume.pdf", resume_pdf, PDF), "jd_file": (name, data, DOCX)}
        return client.post("/analyze", files=files)

    assert_error(with_jd("jd.docx", b"plain text renamed " * 50), 415, "unsupported_type")
    assert_error(with_jd("jd.doc", LEGACY_DOC), 415, "legacy_doc")
    assert_error(with_jd("jd.pdf", make_pdf(JD_TEXT, encrypt="pw")), 422, "encrypted_pdf")
    assert_error(with_jd("jd.pdf", make_scanned_pdf()), 422, "too_little_text")


def test_too_large_and_too_long(client, resume_pdf):
    big = b"%PDF-1.7\n" + b"0" * (5 * 1024 * 1024 + 10)
    files = {"resume": ("resume.pdf", big, PDF)}
    assert_error(
        client.post("/analyze", files=files, data={"jd_text": JD_TEXT}), 413, "file_too_large"
    )
    files = {"resume": ("resume.pdf", make_pages_pdf(6), PDF)}
    assert_error(
        client.post("/analyze", files=files, data={"jd_text": JD_TEXT}), 413, "too_many_pages"
    )
    assert_error(
        client.post("/jd/extract", files={"file": ("jd.pdf", make_pages_pdf(11), PDF)}),
        413,
        "too_many_pages",
    )


def test_unknown_route_and_method_use_the_error_shape(client):
    assert_error(client.get("/nope"), 404, "not_found")
    assert_error(client.put("/analyses"), 405, "method_not_allowed")


# ---- privacy -------------------------------------------------------------------------
def test_logs_carry_request_id_and_no_personal_data(client, resume_pdf, caplog):
    logger = logging.getLogger("resumefit")
    logger.propagate = True  # let pytest capture it
    try:
        with caplog.at_level(logging.INFO, logger="resumefit"):
            post_analysis(client, resume_pdf)
    finally:
        logger.propagate = False
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert '"request_id"' in logged and '"score"' in logged
    for secret in ("Asha", "asha.rao@example.com", "98765", "PyTorch", "solution designs"):
        assert secret not in logged
