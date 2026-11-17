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
- `eval/coach_eval.py` with the real embedding model, retrieval-only: hit rate at 5 is
  55% (11/20), refusal accuracy 100% (30/30). README "Evaluation" explains the misses:
  the resume is 4 passages and the JD 1 passage against 24 guidance passages, so gold
  passages rank below guidance. The threshold is not the lever; chunking or a per-source
  quota is. `eval/coach_answers.csv` is the untracked output for the manual check.
- `.env` still has no `RESUMEFIT_LLM_*` or `RESUMEFIT_COACH_*` lines (defaults apply:
  no language model, retrieval-only coach).

## Do next, in order

1. Owner decides on the retrieval fix (smaller resume and JD chunks, or a per-source
   quota) and reviews the draft question set; then rerun `python -m eval.coach_eval`.
2. Owner chooses a language model provider; then configure `.env`, rerun the eval, and
   do the manual faithfulness check on the CSV.
3. Still open from Phase 1: GitHub remote and CI, Docker build, labelled pairs, load test.

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
