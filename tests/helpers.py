"""Builders for test files. All personal data here is fake."""

import io
import zipfile

RESUME_TEXT = """Asha Rao
asha.rao@example.com | +91 98765 43210 | linkedin.com/in/asharao
Flat 4, MG Road, Hyderabad 500081

Skills
Languages: Python, SQL, C++
Tools: PyTorch, Git, Containerisation, FastAPI

Projects
Chest X-ray classifier
- Trained a CNN in PyTorch to classify chest X-ray images, reaching 91% accuracy on the test split.
- Built a REST API with FastAPI to serve model predictions and stored results in PostgreSQL.
- Wrote unit tests with pytest and packaged the service in a Docker image.

Experience
Machine Learning Intern, Example Labs
- Cleaned and transformed sensor data with pandas and built data pipelines for model training.
- Monitored model performance weekly and reported drift in input features to the team.

Education
B.Tech Computer Science, Example Institute of Technology, 2027
"""

WEAK_RESUME_TEXT = """Ravi Kumar
ravi.kumar@example.com | 9123456780

Skills
MS Excel, Tally, Communication

Projects
College fest accounts
- Managed the budget and vendor payments for the annual college cultural festival.
- Prepared weekly expense reports for the organising committee in Excel.

Education
B.Com, Example College of Commerce, 2027
"""

JD_TEXT = """AI Engineer

Responsibilities
- Implement machine learning and AI models as per solution designs and convert analytical models into production-ready components for the business.
- Integrate models with REST APIs, applications and data pipelines so that predictions reach downstream systems reliably.
- Deploy models on cloud platforms using Docker and monitor model performance and basic drift indicators.
- Perform data preprocessing and transformation, and carry out functional testing of AI components.

Requirements
- Strong Python and SQL skills, with hands-on experience in PyTorch or scikit-learn.
- Working knowledge of Docker, Git and SQL databases.
- Good communication skills and the ability to maintain clear documentation.
"""


def make_pdf(text: str, encrypt: str | None = None) -> bytes:
    """A simple text PDF: one paragraph per line, long lines wrap."""
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    kwargs = {"encrypt": encrypt} if encrypt else {}
    doc = SimpleDocTemplate(buffer, pagesize=A4, **kwargs)
    style = getSampleStyleSheet()["Normal"]
    flow = []
    for line in text.splitlines():
        flow.append(Paragraph(escape(line), style) if line.strip() else Spacer(1, 10))
    doc.build(flow)
    return buffer.getvalue()


def make_pages_pdf(n_pages: int) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for i in range(n_pages):
        c.drawString(72, 720, f"Page {i + 1} of a long document with some words on it.")
        c.showPage()
    c.save()
    return buffer.getvalue()


def make_scanned_pdf() -> bytes:
    """A PDF with drawings but no text layer, like a scan."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.rect(72, 72, 400, 600, fill=1)
    c.showPage()
    c.save()
    return buffer.getvalue()


def make_docx(text: str, table: list[list[str]] | None = None) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def add_to_zip(data: bytes, name: str, content: bytes) -> bytes:
    """Return a copy of a zip (e.g. a .docx) with one more member."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as src,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr(name, content)
    return out.getvalue()


LEGACY_DOC = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512
