# ResumeFit: project notes for Claude

ResumeFit scores a resume against a job description and explains the gaps. The PRD has
three phases: 1 Matcher MVP, 2 RAG coach, 3 SaaS-lite (accounts, quotas, admin metrics).
Phases 1 and 2 are written. README.md has the architecture, API table and known limits.

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

## Do next, in order

1. After the owner restarts Windows: start Docker Desktop, run the local Docker build,
   and update README Status.
2. Owner decides whether to move the coach to a hosted model to meet the targets; that
   needs an API key, a cost decision and a privacy note naming the provider.
3. Collect consenting resumes, labelled pairs and real coach questions under `eval/`;
   rerun both evaluations before quoting any quality number.

Stop and ask the owner before: deploying, sending any text to a third-party model,
switching the coach to a hosted provider, starting Phase 3, or changing scoring weights
or thresholds (those are tuned on data, not by feel). Pushing to `origin main` is
approved.

## Rules for this repo

- `app/core/` must not import FastAPI or SQLAlchemy.
- The matcher makes no LLM call. Only the coach does, through `app/core/llm.py`.
- The coach may show generated text only if every cited passage id was retrieved.
- Never log, store or commit resume or JD text beyond what README "Privacy" describes.
  Real resumes go under `eval/data/` (git-ignored) and only from people who consented.
- Tests use fake personal data and the hashing embedder; keep the suite download-free.
- Every error response uses `{"error": {"code": "...", "message": "..."}}`.
- Do not put a number in README or on a resume bullet unless it was measured.
