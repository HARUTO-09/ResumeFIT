"""Read uploaded files safely and turn them into text.

Rules (PRD F1, F2, F16 and the "malformed or malicious files" risk):
- the file type is decided by its content signature, never its extension;
- encrypted PDFs, macro-enabled Word files and legacy .doc are rejected;
- size, page count and decompressed size are capped;
- files are parsed in memory and never written to disk.
"""

import io
import re
import unicodedata
import zipfile

from app.core.params import DocumentLimits
from app.errors import AppError

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK"
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # legacy .doc / .xls / .ppt

PASTE_HINT = "Please paste the text instead."


# --------------------------------------------------------------------------
# Type detection and limits
# --------------------------------------------------------------------------
def check_size(data: bytes, max_bytes: int, what: str) -> None:
    if len(data) > max_bytes:
        raise AppError(
            413,
            "file_too_large",
            f"The {what} file is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    if not data:
        raise AppError(422, "empty_file", f"The {what} file is empty.")


def sniff_type(data: bytes, limits: DocumentLimits) -> str:
    """Return "pdf" or "docx" from the file's content, or raise 415."""
    if PDF_MAGIC in data[:1024]:
        return "pdf"
    if data.startswith(OLE_MAGIC):
        raise AppError(
            415,
            "legacy_doc",
            "Legacy .doc files are not supported. Save the file as .docx or PDF and try again.",
        )
    if data.startswith(ZIP_MAGIC):
        _check_docx_archive(data, limits)
        return "docx"
    raise AppError(
        415,
        "unsupported_type",
        "Unsupported file type. Upload a PDF or a .docx file.",
    )


def _check_docx_archive(data: bytes, limits: DocumentLimits) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            names = {i.filename for i in infos}
            total = sum(i.file_size for i in infos)
            content_types = b""
            if total <= limits.docx_max_uncompressed_bytes and "[Content_Types].xml" in names:
                content_types = zf.read("[Content_Types].xml")
    except zipfile.BadZipFile:
        raise AppError(415, "unsupported_type", "The file is not a valid .docx document.") from None

    if total > limits.docx_max_uncompressed_bytes:
        raise AppError(
            413,
            "archive_too_large",
            "The .docx file expands to more data than is allowed.",
        )
    if "word/document.xml" not in names:
        raise AppError(
            415, "unsupported_type", "The file is a zip archive but not a Word document."
        )
    if any(n.lower().endswith("vbaproject.bin") for n in names) or b"macroEnabled" in content_types:
        raise AppError(
            415,
            "macros_not_allowed",
            "Macro-enabled Word files (.docm) are not accepted. Save as .docx without macros.",
        )


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
def normalise_text(text: str) -> str:
    """Unicode-normalise (fixes ligatures), drop control chars, tidy whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(data: bytes, max_pages: int, what: str) -> str:
    import pdfplumber
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AppError(
                422,
                "encrypted_pdf",
                f"The {what} PDF is password-protected. Remove the password and try again.",
            )
        n_pages = len(reader.pages)
    except AppError:
        raise
    except Exception:
        raise AppError(422, "unreadable_pdf", f"The {what} PDF could not be read.") from None

    if n_pages > max_pages:
        raise AppError(
            413,
            "too_many_pages",
            f"The {what} PDF has {n_pages} pages; the limit is {max_pages}.",
        )

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        raise AppError(422, "unreadable_pdf", f"The {what} PDF could not be read.") from None
    return normalise_text("\n".join(pages))


def extract_docx(data: bytes, max_pages: int, what: str) -> str:
    """Paragraphs and table cells, in document order."""
    import docx
    from docx.table import Table

    pages = _docx_page_count(data)
    if pages is not None and pages > max_pages:
        raise AppError(
            413,
            "too_many_pages",
            f"The {what} document has {pages} pages; the limit is {max_pages}.",
        )
    try:
        document = docx.Document(io.BytesIO(data))
        lines: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                for row in block.rows:
                    cells: list[str] = []
                    for cell in row.cells:
                        text = cell.text.strip()
                        # merged cells repeat; keep each value once per row
                        if text and (not cells or cells[-1] != text):
                            cells.append(text)
                    if cells:
                        lines.append(" | ".join(cells))
            else:
                lines.append(block.text)
    except Exception:
        raise AppError(422, "unreadable_docx", f"The {what} document could not be read.") from None
    return normalise_text("\n".join(lines))


def _docx_page_count(data: bytes) -> int | None:
    """Word stores a page count in docProps/app.xml; it may be absent."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "docProps/app.xml" not in zf.namelist():
                return None
            match = re.search(rb"<Pages>(\d+)</Pages>", zf.read("docProps/app.xml"))
            return int(match.group(1)) if match else None
    except Exception:
        return None


def check_text_quality(text: str, min_chars: int, limits: DocumentLimits, what: str) -> None:
    """Reject scanned or image-only files, which extract to little or no text."""
    compact = re.sub(r"\s", "", text)
    if len(text) < min_chars:
        raise AppError(
            422,
            "too_little_text",
            f"Only {len(text)} characters of text could be read from the {what} "
            f"(minimum {min_chars}). It may be a scanned or image-only file. {PASTE_HINT}",
        )
    ratio = sum(ch.isalnum() for ch in compact) / max(len(compact), 1)
    if ratio < limits.min_text_ratio:
        raise AppError(
            422,
            "mostly_non_text",
            f"The {what} is mostly non-text content. {PASTE_HINT}",
        )


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------
def read_resume(data: bytes, limits: DocumentLimits) -> str:
    """F1: PDF only, size and page limits, text must be extractable."""
    check_size(data, limits.resume_max_bytes, "resume")
    kind = sniff_type(data, limits)
    if kind != "pdf":
        raise AppError(415, "unsupported_type", "The resume must be a PDF file.")
    text = extract_pdf(data, limits.resume_max_pages, "resume")
    check_text_quality(text, limits.resume_min_chars, limits, "resume")
    return text


def read_jd_file(data: bytes, limits: DocumentLimits) -> tuple[str, str]:
    """F2/F16: PDF or DOCX. Returns (text, source) where source is "pdf" or "docx"."""
    check_size(data, limits.jd_max_bytes, "job description")
    kind = sniff_type(data, limits)
    if kind == "pdf":
        text = extract_pdf(data, limits.jd_max_pages, "job description")
    else:
        text = extract_docx(data, limits.jd_max_pages, "job description")
    check_text_quality(text, limits.jd_min_chars, limits, "job description")
    return text, kind


def validate_jd_text(text: str, limits: DocumentLimits) -> str:
    """F2: the final JD text must be 200 to 10,000 characters."""
    text = normalise_text(text)
    if len(text) < limits.jd_min_chars:
        raise AppError(
            422,
            "jd_too_short",
            f"The job description has {len(text)} characters; "
            f"at least {limits.jd_min_chars} are needed.",
        )
    if len(text) > limits.jd_max_chars:
        raise AppError(
            422,
            "jd_too_long",
            f"The job description has {len(text)} characters; the limit is {limits.jd_max_chars}.",
        )
    return text
