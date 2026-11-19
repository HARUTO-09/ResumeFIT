# ResumeFit

**Score a resume against a job description, see exactly which skills are missing, and ask
a coach what to change, with every answer citing its source.**

**Live:** [resumefit-web.vercel.app](https://resumefit-web.vercel.app) · API docs:
[resumefit-api-x93n.onrender.com/docs](https://resumefit-api-x93n.onrender.com/docs)

ResumeFit is a full-stack app: a FastAPI backend with an embedding-based matcher, a
retrieval-augmented (RAG) coach with a groundedness guardrail, Firebase sign-in, per-user
data isolation, daily quotas, ratings, an admin metrics page with score-drift detection,
and a plain HTML/CSS/JavaScript front end. It runs entirely on free tiers: Vercel, Render,
Neon PostgreSQL, Firebase Authentication and the Gemini API.

> The score is a guide to improving a resume, not a hiring decision, and it can be wrong.

## Results at a glance

Every number below was measured on this project; the conditions are in the right-hand
column and in [Evaluation](#evaluation). Test data is fake (`tests/helpers.py`,
`eval/samples/`).

| What | Result | Conditions |
| --- | --- | --- |
| Automated tests | **229 tests, 96% line coverage** of `app/` | `pytest --cov=app`, 19 Nov 2026; CI gate is 80% |
| End-to-end checks on the live deployment | **21/21** browser checks and **21/21** API checks passed | Playwright (headless Edge) against the live site, and a scripted API flow against the live API, with throwaway test accounts deleted afterwards, 17 Nov 2026 |
| `/analyze` latency, 2-page resume | **p50 488 ms, p95 642 ms** one request at a time (20 requests); **p50 1113 ms, p95 1549 ms** at concurrency 4 (30 requests); **0 failures in 52 analyses** | `eval/load_test.py` on a laptop (Intel i7-1355U), client and server on the same machine, ONNX backend, 19 Nov 2026 |
| Embedding runtime switch (PyTorch to ONNX Runtime) | **3.4× faster** per analysis (96 ms vs 326 ms), **identical outputs**, API peak memory **324 MB** | Same model, both runtimes, same laptop; memory is the Windows working set through the full account flow, under the 512 MB free host. Cosine 1.000000 between the two runtimes' vectors on 79 texts; 6/6 resume and JD pairs gave identical reports; the coach retrieved the same passages for 30/30 questions |
| Coach retrieval hit rate at 5 | **100% (20/20)**, up from **55% (11/20)** | 30-question draft set (20 answerable), after moving resume and JD passages from about 180 to about 25 words and reserving a slot for each |
| Coach refusals | **100% (30/30)** correct | Same set: answerable questions answered; out-of-scope and adversarial questions declined |
| Coach answers that cite a retrieved source | **20/20** with Gemini, up from **17/20** with a local 3B model | Same set, coach 0.3.0 |
| Coach p95 latency | **8.2 s** (8.4 s on a second run), down from **39.8 s** | `gemini-3.5-flash-lite` (hosted, free tier) vs qwen2.5:3b on the laptop CPU |
| Skills knowledge base | **103 skills, 239 aliases, 28 implication rules** | `app/data/skills.json` (for example, PostgreSQL implies SQL) |
| Coach guide library | **24 documents** | `app/data/guidance/` |
| Hosting cost | **$0 a month** | Free plans of Vercel, Render, Neon, Firebase and the Gemini API |

Not measured yet: agreement with human-labelled match bands, and the gain over a keyword
baseline. Both need labelled resume and job pairs (see [Next steps](#next-steps)).

## Features

- **Matcher.** Upload a resume PDF and paste a job description, or upload it as PDF or
  Word. You get a 0–100 score and a band (strong, partial, weak), the matched and missing
  skills ranked by how often the job asks for them, a "start here" gap, and suggestions
  for weak resume sections. The report downloads as Markdown.
- **Coach.** Ask follow-up questions about an analysis. Answers come only from your
  resume, the job description and a 24-document guide library, with citations such as
  `[R3]` or `[J10]`. An answer that cites anything it did not retrieve is never shown.
- **Accounts.** Google or email sign-in through Firebase, a consent step that shows what
  is stored, a history with a score trend, and full account deletion.
- **SaaS basics.** Per-user isolation, daily quotas, 1–5 ratings on analyses and coach
  answers, and an admin page with latency percentiles, error rates, quota hits, usage,
  the score distribution, rating trends and drift flags.
- **Privacy by design.** Uploads are parsed in memory and never saved. Names and contact
  details are removed before anything is stored or sent to the language model. Logs
  carry no resume or job text, and tests check this.

## Architecture

```
 Browser ──► Vercel (static site: web/, plain HTML/CSS/JS)
    │
    ├──► Firebase Authentication (Google or email sign-in, ID tokens)
    │
    └──► Render (Docker, FastAPI) ── verifies Firebase tokens (PyJWT, RS256)
              │
              ├── matcher: parsing ─► redaction ─► skills ─► embeddings (ONNX) ─► score
              ├── coach:   retrieval ─► Gemini API ─► groundedness check
              └── Neon PostgreSQL: users, analyses, passages + vectors, ratings, metrics
```

| Layer | Technology |
| --- | --- |
| API | Python, FastAPI, Pydantic, SQLAlchemy 2, Uvicorn |
| Matching | all-MiniLM-L6-v2 embeddings through ONNX Runtime, a curated skills graph, scikit-learn, SciPy |
| Documents | pdfplumber, pypdf, python-docx, with checks on file type, size, page count and zip bombs |
| Coach | Retrieval over SQL-stored vectors, Gemini API through an OpenAI-compatible client, rule-based guardrails |
| Auth | Firebase Authentication, PyJWT token verification against Google's public keys |
| Data | PostgreSQL on Neon (psycopg 3) in production, SQLite locally and in tests |
| Front end | Plain HTML, CSS and JavaScript (no framework, no build step), Firebase JS SDK |
| Quality | pytest (229 tests), ruff, pre-commit, GitHub Actions (lint, tests, Docker build) |
| Hosting | Vercel (site), Render (API, Docker), Neon (database), all free plans |

`app/core/` holds the matching, coach and security logic with no FastAPI or database
imports; `app/routes.py`, `app/auth.py` and `app/admin.py` are thin layers over it.

## Quick start (Windows PowerShell)

```powershell
cd C:\Users\mukun\Job\Projects\ResumeFIT
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
# then in .env: set the RESUMEFIT_FIREBASE_* values (see "Firebase setup") and, for the
# coach, RESUMEFIT_LLM_* (see "The coach")

pytest --cov=app --cov-report=term-missing     # hashing embedder, no download
ruff check . ; ruff format --check .

uvicorn app.main:app --reload                   # API on http://127.0.0.1:8000, docs at /docs
python -m http.server 5500 --directory web      # web front end: open http://localhost:5500
```

Open the site at `localhost`, not `127.0.0.1`: Firebase allows `localhost` by default.
The first API start downloads the embedding model's ONNX files (pinned revision). To run
without the download, set `RESUMEFIT_EMBEDDING_BACKEND=hashing`; scores from that backend
are for plumbing checks only.

The older Streamlit UI still works: `streamlit run ui/streamlit_app.py` from the repo root.

Docker (the image CI builds and Render runs):

```powershell
docker build -t resumefit .
docker run -p 8000:8000 -v resumefit-data:/data --env-file .env resumefit
```

## Deployment

| Part | Where | Notes |
| --- | --- | --- |
| Website | Vercel, root directory `web` | Static, deploys from `main`. `web/config.js` holds the API URL and the coach provider's name for the privacy text |
| API | Render, free plan, Docker, Virginia | Deploys from `main` (see `render.yaml`). Secrets (database URL, Gemini key) are set in Render, never in the repository |
| Database | Neon PostgreSQL 18, AWS us-east-1 | Same region as the API. Tables are created at startup |
| Sign-in | Firebase project `resumefit-2b9f9` | The site's domain is in Authorized domains |

To publish your own copy: set `RESUMEFIT_DATABASE_URL` to the Postgres connection string
as the host gives it (`postgresql://...?sslmode=require`). The API switches to the psycopg
3 driver, checks pooled connections before use (Neon's free compute sleeps when idle) and
turns off server-side prepared statements so Neon's `-pooler` endpoint works. Set
`RESUMEFIT_CORS_ORIGINS` to the site's address and add that domain in Firebase.

Free-plan behaviour: the Render API sleeps after about 15 idle minutes, and the first
request after that is slow; the site shows "Waking up the server…" meanwhile. Hugging Face
Spaces was tried first but now needs a paid plan for Docker; `deploy/hf_space.py` is kept
for reference.

## Firebase setup

1. In the [Firebase console](https://console.firebase.google.com/), open the project, then
   **Authentication > Sign-in method**, and enable **Email/Password** and **Google**.
2. Under **Authentication > Settings > Authorized domains**, add each domain that serves
   the site (`localhost` is there by default).
3. In `.env`, set `RESUMEFIT_FIREBASE_PROJECT_ID`, `RESUMEFIT_FIREBASE_API_KEY` and
   `RESUMEFIT_FIREBASE_AUTH_DOMAIN` from the project's web app config. These are public
   identifiers, not secrets. The site reads them from `GET /auth/config`.

The API only verifies the Firebase ID token sent with each request, using Google's public
keys: no service account or Firebase Admin SDK.

## API

Every endpoint except `/health` and `/auth/config` needs `Authorization: Bearer <Firebase
ID token>`; without one it returns 401. A Firebase user who has not yet agreed to the
privacy note gets 403 `registration_required` until they call `POST /auth/register`.

| Method and path | Purpose | Main responses |
| --- | --- | --- |
| `GET /health` | Liveness and model versions | 200 |
| `GET /auth/config` | Public Firebase web settings for the site | 200 |
| `POST /auth/register` | JSON `{"consent": true}`; creates the ResumeFit account | 201 (new), 200 (exists), 401, 422 |
| `GET /auth/me` | The signed-in user, verified-email and admin flags, today's quota use | 200, 401, 403 |
| `DELETE /auth/me` | Deletes the account and all its data; needs a sign-in under 5 minutes old | 204, 401 |
| `POST /jd/extract` | Read a JD file (PDF or DOCX) and return its text; stores nothing | 200, 413, 415, 422 |
| `POST /analyze` | Multipart: `resume` (PDF) plus exactly one of `jd_text` or `jd_file`; optional `store_resume_text`, `jd_source` | 201, 413, 415, 422, 429 |
| `GET /analyses` | Your analyses, newest first | 200 |
| `GET /analyses/{id}` | One of your analyses | 200, 404 |
| `DELETE /analyses/{id}` | Delete an analysis with its coach messages and stored passages | 204, 404 |
| `POST /coach` | JSON `{"analysis_id", "question"}`; returns `answer`, `citations` and `status` | 200, 404, 422, 429, 503 |
| `POST /feedback` | JSON `{"target_type": "analysis" or "coach_message", "target_id", "rating": 1-5, "comment"?}` | 201 (new), 200 (updated), 404, 422 |
| `GET /admin/metrics?days=7` | Quality, latency, usage and drift for the last N days; admins only | 200, 401, 403 |

Another user's analysis or coach answer is reported as 404, not 403, so its existence is
not revealed. A 429 carries `limit`, `used` and `reset_at` and a `Retry-After` header.
Every error has one shape: `{"error": {"code": "...", "message": "..."}}`.

```powershell
# sign in to Firebase with email and password, then call the API with the ID token
$api = "http://127.0.0.1:8000"
$key = (Invoke-RestMethod "$api/auth/config").api_key
$fb = Invoke-RestMethod -Method Post `
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=$key" `
  -ContentType "application/json" `
  -Body '{"email": "you@example.com", "password": "your password", "returnSecureToken": true}'
curl.exe -X POST "$api/analyze" -H "Authorization: Bearer $($fb.idToken)" `
  -F "resume=@resume.pdf" -F "jd_file=@jd.docx"
```

## How the matcher works

```
upload ─► documents.py ─► sections.py ─► redaction.py ─► skills.py ─┐
          type/size/page   skills,        drop header,    curated    ├─► scoring.py ─► gap report ─► SQL
          checks, text     projects, ...  redact contact  list +     │   0-100, band
JD ─────► documents.py ─► split_units (requirement sentences) ──────┘
                                         embeddings.py (MiniLM, ONNX Runtime)
```

**Score.** `score = 100 × (w1 × S_skill + w2 × S_semantic)`, with `w1 = w2 = 0.5` to start.

- `S_skill`: share of the JD's skills found on the resume, each weighted by how often the
  JD mentions it. Skills come from `app/data/skills.json`; aliases such as "ML" and
  "machine learning" count as one, and a specific skill implies a general one. A phrase in
  the resume's skills section that the list misses can still match by embedding
  similarity; these are reported separately as `semantic_matches`.
- `S_semantic`: the JD is split into requirement sentences; each takes its best cosine
  similarity to any resume chunk, and the mean is the score.
- `projects_similarity` and `experience_similarity` repeat this per section and drive the
  suggestions. Bands: strong ≥ 70, partial ≥ 45, otherwise weak.

All weights and thresholds are untuned starting values in `.env`. They are to be tuned on
labelled pairs, not by feel.

**Embedding runtime.** The model (all-MiniLM-L6-v2) runs through ONNX Runtime from the
model's official ONNX export, pinned to one revision, with the same tokenizer, 256-token
limit, mean pooling and normalisation as sentence-transformers. This removed PyTorch from
the server so it fits a 512 MB free host. Checked against sentence-transformers on 79
texts (one past the token limit): cosine 1.000000 for every text, largest element
difference 2e-7, identical reports for 6 resume and JD pairs, and the same coach
retrieval for all 30 questions. The PyTorch backend is still available
(`requirements-torch.txt`, `RESUMEFIT_EMBEDDING_BACKEND=sentence-transformers`).

## The coach

```
question ─► scope check ─► retrieve top 5 ─► language model ─► groundedness check ─► answer + citations
            (guardrails)   (resume, JD,      (Gemini API)      (every cited id must
                            guidance)                           have been retrieved)
```

- **Sources.** Three only: the resume (redacted passages), the JD, and 24 short guidance
  documents in `app/data/guidance/`, each with a title, source and version. The guidance
  text was drafted with an AI assistant for this project and should be reviewed before
  anyone relies on it.
- **Storage and search.** Passages and their embeddings are rows in the SQL `chunks`
  table, and search is an exact dot product. At this size no vector index is needed, and
  deleting an analysis with its passages is one transaction. `app/store.py` is the only
  place to change for a vector library later.
- **Retrieval.** Guidance is chunked at about 180 words; the resume and JD at about 25
  words, roughly one bullet or sentence, so a question about one fact matches that line.
  Retrieval takes the top 5, then reserves a place for the best resume and the best JD
  passage if they clear the similarity floor, so long guidance passages cannot crowd the
  student's own documents out. This took the hit rate from 55% to 100% on the draft set.
- **Guardrails.** Rules decline hiring predictions and attempts to override the
  instructions before any model call. Uploaded text reaches the model as delimited data,
  and the model has no tools. An answer is rejected, and only the passages are shown,
  if it cites an id that was not retrieved (including invented ones like `[Q1]`) or says
  "not in the sources" while citing a passage.
- **Answer status.** `answered`, `retrieval_only` (passages only: no model configured, or
  the answer failed the groundedness check), `not_in_sources`, `declined`.
- **Language model.** Set by configuration (`RESUMEFIT_LLM_*`). Production uses Google's
  `gemini-3.5-flash-lite` through the OpenAI-compatible endpoint
  (`https://generativelanguage.googleapis.com/v1beta/openai`) with a 20 s timeout and up
  to 2 retries. `none` runs retrieval-only; any local server with the same format (for
  example Ollama) also works. If the model is down, `/coach` returns 503 and the matcher
  keeps working.
- **Not built** (cuttable in the PRD): reranker, conversation memory, hybrid (BM25) search.

## Accounts, quotas, feedback and monitoring

- **Accounts.** Firebase issues a one-hour ID token that the site refreshes. The API checks
  each token's RS256 signature against Google's published keys (cached), plus audience,
  issuer, expiry and sign-in time (`app/core/security.py`). The ResumeFit account is
  created only with `consent: true`, and the consent time is stored. Admin rights need an
  email in `RESUMEFIT_ADMIN_EMAILS` that Firebase marks as verified. Deleting the account
  needs a sign-in under 5 minutes old.
- **Isolation.** Every analysis, coach and feedback lookup goes through one ownership check;
  `tests/test_api_isolation.py` tries every such route as a second user.
- **Quotas.** 20 analyses and 50 coach questions per user per UTC day by default. Only
  successful requests count.
- **Feedback.** A 1–5 rating and optional comment on an analysis or coach answer, saved
  with that item's model version. Rating again updates it.
- **Admin metrics.** Request counts by endpoint, p50/p95 latency of successful `/analyze`,
  `/coach` and `/jd/extract` calls, error rates, quota hits per day, active and top users
  (pseudonymous ids, never emails), the score distribution and the rating trend.
- **Drift check.** Every score also goes to an anonymous `score_events` table. The admin
  page compares the latest week with the first and flags a mean shift above 10 points or a
  two-sample KS test p-value below 0.01 (at least 20 scores a week), an average rating
  below 3.5, and a server error rate above 1%.

### Privacy and safety

- File type is decided by content signature. Encrypted PDFs, `.docm`, legacy `.doc`,
  oversized files, too many pages and zip bombs are rejected with a readable message.
- Uploads are parsed in memory and never written to disk.
- The full resume text is stored only if the user ticks the box for that analysis. The JD
  is stored. **Redacted resume passages are stored** for the coach (header dropped;
  email, phone, links, name and address lines removed) and are deleted with the analysis.
- **Third-party model provider: Google (Gemini API, free tier).** Only redacted passages
  and a redacted question are sent. Under the free tier's terms Google may use this text
  to improve its products and people at Google may read it; the sign-up note and the
  site's Privacy page say so.
- Coach questions and feedback comments are stored redacted. Logs are JSON with a request
  id and metadata only (status, latency, score, band, model version, error code); tests
  check that no resume or JD text and no email reaches the log.
- The resume header is excluded from scoring; a test checks that changing only the name
  and contact details leaves the score unchanged.
- Analyses older than 30 days are deleted at startup, with their passages and coach
  messages.
- Firebase holds the email and a password hash or Google identity; ResumeFit stores the
  Firebase user id, the email and the consent time, and never sees passwords.
  `DELETE /auth/me` deletes everything linked to the user in one transaction, and the site
  then deletes the Firebase user.
- Kept after deletion because they identify no one: anonymous score events and request
  metrics (route, status, latency, time).

## Evaluation

| Metric | Target (PRD) | Measured |
| --- | --- | --- |
| Test coverage of `app/` | ≥ 80% | **96%**, 229 tests, hashing embedder, 19 Nov 2026 |
| `/analyze` p95, 2-page resume | < 3 s | **642 ms** one at a time (p50 488 ms, 20 requests); **1549 ms** at concurrency 4 (p50 1113 ms, 30 requests); 0 failures. Laptop CPU, ONNX backend, 19 Nov 2026. Earlier, with PyTorch on 17 Nov: p95 767 ms and 2019 ms on a different fake 2-page resume |
| Coach retrieval hit rate at 5 (answerable questions) | none set | **100% (20/20)**; 55% (11/20) before the passage-size and reserved-slot change |
| Coach refusal accuracy (all 30 questions) | none set | **100% (30/30)** |
| Coach answers that cite a retrieved passage | ≥ 90% | **100% (20/20)**, gemini-3.5-flash-lite, coach 0.3.0 |
| Coach answers judged faithful to their sources | ≥ 85% | **19/20**, judged by Claude (the coding assistant) reading each answer against its passages, not yet by the owner |
| Coach answer p95 latency | < 8 s | **8.2 s** and **8.4 s** in two runs of the draft set (p50 1.5 s and 6.4 s), just above target. In the load test, p95 2.3 s one at a time for the calls that succeeded |
| Band agreement with human labels, held-out pairs | ≥ 70% | not measured |
| Gain over the keyword baseline | ≥ 10 points | not measured |

The coach numbers come from `eval/coach_eval.py`: a 30-question draft set in
`eval/coach_questions.json` (10 about the resume, 10 about the JD, 10 out of scope or
adversarial) against the fake sample resume and JD in `eval/samples/`. Twenty answerable
questions about one fake resume is a small set: treat the numbers as evidence that the
pipeline works, and repeat them on real, consenting users' questions before relying on them.

**Load test notes.** `eval/load_test.py` sends `/analyze` and `/coach` requests from a
thread pool and prints p50 and p95. In the 19 Nov run, 17 of 50 coach calls returned 503
`llm_unavailable` because the Gemini free tier refused bursts of concurrent calls; the API
returned its standard error and every analysis still succeeded. The numbers are from a
laptop, not from the free Render instance, which has far less CPU.

```powershell
python -m eval.coach_eval --out eval/coach_answers.csv
python -m eval.load_test --resume resume.pdf --jd jd.txt --requests 30 --concurrency 4
python -m eval.evaluate eval/labels.csv --split test   # needs labelled pairs in eval/data/
```

### Choosing the coach model

The first constraint was a laptop with no usable GPU and no API key, so small open models
ran locally in Ollama. All runs used the same 30-question set, and faithfulness for the
local models was judged by hand.

| Model, coach version | Cited answers | Faithful, of those shown | p50 / p95 latency |
| --- | --- | --- | --- |
| llama3.2:3b, 0.2.0 | 18/20 | 11/18 | 18.4 s / 27.9 s |
| qwen2.5:1.5b, 0.3.0 with extra prompt rules | 5/20 | not checked | 6.8 s / 18.0 s |
| qwen2.5:3b, 0.3.0 | 17/20 | 13/17 | 17.9 s / 39.8 s |
| **gemini-3.5-flash-lite (hosted), 0.3.0** | **20/20** | **19/20** (Claude's reading) | **1.5 s / 8.2 s** |

The local models missed the PRD's citation, faithfulness and latency targets; llama3.2:3b
invented facts, and qwen2.5:1.5b rarely cited. Two extra prompt rules made qwen2.5:3b worse
and were removed. The hosted model was chosen for speed, with the privacy trade-off above.
The larger Gemini Flash models returned 503 "high demand" on the free tier when tried, so
the pinned Flash-Lite model is used.

## Known limits

- Automated tests cover email sign-in only; Google sign-in needs a real Google account. The
  owner used the live site and reported it working (17 Nov 2026).
- Weights and band thresholds are untuned. Skills outside the curated list are invisible
  to `S_skill` (the semantic part still sees them). Bare "Go" is not matched, to avoid the
  verb; "Golang" is.
- The coach's scope rules are keyword patterns and will miss rephrased requests. Its
  retrieval settings were chosen on a small fake draft set.
- The Gemini free tier rate-limits bursts of coach questions (503 to the user). The
  Render free plan sleeps when idle.
- Section detection relies on common headings; unusual ones are scored as one block, and
  the report says so. Two-column PDFs may extract out of order. Name and address redaction
  are heuristics. English only; scanned PDFs are rejected.
- A Firebase ID token stays valid until it expires (up to an hour) after signing out.
  Quota checks can let two racing requests through at the exact limit. Quota days are UTC.
- The retention job runs at startup. Tables are created at startup; move to Alembic
  migrations before the first change to an existing table.
- Re-ingesting the guidance corpus renumbers its passages, so citation ids saved with
  older coach messages go stale.

## Next steps

1. Collect labelled resume and job pairs from consenting people, measure band agreement
   and the gain over the keyword baseline, then tune the weights and thresholds.
2. Add real coach questions and review faithfulness by hand.
3. Set an admin email in Render (`RESUMEFIT_ADMIN_EMAILS`) and check the Admin page with
   real traffic.
4. Move to Alembic migrations and schedule the retention job.
