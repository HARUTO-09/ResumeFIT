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
| GitHub Actions workflow | Green on the first push to `github.com/HARUTO-09/ResumeFIT` (17 Nov 2026): lint, tests with coverage gate, Docker build on the runner |
| Dockerfile, local Docker build | **Not yet run locally.** Docker Desktop was installed on 17 Nov 2026, but its engine needs Windows' Virtual Machine Platform and WSL 2, which need a restart; the CI runner built the image |
| Score quality with the real embedding model | **Not measured.** Needs your labelled pairs |
| Phase 2 coach core: chunking, retrieval, guardrails, LLM client | Built; unit tests pass |
| Phase 2 storage and API: `chunks`, `coach_messages`, `POST /coach`, `tests/test_api_coach.py` | Built; 118 tests pass in all, 97% line coverage of `app/` |
| Coach with the real embedding model, retrieval-only | Smoke-tested by hand: `/health` reports 24 guidance documents; `/coach` returns cited passages, declines a hiring question, and answers "not in the sources" for an off-topic one. `eval/coach_eval.py` was run; see the results table |
| Load test (`eval/load_test.py`, 2-page fake resume, laptop CPU) | Run on 17 Nov 2026; see the results table |
| Coach with a real language model | Local qwen2.5:3b through Ollama, chosen from three local models (see "Choosing the coach model"). Evaluated and smoke-tested through `/coach`; it misses the PRD citation, faithfulness and latency targets on this laptop |
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
- **Passage sizes and retrieval.** Guidance documents are chunked at about 180 words. The
  resume and the JD are chunked at about 25 words, roughly one bullet or sentence each, so
  a question about one fact matches that line rather than a whole section. Retrieval takes
  the top 5 overall, then keeps a place for the best resume passage and the best JD passage
  if they clear the floor, so the longer guidance passages cannot crowd the student's own
  documents out (`CoachParams` in `app/core/params.py`). Both choices came from the draft
  eval set, which is small and fake; recheck them on real data.
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
  model provider: none.** The configured model (qwen2.5:3b) runs locally in Ollama, so no
  text leaves the machine. If you switch to a hosted provider, name it here and in the UI.
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

`eval/load_test.py` sends `/analyze` and `/coach` requests to a running API with a thread
pool and prints p50 and p95 latency. It needs only `requests`, so Locust is not required.

```powershell
python -m eval.load_test --resume resume.pdf --jd jd.txt --requests 30 --concurrency 4
```

| Metric | Target (PRD) | Measured |
| --- | --- | --- |
| Coach retrieval hit rate at 5, answerable questions (draft set, fake sample data) | none set | 100% (20/20), real embedding model, retrieval-only, threshold 0.25, 17 Nov 2026. It was 55% (11/20) before the passage-size and reserved-slot change described above |
| Coach refusal accuracy, all 30 draft questions | none set | 100% (30/30), same run |
| Coach answers that cite a source passage | ≥ 90% | 85% (17/20), qwen2.5:3b local, coach 0.3.0, 17 Nov 2026. **Below target** |
| Coach answers judged faithful (manual) | ≥ 85% | 76% (13 of the 17 shown answers), same run, checked by hand against the cited passages. **Below target** |
| Coach answer p95 latency | < 8 s | qwen2.5:3b on a laptop CPU, one question at a time: p50 17.9 s, p95 39.8 s. **Above target.** Retrieval-only: p95 34 ms at concurrency 1, 160 ms at concurrency 4 |
| Band agreement with human labels, held-out pairs | ≥ 70% | not measured |
| Gain over keyword baseline | ≥ 10 points | not measured |
| `/analyze` p95 latency, 2-page resume | < 3 s | fake 2-page resume, laptop CPU, 17 Nov 2026: p50 720 ms and p95 767 ms at concurrency 1 (20 requests); p50 1692 ms and p95 2019 ms at concurrency 4 (30 requests). Measured end to end from the client, after one warm-up call |
| Test coverage, core modules | ≥ 80% | 97% of `app/` lines (118 tests, hashing embedder, 17 Nov 2026) |

Fill this table only with numbers you have run.

**How the hit rate went from 55% to 100%.** With 180-word passages the resume was 4 passages
(one per section) and the JD a single passage, against 24 guidance passages. For the 9
misses the gold resume or JD passage ranked 6th to 25th behind longer guidance passages on
the same topic. The retrieval floor was not the lever: `top_k` cuts first, and the plain
off-topic questions scored at most 0.18 against any passage. Chunking the resume and JD at
25 words gave 18/20 on its own, and the reserved slot for the best resume and JD passage
gave 20/20. Twenty questions on one fake resume is a small set, so treat this as a sanity
check rather than a result; the question set itself was reviewed on 17 Nov 2026 and every
gold passage exists in the sources.

### Choosing the coach model (17 Nov 2026)

The constraint was a laptop with an Intel i7-1355U CPU, 16 GB RAM, no usable GPU and no
hosted-model API key, so the candidates were small open models running locally in Ollama.
All runs used the 30-question draft set, the real embedding model and retrieval with the
reserved resume and JD slots. Faithfulness was judged by hand against the cited passages.

| Model, coach version | Cited answers | Faithful, of those shown | p50 / p95 latency |
| --- | --- | --- | --- |
| qwen2.5:3b, 0.2.0 | 19/20 | 15/19 | 16.5 s / 37.0 s |
| llama3.2:3b, 0.2.0 | 18/20 | 11/18 | 18.4 s / 27.9 s |
| qwen2.5:1.5b, 0.3.0 with extra prompt rules | 5/20 | not checked | 6.8 s / 18.0 s |
| qwen2.5:3b, 0.3.0 with extra prompt rules | 15/20 | 10/15 | 18.1 s / 37.0 s |
| **qwen2.5:3b, 0.3.0 (chosen)** | **17/20** | **13/17** | **17.9 s / 39.8 s** |

All five runs kept 100% retrieval hit rate and 100% refusal accuracy. qwen2.5:3b is the
best of these and is the configured model. llama3.2:3b invented facts, such as listing
SQLite as a database the student used. qwen2.5:1.5b mostly failed to cite. Two extra prompt
rules, which said guidance examples are not the student's work and that "not in the
sources" is only for unanswerable questions, made qwen2.5:3b worse, so they were removed.

Coach 0.3.0 tightens the groundedness check. An answer that cites an id outside the R/J/G
scheme, such as `[Q1]`, is rejected. So is an answer that says "not in the sources" while
citing a passage. Both happened with qwen2.5:3b, and both are now shown as passages only.

The remaining failure is the one that matters most for students. The model sometimes turns
a guidance example into a suggestion that the student claim it, including a "120 ms"
figure nobody measured. No local model here meets the PRD's citation, faithfulness or
latency targets. The likely way to meet them is a larger hosted model, which needs an API
key, a cost decision and a privacy note naming the provider. Until then, treat generated
coach answers as drafts and read the cited passages.

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

1. Decide whether to use a hosted model for the coach to meet the citation, faithfulness
   and latency targets; the local qwen2.5:3b misses all three on this laptop.
2. Restart Windows to finish the WSL 2 install, start Docker Desktop, and run
   `docker build -t resumefit .`.
3. Add questions from real, consenting users to `eval/coach_questions.json` and rerun the
   coach evaluation; the current numbers are on 20 questions about one fake resume.
4. Still open from Phase 1: labelled resume and JD pairs and threshold tuning.
5. Phase 3: accounts, per-user isolation, quotas, feedback, admin metrics.
