from helpers import RESUME_TEXT

from app.core.redaction import find_name, redact
from app.core.sections import missing_sections, split_sections, split_units


def test_sections_found():
    sections = split_sections(RESUME_TEXT)
    assert sections["header"].startswith("Asha Rao")
    assert "PyTorch" in sections["skills"]
    assert "Chest X-ray" in sections["projects"]
    assert "Intern" in sections["experience"]
    assert "B.Tech" in sections["education"]
    assert missing_sections(sections) == []


def test_missing_section_is_reported_not_fatal():
    text = "Jane Doe\n\nTECHNICAL SKILLS:\nPython, SQL\n\nEducation\nB.Sc Physics"
    sections = split_sections(text)
    assert "Python" in sections["skills"]
    assert missing_sections(sections) == ["projects", "experience"]


def test_no_headings_at_all():
    sections = split_sections("just a paragraph of text\nwith no headings")
    assert missing_sections(sections) == ["skills", "projects", "experience", "education"]


def test_split_units_joins_wrapped_lines_and_splits_bullets():
    text = (
        "Requirements\n"
        "- Strong Python skills and experience building machine learning models for production use\n"
        "in a team setting.\n"
        "- Knowledge of SQL. Experience with Docker is a plus.\n"
    )
    units = split_units(text)
    assert units[0].startswith("Strong Python skills") and units[0].endswith("team setting.")
    assert "Knowledge of SQL." in units
    assert "Experience with Docker is a plus." in units
    assert "Requirements" not in units  # headings are too short to be a unit


def test_redaction_removes_contact_details():
    header = split_sections(RESUME_TEXT)["header"]
    result = redact(RESUME_TEXT, header)
    for secret in ("asha.rao@example.com", "98765 43210", "linkedin.com", "Asha Rao", "MG Road"):
        assert secret not in result.text
    for token in ("[EMAIL]", "[PHONE]", "[URL]", "[NAME]", "[ADDRESS]"):
        assert token in result.text
    assert result.counts["email"] == 1 and result.counts["phone"] == 1
    # content that matters for scoring survives
    assert "PyTorch" in result.text and "91% accuracy" in result.text


def test_redaction_keeps_years_and_scores():
    text = "Interned 2023 - 2024 and scored 9.1 CGPA; 12000 rows processed."
    assert redact(text).text == text


def test_find_name():
    assert find_name("Asha Rao\nasha@example.com") == "Asha Rao"
    assert find_name("asha@example.com\n+91 9999999999") is None
