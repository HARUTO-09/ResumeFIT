# ResumeFit: project notes for Claude

ResumeFit scores a resume against a job description and explains the gaps. The PRD has
three phases: 1 Matcher MVP, 2 RAG coach, 3 SaaS-lite (accounts, quotas, admin metrics).
Phase 1 code is written. README.md has the architecture, API table and known limits.

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

## Do next, in order

1. Add a GitHub remote, push, and check that CI is green (owner decides when).
2. Install Docker Desktop and run `docker build -t resumefit .`.
3. Collect consenting resumes and labelled pairs under `eval/data/`, then run
   `python -m eval.evaluate` and fill in the README results table.
4. Load-test `/analyze` for p50 and p95 before claiming any latency number.

Stop and ask the owner before: pushing to any remote, deploying, starting Phase 2, or
changing scoring weights or thresholds (those are tuned on labelled data, not by feel).

## Rules for this repo

- `app/core/` must not import FastAPI or SQLAlchemy.
- The matcher makes no LLM call.
- Never log, store or commit resume or JD text beyond what README "Privacy" describes.
  Real resumes go under `eval/data/` (git-ignored) and only from people who consented.
- Tests use fake personal data and the hashing embedder; keep the suite download-free.
- Every error response uses `{"error": {"code": "...", "message": "..."}}`.
- Do not put a number in README or on a resume bullet unless it was measured.
