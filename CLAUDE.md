# ResumeFit: project notes for Claude

ResumeFit scores a resume against a job description and explains the gaps. The PRD has
three phases: 1 Matcher MVP, 2 RAG coach, 3 SaaS-lite (accounts, quotas, admin metrics).
Phases 1 and 2 are written. README.md has the architecture, API table and known limits.

## Current state (16 Nov 2026, evening)

- `.venv` exists (Python 3.14, torch 2.15 CPU). `.env` is a copy of `.env.example`.
- Full suite runs locally: `pytest --cov=app` passes with 96% coverage; `ruff check` and
  `ruff format --check` are clean. Run both before every commit.
- The API was smoke-tested by hand with the real model (all-MiniLM-L6-v2, cached under
  `~/.cache/huggingface`). All endpoints and the documented error codes work. The
  Streamlit UI loads against it; its upload flow has not been clicked through in a browser.
- Weights and band thresholds are still untuned placeholders.
- Git for Windows was installed on 16 Nov 2026 and the repo has its first commit. No
  remote yet. Docker is not installed, so the Dockerfile and CI have never run.
- `Claude outputs/` holds hand-saved duplicates of `.github/workflows/ci.yml` and
  `.pre-commit-config.yaml`; it is git-ignored and can be deleted.

## Phase 2 (RAG coach), first run on this machine 17 Nov 2026

- Core modules `app/core/chunking.py`, `guardrails.py`, `coach.py`, `llm.py`,
  `guidance.py`; 24 guidance files in `app/data/guidance/`; storage in `app/store.py`;
  `POST /coach`; coach chat in `ui/streamlit_app.py`.
- Everything ran first time: 115 tests pass, 97% coverage, ruff clean. `/health` reports
  24 guidance documents; `/coach` was smoke-tested retrieval-only; the UI coach chat was
  driven headlessly with Streamlit's AppTest.
- Retrieval change on 17 Nov 2026 (coach version 0.2.0): resume and JD passages are now
  about 25 words each (`CoachParams.document_chunk_words`) and retrieval reserves a slot
  for the best resume and best JD passage (`reserve_user_sources`). On the draft eval set
  with the real embedding model this took hit rate at 5 from 11/20 to 20/20; refusal
  accuracy stayed 30/30. Guidance chunking is unchanged, so no re-ingest happens.
  Analyses made before this change keep their old coarse chunks.
- `eval/load_test.py` (threads + requests, no Locust) was run against the API with a
  fake 2-page resume: `/analyze` p95 767 ms at concurrency 1 and 2019 ms at
  concurrency 4; `/coach` retrieval-only p95 34 ms and 160 ms. Numbers are in README.
- `eval/coach_answers.csv` is the untracked eval output for the manual faithfulness check.
- `.env` still has no `RESUMEFIT_LLM_*` or `RESUMEFIT_COACH_*` lines (defaults apply:
  no language model, retrieval-only coach).

## Do next, in order

1. Owner chooses a language model provider; then configure `.env`, rerun
   `python -m eval.coach_eval --out eval/coach_answers.csv`, and do the manual
   faithfulness check on the CSV.
2. Owner adds a GitHub remote and pushes, so CI runs; installs Docker and runs the build.
3. Collect consenting resumes, labelled pairs and real coach questions under `eval/`;
   rerun both evaluations before quoting any quality number.

Stop and ask the owner before: pushing to any remote, deploying, choosing or configuring a
language-model provider, sending any text to a third-party model, starting Phase 3, or
changing scoring weights or thresholds (those are tuned on data, not by feel).

## Rules for this repo

- `app/core/` must not import FastAPI or SQLAlchemy.
- The matcher makes no LLM call. Only the coach does, through `app/core/llm.py`.
- The coach may show generated text only if every cited passage id was retrieved.
- Never log, store or commit resume or JD text beyond what README "Privacy" describes.
  Real resumes go under `eval/data/` (git-ignored) and only from people who consented.
- Tests use fake personal data and the hashing embedder; keep the suite download-free.
- Every error response uses `{"error": {"code": "...", "message": "..."}}`.
- Do not put a number in README or on a resume bullet unless it was measured.
