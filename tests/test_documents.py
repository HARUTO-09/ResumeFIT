import pytest
from helpers import (
    JD_TEXT,
    LEGACY_DOC,
    RESUME_TEXT,
    add_to_zip,
    make_docx,
    make_pages_pdf,
    make_pdf,
    make_scanned_pdf,
)

from app.core.documents import (
    normalise_text,
    read_jd_file,
    read_resume,
    validate_jd_text,
)
from app.core.params import DocumentLimits
from app.errors import AppError


def expect_error(status: int, code: str, fn, *args):
    with pytest.raises(AppError) as info:
        fn(*args)
    assert info.value.status == status
    assert info.value.code == code
    assert info.value.message  # readable message, never empty
    return info.value


def test_resume_pdf_text_is_extracted(limits):
    text = read_resume(make_pdf(RESUME_TEXT), limits)
    assert "PyTorch" in text and "Education" in text


def test_text_file_renamed_is_rejected_by_content(limits):
    expect_error(415, "unsupported_type", read_resume, b"just some plain text " * 50, limits)
    expect_error(415, "unsupported_type", read_jd_file, b"just some plain text " * 50, limits)


def test_resume_must_be_pdf(limits):
    expect_error(415, "unsupported_type", read_resume, make_docx(RESUME_TEXT), limits)


def test_legacy_doc_rejected(limits):
    err = expect_error(415, "legacy_doc", read_jd_file, LEGACY_DOC, limits)
    assert ".docx" in err.message


def test_encrypted_pdf_rejected(limits):
    data = make_pdf(JD_TEXT, encrypt="secret")
    expect_error(422, "encrypted_pdf", read_jd_file, data, limits)


def test_scanned_pdf_asks_for_paste(limits):
    err = expect_error(422, "too_little_text", read_jd_file, make_scanned_pdf(), limits)
    assert "paste" in err.message.lower()


def test_mostly_non_text_rejected(limits):
    data = make_pdf("\n".join(["#### ---- **** //// ==== ++++ ~~~~ ^^^^ %%%% $$$$"] * 12))
    expect_error(422, "mostly_non_text", read_jd_file, data, limits)


def test_page_limit(limits):
    expect_error(413, "too_many_pages", read_resume, make_pages_pdf(6), limits)
    expect_error(413, "too_many_pages", read_jd_file, make_pages_pdf(11), limits)


def test_size_limit():
    small = DocumentLimits(resume_max_bytes=1000, jd_max_bytes=1000)
    expect_error(413, "file_too_large", read_resume, make_pdf(RESUME_TEXT), small)
    expect_error(413, "file_too_large", read_jd_file, make_pdf(JD_TEXT), small)


def test_empty_file(limits):
    expect_error(422, "empty_file", read_resume, b"", limits)


def test_corrupt_pdf(limits):
    expect_error(422, "unreadable_pdf", read_jd_file, b"%PDF-1.7\nnot really a pdf", limits)


def test_docx_paragraphs_and_table_cells(limits):
    data = make_docx(JD_TEXT, table=[["Location", "Hyderabad"], ["Stipend", "As per norms"]])
    text, source = read_jd_file(data, limits)
    assert source == "docx"
    assert "Integrate models with REST APIs" in text
    assert "Location | Hyderabad" in text and "Stipend | As per norms" in text


def test_macro_enabled_docx_rejected(limits):
    data = add_to_zip(make_docx(JD_TEXT), "word/vbaProject.bin", b"macro")
    expect_error(415, "macros_not_allowed", read_jd_file, data, limits)


def test_zip_that_is_not_word_rejected(limits):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("hello.txt", "hi")
    expect_error(415, "unsupported_type", read_jd_file, buffer.getvalue(), limits)
    expect_error(415, "unsupported_type", read_jd_file, b"PK\x03\x04 broken zip", limits)


def test_oversized_archive_rejected():
    data = add_to_zip(make_docx(JD_TEXT), "word/media/big.bin", b"\x00" * 200_000)
    small = DocumentLimits(docx_max_uncompressed_bytes=100_000)
    expect_error(413, "archive_too_large", read_jd_file, data, small)


def test_jd_text_length_bounds(limits):
    expect_error(422, "jd_too_short", validate_jd_text, "too short", limits)
    expect_error(422, "jd_too_long", validate_jd_text, "word " * 3000, limits)
    assert validate_jd_text(JD_TEXT, limits).startswith("AI Engineer")


def test_normalise_text_fixes_ligatures_and_whitespace():
    assert normalise_text("ﬁne\r\n\r\n\r\n\r\ntext  here\x00") == "fine\n\ntext here"
