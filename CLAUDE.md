# ResumeFit: project notes for Claude

ResumeFit scores a resume against a job description and explains the gaps. The PRD has
three phases: 1 Matcher MVP, 2 RAG coach, 3 SaaS-lite (accounts, quotas, admin metrics).
All three are written. README.md has the architecture, API table and known limits.

## Current state (17 Nov 2026, evening)

- `.venv` exists (Python 3.14, torch 2.15 CPU). Git is at `C:\Program Files\Git\cmd`
  (prepend it to PATH in a shell opened before 16 Nov).
- `pytest --cov=app` passes (118 tests, 97% coverage); `ruff check` and
  `ruff format --check` are clean. Run both before every commit.
- Remote `origin` is `https://github.com/HARUTO-09/ResumeFIT.git`, branch `main`. CI
  (lint, tests with an 80% coverage gate, Docker build on the runner) was green on the
  first push.
- The matcher and coach APIs were smoke-tested by hand with the real embedding model
  (all-MiniLM-L6-v2). The Streamlit UI and its coach chat were driven headlessly with
  Streamlit's AppTest; the upload flow has not been clicked through in a browser.
- Weights and band thresholds are still untuned placeholders.
- `Claude outputs/` holds hand-saved duplicates of CI and pre-commit files; it is
  git-ignored and can be deleted.

## Coach (Phase 2)

- Retrieval (coach 0.2.0): resume and JD passages are about 25 words; retrieval reserves a
  slot for the best resume and JD passage. Hit rate at 5 on the draft set is 20/20.
- Guardrail (coach 0.3.0): answers citing an id outside R/J/G (e.g. `[Q1]`) or saying
  "not in the sources" while citing a passage are rejected and shown as passages only.
- Language model: local qwen2.5:3b through Ollama (`%LOCALAPPDATA%\Programs\Ollama`),
  configured in `.env` with a 60 s timeout. Ollama must be running for `/coach`; if it is
  not, `/coach` returns 503 and the matcher keeps working. Nothing leaves the machine.
- Chosen over llama3.2:3b and qwen2.5:1.5b; README "Choosing the coach model" has the
  table. qwen2.5:3b still misses the PRD targets: 17/20 cited, 13/17 faithful by hand,
  p95 39.8 s. Two prompt rules tried on 17 Nov made it worse and were removed.
- Eval answer CSVs are untracked (`eval/coach_answers.csv` and copies in the scratchpad).
- `eval/load_test.py` measured `/analyze` p95 767 ms (concurrency 1) and 2019 ms
  (concurrency 4) on a fake 2-page resume.

## Docker

- Docker Desktop 4.99 was installed on 17 Nov 2026. Its engine failed with "Virtual
  Machine Platform not enabled", so `wsl --install --no-distribution` was run elevated.
  A Windows restart is needed before Docker can start; then run `docker build -t
  resumefit .` and record the result in README.

## Phase 3 added on 17 Nov 2026 (written outside this machine, API not yet run here)

- Sign-in is **Firebase Authentication** (owner's request, 17 Nov), project
  `resumefit-2b9f9`, Google and email/password. The first draft's own passwords and
  HS256 tokens were replaced the same day and never ran here.
- Tested in the authoring sandbox (39 tests, ruff clean): `app/core/security.py`
  (Firebase ID token verification with PyJWT against Google's keys),
  `app/core/monitoring.py`, `ui/firebase_client.py` (Firebase REST: sign-in, sign-up,
  refresh, reset, verify email, delete); `tests/test_security.py`,
  `tests/test_monitoring.py`, `tests/test_firebase_client.py`. `tests/firebase_fake.py`
  signs fake Firebase tokens with a local key served on 127.0.0.1.
- **Never executed:** `app/deps.py`, `app/auth.py` (/auth/config, /auth/register, GET
  and DELETE /auth/me), `app/quotas.py`, `app/admin.py`, and the changes to
  `app/routes.py`, `app/models.py`, `app/db.py`, `app/main.py`, `app/config.py`,
  `app/schemas.py`, `app/errors.py`; the API test files `tests/test_api_accounts.py`,
  `test_api_isolation.py`, `test_api_quotas.py`, `test_api_feedback_admin.py`, the
  `make_api` fixture and the sign-in in `tests/test_api.py` and `test_api_coach.py`; the
  Streamlit sign-in, consent, ratings, account and admin code; the Google component
  `ui/firebase_google/index.html`; Firebase sign-in in `eval/load_test.py`.
- New dependency `pyjwt[crypto]` in `requirements.txt`; the venv may not have it yet.
- 17 Nov evening: `pip install -r requirements.txt` done; 218 tests pass (97%), ruff clean.
  `.env` now has the Firebase project id, web API key and auth domain. Probed via the
  Identity Toolkit REST API: Google sign-in is enabled; Email/Password is disabled
  (PASSWORD_LOGIN_DISABLED), so the owner must enable it before step 2 can finish. With the real API running, `/auth/config` answers
  and `/auth/me` returns 401 for no token and for a bad token. `RESUMEFIT_ADMIN_EMAILS`
  is not set.
- Firebase console: Google and Email/Password both enabled (17 Nov evening).
- Live API run against the real project with two throwaway test accounts (created and
  deleted again): consent, analysis, coach, ratings, isolation, admin 403 and account
  deletion all passed (21/21). Script: scratchpad `account_flow.py` (not in the repo).
  The UI's sign-in screens, especially Google, still need a click-through in a browser.

## Web front end and free hosting (17 Nov 2026, late)

- The owner wants everything on free tiers, looking like a real product. They asked for a
  lighter UI than Streamlit: `web/` is plain HTML/CSS/JS (no build), Firebase JS SDK
  10.12.2 from gstatic, API URL and coach-provider privacy text in `web/config.js`.
  Serve with `python -m http.server 5500 --directory web` and open `localhost:5500`.
- API has CORS from `RESUMEFIT_CORS_ORIGINS` (`.env` has `http://localhost:5500`).
  222 tests pass, 97%, ruff clean. Browser flow (scratchpad `web_flow.py`, Playwright with
  Edge) passed 21/21 with a throwaway test account it deletes.
- Coach: switched on the owner's request to Google Gemini API free tier,
  `gemini-3.5-flash-lite` (key in `.env` only, never commit it). Bigger Flash models gave
  503 "high demand". Eval: 20/20 cited, 19/20 faithful (Claude's reading, not the
  owner's), p50 1.5 s, p95 8.2 s. README Privacy and `web/config.js` name Google.
  Answers CSV in scratchpad `coach_answers_gemini.csv`. Ollama is no longer needed.
- Free stack, all live since 17 Nov 2026: `web/` on Vercel Hobby
  (`https://resumefit-web.vercel.app`, root directory `web`, deploys from `main`), API on
  Render free (Docker, 512 MB, region virginia), Neon Postgres. Browser flow 21/21 on the
  live site; the owner then used the live site and reported everything working (17 Nov,
  late). CORS and Firebase Authorized domains include the Vercel domain. The Render
  API key cannot edit env vars (403); change them in the Render dashboard.
- Render: service `srv-dbu8vuui0phs7394d830`, `https://resumefit-api-x93n.onrender.com`,
  workspace `tea-dbu8k9k9v7es73e1l8d0`, auto-deploys from `main`. Created through the
  Render API (scratchpad `render_deploy.py`), env vars set there (secrets not in repo).
  Live 17 Nov; account flow 21/21 against it. CORS origins not set until the Vercel URL
  exists. Pushing to main redeploys production. Hugging Face was dropped: Docker Spaces now need PRO
  (402 on create, nothing was created). `deploy/hf_space.py` is unused.
- Embeddings now run through ONNX Runtime (`OnnxEmbedder`, default backend `onnx`, model
  revision pinned); no torch in requirements. Verified identical to sentence-transformers
  (cosine 1.000000, 6/6 identical reports, 30/30 same retrieval); API peak 324 MB.
- Neon: project shy-poetry-66901925, AWS us-east-1, only the Postgres service enabled.
  Connection string is `NEON_DATABASE_URL` in `.env` (not read by the app; local runs stay
  on SQLite). Set it as `RESUMEFIT_DATABASE_URL` in the host's secrets. Verified 17 Nov:
  tables created, account flow 21/21 against it, no user rows left. The Wi-Fi router's DNS
  (192.168.29.1) refuses `*.neon.tech` endpoint names; locally append
  `&hostaddr=<IPv4 from 1.1.1.1>` to the URL. Node.js is not installed, so the Neon CLI
  was not used.

## Do next, in order

1. Done 17 Nov: requirements installed, 218 tests pass, ruff clean. Keep the isolation,
   token and privacy tests as strict as written.
2. API flow done against the real project (see above). Still to do: the owner clicks
   through Google and email sign-in, consent, ratings and deletion in the UI in a
   browser. Update README Status with what was actually run.
3. Ask the owner which email to put in `RESUMEFIT_ADMIN_EMAILS`, then check the Admin tab.
4. Rerun `eval/load_test.py` with raised quotas and compare with the 17 Nov numbers.
5. Still open: Docker build after the Windows restart, hosted-model decision for the coach,
   labelled pairs and real coach questions.

Stop and ask the owner before: deploying, sending any text to a third-party model,
switching the coach to a hosted provider, creating or deleting Firebase users other
than test accounts, or changing scoring weights or thresholds (those are tuned on data,
not by feel). Pushing to `origin main` is approved.

## Rules for this repo

- `app/core/` must not import FastAPI or SQLAlchemy.
- The matcher makes no LLM call. Only the coach does, through `app/core/llm.py`.
- The coach may show generated text only if every cited passage id was retrieved.
- Never log, store or commit resume or JD text beyond what README "Privacy" describes.
  Real resumes go under `eval/data/` (git-ignored) and only from people who consented.
- Tests use fake personal data and the hashing embedder; keep the suite download-free.
- Every error response uses `{"error": {"code": "...", "message": "..."}}`.
- Do not put a number in README or on a resume bullet unless it was measured.
