"""Small load test for /analyze and /coach: p50 and p95 latency under concurrency.

Needs a running API (uvicorn app.main:app). Uses only the `requests` package,
so no Locust install is needed for the PRD latency check.

    python -m eval.load_test --resume path/to/resume.pdf --jd path/to/jd.txt
    python -m eval.load_test --resume r.pdf --jd jd.txt --requests 40 --concurrency 4

Use a fake resume: the analyses this creates are stored like any other, and
they are deleted again at the end unless --keep is given.
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

COACH_QUESTIONS = [
    "Which of my projects shows that I can build an API?",
    "What does this job description say about deployment?",
    "How should I tailor my resume to this job description?",
    "Where does my resume mention Docker or containers?",
]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarise(name: str, latencies: list[float], failures: int) -> None:
    if not latencies:
        print(f"{name}: no successful requests ({failures} failed)")
        return
    print(
        f"{name}: n={len(latencies)} failed={failures} "
        f"p50={statistics.median(latencies):.0f} ms "
        f"p95={percentile(latencies, 95):.0f} ms "
        f"max={max(latencies):.0f} ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--resume", type=Path, required=True, help="resume PDF")
    parser.add_argument("--jd", type=Path, required=True, help="JD as a UTF-8 text file")
    parser.add_argument("--requests", type=int, default=30, help="analyze requests in total")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--keep", action="store_true", help="do not delete the analyses")
    args = parser.parse_args()

    resume_bytes = args.resume.read_bytes()
    jd_text = args.jd.read_text(encoding="utf-8")
    health = requests.get(f"{args.api}/health", timeout=30).json()
    print(f"API {args.api}: {health['model_version']}, coach {health['coach_model_version']}")

    # one warm-up call so the first-request cost does not count as steady state
    warm = requests.post(
        f"{args.api}/analyze",
        files={"resume": ("resume.pdf", resume_bytes, "application/pdf")},
        data={"jd_text": jd_text},
        timeout=120,
    )
    warm.raise_for_status()
    created = [warm.json()["id"]]
    print(f"warm-up analyze: {warm.json()['latency_ms']} ms server-side")

    def analyze(_: int):
        started = time.perf_counter()
        response = requests.post(
            f"{args.api}/analyze",
            files={"resume": ("resume.pdf", resume_bytes, "application/pdf")},
            data={"jd_text": jd_text},
            timeout=120,
        )
        elapsed = (time.perf_counter() - started) * 1000
        return response.status_code, elapsed, response.json().get("id")

    def coach(i: int):
        started = time.perf_counter()
        response = requests.post(
            f"{args.api}/coach",
            json={"analysis_id": created[0], "question": COACH_QUESTIONS[i % 4]},
            timeout=120,
        )
        return response.status_code, (time.perf_counter() - started) * 1000, None

    for name, fn, expected in (("/analyze", analyze, 201), ("/coach", coach, 200)):
        latencies: list[float] = []
        failures = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for status, elapsed, analysis_id in pool.map(fn, range(args.requests)):
                if analysis_id:
                    created.append(analysis_id)
                if status == expected:
                    latencies.append(elapsed)
                else:
                    failures += 1
        summarise(f"{name} (concurrency {args.concurrency})", latencies, failures)

    if not args.keep:
        for analysis_id in created:
            requests.delete(f"{args.api}/analyses/{analysis_id}", timeout=30)
        print(f"deleted {len(created)} analyses created by this run")


if __name__ == "__main__":
    main()
