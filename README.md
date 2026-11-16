# ResumeFit

Scores a resume against a job description (JD), shows which skills match and which are
missing, and suggests what to change in each weak section. This repository holds
**Phase 1 (Matcher MVP)** of the PRD. The RAG coach (Phase 2) and accounts, quotas and
admin metrics (Phase 3) are planned and not built yet.

> The score is a guide to improving a resume, not a hiring decision, and it can be wrong.

## Status

| Item | State (16 Nov 2026, Windows 11, Python 3.14, torch 2.15 CPU) |
| --- | --- |
| Core matcher: parsing, redaction, skills, scoring, gap report | Built; unit tests pass |
| API, SQL storage, API tests (`tests/test_api.py`) | Built; 57 tests pass, 96% line coverage of `app/` |
| Lint (`ruff check`, `ruff format`) | Clean |
| API with the real model (all-MiniLM-L6-v2) | Smoke-tested by hand: every endpoint and the error paths behave as in the table below |
| Streamlit UI | Loads against the running API and lists saved analyses; the upload flow was not exercised in a browser |
| Dockerfile, GitHub Actions workflow | Written; **not yet run** (Docker is not installed on the dev machine; CI has not run) |
| Score quality with the real embedding model | **Not measured.** Needs your labelled pairs |

Observed on the fake test resume and JD from `tests/helpers.py`, with the real model: the
same JD sent as pasted text, PDF and DOCX gave the same score, and the weak resume scored
in the weak band. These are plumbing checks, not a quality measurement.

## Quick start (Windows PowerShell)

```powershell
cd C:\Users\mukun\Job\Projects\ResumeFIT
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
copy .env.example .env

pytest --cov=app --cov-report=term-missing     # tests use the hashing embedder, no download
ruff check --fix . ; ruff format .              # lint and format once

uvicorn app.main:app --reload                   # API on http://127.0.0.1:8000, docs at /docs
streamlit run ui/streamlit_app.py               # UI, in a second terminal
```

The first API start downloads the embedding model (about 90 MB). To try the API without
the download, set `RESUMEFIT_EMBEDDING_BACKEND=hashing` in `.env`; scores from that
backend are for plumbing checks only.

Docker:

```powershell
docker build -t resumefit .
docker run -p 8000:8000 -v resumefit-data:/data resumefit
```

## API (Phase 1, no login yet)

| Method and path | Purpose | Main responses |
| --- | --- | --- |
| `GET /health` | Liveness and model version | 200 |
| `POST /jd/extract` | Read a JD file (PDF or DOCX), return its text for preview; stores nothing | 200, 413, 415, 422 |
| `POST /analyze` | Multipart: `resume` (PDF) plus exactly one of `jd_text` or `jd_file`; optional `store_resume_text`, `jd_source` | 201, 413, 415, 422 |
| `GET /analyses` | List analyses, newest first | 200 |
| `GET /analyses/{id}` | Read one analysis | 200, 404 |
| `DELETE /analyses/{id}` | Delete an analysis | 204, 404 |

Every error has one shape: `{"error": {"code": "...", "message": "..."}}`.

```powershell
curl.exe -X POST http://127.0.0.1:8000/analyze -F "resume=@resume.pdf" -F "jd_file=@jd.docx"
```

## How it works

```
upload ─► documents.py ─► sections.py ─► redaction.py ─► skills.py ─┐
          type/size/page   skills,        drop header,    curated    ├─► scoring.py ─► gap report ─► SQL
          checks, text     projects, ...  redact contact  list +     │   0-100, band
JD ─────► documents.py ─► split_units (requirement sentences) ──────┘
                                         embeddings.py (MiniLM, CPU)
```

`app/core/` has no FastAPI or database imports; `app/routes.py` is a thin layer over
`app/core/pipeline.py`. The matcher makes no LLM call.

**Score.** `score = 100 × (w1 × S_skill + w2 × S_semantic)`, with `w1 = w2 = 0.5` to start.

- `S_skill`: share of JD skills found on the resume, each weighted by how often the JD
  mentions it. Skills come from `app/data/skills.json` (aliases such as "ML" and
  "machine learning" count as one). A specific skill implies a general one (PostgreSQL
  implies SQL). A phrase in the resume's skills section that the list misses can still
  match by embedding similarity; these are reported separately as `semantic_matches`.
- `S_semantic`: the JD is cleaned and split into requirement sentences; each takes its
  best cosine similarity to any resume chunk; the mean is the score.
- `projects_similarity` and `experience_similarity` repeat this per section and drive the
  suggestions. Bands: strong ≥ 70, partial ≥ 45, otherwise weak.

All weights and thresholds are untuned starting values in `.env`. Raw cosine similarity
from MiniLM is usually well below 1 even for a good match, so expect to move the band
thresholds once you have labelled pairs.

**Privacy and safety controls in this phase**

- File type is decided by content signature. Encrypted PDFs, `.docm`, legacy `.doc`,
  oversized files, too many pages and zip bombs are rejected with a readable message.
- Uploads are parsed in memory and never written to disk.
- Resume text is not stored unless `store_resume_text=true`. The JD text is stored.
- The resume header (name, contact details, address) is excluded from scoring, and email,
  phone and links are redacted from the rest. A test checks that changing only the name
  and contact details leaves the score unchanged.
- Logs are JSON with a request id and metadata only (status, latency, score, band,
  model version, error code). A test checks that no resume or JD text reaches the log.
- Analyses older than 30 days are deleted at startup.

## Evaluation

`eval/evaluate.py` compares the matcher with the keyword-overlap baseline on labelled
pairs (band agreement and Spearman correlation). Copy `eval/labels_template.csv` to
`eval/labels.csv`, put files under `eval/data/` (both are git-ignored), then:

```powershell
python -m eval.evaluate eval/labels.csv --split test
```

| Metric | Target (PRD) | Measured |
| --- | --- | --- |
| Band agreement with human labels, held-out pairs | ≥ 70% | not measured |
| Gain over keyword baseline | ≥ 10 points | not measured |
| `/analyze` p95 latency, 2-page resume | < 3 s | not measured (no load test yet; single requests on a one-page fake resume took 0.6 to 2.4 s on a laptop CPU, the slowest being the first call after startup) |
| Test coverage, core modules | ≥ 80% | 96% of `app/` lines (57 tests, hashing embedder, 16 Nov 2026) |

Fill this table only with numbers you have run.

## Known limits

- **No login in Phase 1.** Anyone who can reach the API can list and delete every
  analysis. Run it locally or with test data only until Phase 3 adds accounts and
  per-user isolation.
- Skills outside the curated list are invisible to `S_skill` (the semantic part still
  sees them). Bare "Go" is not matched, to avoid false hits on the verb; "Golang" is.
- Section detection relies on common headings. A resume with unusual headings is scored
  as one block and the report says so. Two-column PDF layouts may extract out of order.
- Name and address redaction are heuristics based on the resume header.
- English text only; scanned PDFs are rejected.
- The retention job runs at startup only; a long-running deployment needs a scheduled run.
- Tables are created directly at startup. Move to Alembic migrations before Phase 3.

## Next steps

1. Push to a remote and confirm CI is green; install Docker and run `docker build`.
2. Ask classmates for consenting resumes and labels now; labelling takes the longest.
3. Try 10 real resume layouts and record parsing failures.
4. Tune weights and thresholds on the dev split; report the held-out split.
5. Locust load test for p50 and p95, then the embedding optimisation benchmark.
6. Phase 2: guidance corpus, retrieval and the coach.
