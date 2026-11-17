# ResumeFit

Scores a resume against a job description (JD), shows which skills match and which are
missing, and suggests what to change in each weak section. A coach then answers follow-up
questions using only the resume, the JD and a guidance library, with citations. This
repository holds **Phase 1 (Matcher MVP)** and **Phase 2 (RAG coach)** of the PRD.
Accounts, quotas and admin metrics (Phase 3) are planned and not built yet.

> The score is a guide to improving a resume, not a hiring decision, and it can be wrong.

## Status

| Item | State (17 Nov 2026, Windows 11, Python 3.14, torch 2.15 CPU) |
| --- | --- |
| Core matcher: parsing, redaction, skills, scoring, gap report | Built; unit tests pass |
| API, SQL storage, API tests (`tests/test_api.py`) | Built; tests pass (see coverage row) |
| Lint (`ruff check`, `ruff format`) | Clean |
| API with the real model (all-MiniLM-L6-v2) | Smoke-tested by hand: every endpoint and the error paths behave as in the table below |
| Streamlit UI | Loads against the running API and lists saved analyses; the upload flow was not exercised in a browser |
| Dockerfile, GitHub Actions workflow | Written; **not yet run** (Docker is not installed on the dev machine; CI has not run) |
| Score quality with the real embedding model | **Not measured.** Needs your labelled pairs |
| Phase 2 coach core: chunking, retrieval, guardrails, LLM client | Built; unit tests pass |
| Phase 2 storage and API: `chunks`, `coach_messages`, `POST /coach`, `tests/test_api_coach.py` | Built; 115 tests pass in all, 97% line coverage of `app/` |
| Coach with the real embedding model, retrieval-only | Smoke-tested by hand: `/health` reports 24 guidance documents; `/coach` returns cited passages, declines a hiring question, and answers "not in the sources" for an off-topic one. `eval/coach_eval.py` was run; see the results table |
| Coach with a real language model | **Not run.** No provider is configured; answer quality is unmeasured |
| Coach chat in the Streamlit UI | Driven headlessly against the running API: a question is sent, the answer and a "Sources (5)" expander render |

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

## API (no login yet)

| Method and path | Purpose | Main responses |
| --- | --- | --- |
| `GET /health` | Liveness and model version | 200 |
| `POST /jd/extract` | Read a JD file (PDF or DOCX), return its text for preview; stores nothing | 200, 413, 415, 422 |
| `POST /analyze` | Multipart: `resume` (PDF) plus exactly one of `jd_text` or `jd_file`; optional `store_resume_text`, `jd_source` | 201, 413, 415, 422 |
| `GET /analyses` | List analyses, newest first | 200 |
| `GET /analyses/{id}` | Read one analysis | 200, 404 |
| `DELETE /analyses/{id}` | Delete an analysis, its coach messages and its stored passages | 204, 404 |
| `POST /coach` | JSON `{"analysis_id", "question"}`; returns `answer`, `citations` and a `status` | 200, 404, 422, 503 |

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

## The coach (Phase 2)

```
question ─► scope check ─► retrieve top 5 ─► language model ─► groundedness check ─► answer + citations
            (guardrails)   (resume, JD,      (only if one is   (every cited id must
                            guidance)         configured)       have been retrieved)
```

- **Sources.** Three only: the resume (redacted passages), the JD, and 24 short guidance
  documents in `app/data/guidance/`, each with a title, source and version recorded in the
  `guidance_docs` table. The guidance text was drafted with an AI assistant for this
  project; read it, correct it and make it yours before you rely on it.
- **Storage.** Passages and their embeddings are rows in the SQL `chunks` table and search
  is an exact dot product. This replaces the FAISS or Chroma option in the PRD: at this
  size no index is needed, and deleting an analysis with its passages is one transaction.
  `app/store.py` is the only place to change if you add a vector library later.
- **Answer status.** `answered` (generated text, every claim cited), `retrieval_only`
  (passages shown with no generated text: either no model is configured, or the model's
  answer failed the groundedness check and was discarded), `not_in_sources`, `declined`.
- **Guardrails.** Rules decline hiring predictions and obvious attempts to override the
  instructions before any model call. Off-topic questions rely on retrieval finding
  nothing above `RESUMEFIT_COACH_MIN_SIMILARITY`, which is untuned. Text from uploads is
  passed to the model as delimited data and the model has no tools.
- **Language model.** Set by configuration (`RESUMEFIT_LLM_*` in `.env`). The default is
  `none`, which runs the coach in retrieval-only mode. `openai-compatible` works with any
  hosted or local server that offers the chat-completions HTTP format. Calls time out
  after 8 s with at most 2 retries; if the model is down `/coach` returns 503 and the
  matcher keeps working.
- **Not built** (the PRD marks these as cuttable): reranker, conversation memory, and the
  dense versus hybrid (BM25) retrieval experiment. Each question is answered on its own.

**Privacy and safety controls**

- File type is decided by content signature. Encrypted PDFs, `.docm`, legacy `.doc`,
  oversized files, too many pages and zip bombs are rejected with a readable message.
- Uploads are parsed in memory and never written to disk.
- The full resume text is not stored unless `store_resume_text=true`. The JD text is
  stored. Since Phase 2, **redacted resume passages are stored** for the coach (header
  dropped; email, phone, links, name and address lines removed) and are deleted with the
  analysis. Tell your testers this.
- Only redacted passages and a redacted question are sent to a language model. **Third-party
  model provider: none configured.** If you set one, name it here and in the UI.
- Coach questions are stored redacted; logs carry the answer status and counts, never the
  question, answer or passage text.
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

`eval/coach_eval.py` runs the 30-question set in `eval/coach_questions.json` (10 about the
resume, 10 about the JD, 10 out of scope or adversarial) against the fake sample resume and
JD in `eval/samples/`. It prints retrieval hit rate at 5, refusal accuracy and citation
rate, and writes a CSV with each answer beside the same model's answer without retrieval,
for the manual faithfulness check. The question set is a draft: review every question and
gold passage before reporting numbers.

```powershell
python -m eval.coach_eval --out eval/coach_answers.csv
```

| Metric | Target (PRD) | Measured |
| --- | --- | --- |
| Coach retrieval hit rate at 5, answerable questions (draft set, fake sample data) | none set | 55% (11/20), real embedding model, retrieval-only, threshold 0.25, 17 Nov 2026 |
| Coach refusal accuracy, all 30 draft questions | none set | 100% (30/30), same run |
| Coach answers that cite a source passage | ≥ 90% | not measured (needs a language model; retrieval-only answers always show their passages) |
| Coach answers judged faithful (manual) | ≥ 85% | not measured |
| Coach answer p95 latency | < 8 s | not measured (no load test; single retrieval-only `/coach` calls took under 30 ms) |
| Band agreement with human labels, held-out pairs | ≥ 70% | not measured |
| Gain over keyword baseline | ≥ 10 points | not measured |
| `/analyze` p95 latency, 2-page resume | < 3 s | not measured (no load test yet; single requests on a one-page fake resume took 0.6 to 2.4 s on a laptop CPU, the slowest being the first call after startup) |
| Test coverage, core modules | ≥ 80% | 97% of `app/` lines (115 tests, hashing embedder, 17 Nov 2026) |

Fill this table only with numbers you have run.

**Why the hit rate is 55%.** On the eval corpus the resume becomes 4 passages (one per
section) and the JD a single passage, against 24 guidance passages. For the 9 misses the
gold resume or JD passage was usually ranked 6th to 25th, below several longer guidance
passages on the same topic; its similarity was between 0.11 and 0.38, while the top hit
scored 0.30 to 0.82. Lowering `RESUMEFIT_COACH_MIN_SIMILARITY` would not help, because
`top_k` cuts first. The plain off-topic questions scored at most 0.18 against any passage,
and the three hiring questions (up to 0.37) were caught by the scope rules before
retrieval. The likely levers are smaller resume and JD chunks, or a per-source quota in
retrieval; both are untried.

## Known limits

- **No login in Phase 1.** Anyone who can reach the API can list and delete every
  analysis. Run it locally or with test data only until Phase 3 adds accounts and
  per-user isolation.
- The coach's retrieval threshold, prompt and scope rules are untested against a real
  model. The scope rules are keyword patterns and will miss rephrased requests.
- Analyses created before Phase 2 have no stored passages; the coach answers those from
  the guidance library only. Re-run the analysis to fix that.
- Re-ingesting the guidance corpus (after editing a file or changing the embedding model)
  renumbers guidance passages, so citation ids saved with older coach messages go stale.
- Skills outside the curated list are invisible to `S_skill` (the semantic part still
  sees them). Bare "Go" is not matched, to avoid false hits on the verb; "Golang" is.
- Section detection relies on common headings. A resume with unusual headings is scored
  as one block and the report says so. Two-column PDF layouts may extract out of order.
- Name and address redaction are heuristics based on the resume header.
- English text only; scanned PDFs are rejected.
- The retention job runs at startup only; a long-running deployment needs a scheduled run.
- Tables are created directly at startup. Move to Alembic migrations before Phase 3.

## Next steps

1. Decide how to raise retrieval hit rate (smaller resume and JD chunks, or a per-source
   quota) and rerun `python -m eval.coach_eval`; review the draft question set first.
2. Choose a language model, configure it in `.env`, rerun the evaluation, and do the manual
   faithfulness check on `eval/coach_answers.csv`. Fill the results table.
3. Still open from Phase 1: labelled resume and JD pairs, threshold tuning, load test,
   Docker build, CI.
4. Phase 3: accounts, per-user isolation, quotas, feedback, admin metrics.
