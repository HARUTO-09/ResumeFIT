"""Compare the matcher with the keyword baseline on human-labelled pairs.

Input: a CSV with columns  resume_path, jd_path, label[, split]
  - resume_path: a PDF resume, or a .txt file of resume text
  - jd_path:     a .txt, .pdf or .docx job description
  - label:       strong | partial | weak   (from your classmates)
  - split:       dev | test  (optional; tune thresholds on dev, report test)

Usage:
    python -m eval.evaluate eval/labels.csv --split test
    python -m eval.evaluate eval/labels.csv --split test --backend hashing

Use only resumes from people who agreed to this, and keep them out of git.
"""

import argparse
import csv
from pathlib import Path

from scipy.stats import spearmanr

from app.config import get_settings
from app.core import scoring
from app.core.documents import read_jd_file, read_resume, validate_jd_text
from app.core.embeddings import build_embedder
from app.core.pipeline import analyze_texts
from app.core.skills import load_skills

RANK = {"weak": 0, "partial": 1, "strong": 2}


def load_resume(path: Path, limits) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    return read_resume(path.read_bytes(), limits)


def load_jd(path: Path, limits) -> str:
    if path.suffix.lower() == ".txt":
        return validate_jd_text(path.read_text(encoding="utf-8"), limits)
    return validate_jd_text(read_jd_file(path.read_bytes(), limits)[0], limits)


def agreement(predicted: list[str], labels: list[str]) -> float:
    return 100 * sum(p == y for p, y in zip(predicted, labels, strict=True)) / len(labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--split", choices=["dev", "test"], help="use only this split")
    parser.add_argument("--backend", help="override the embedding backend (e.g. hashing)")
    args = parser.parse_args()

    settings = get_settings()
    limits, params = settings.limits(), settings.scoring()
    embedder = build_embedder(args.backend or settings.embedding_backend, settings.embedding_model)
    skills_db = load_skills()
    base = args.csv_path.parent

    labels, model_scores, baseline_scores = [], [], []
    with args.csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if args.split and row.get("split", "").strip() != args.split:
                continue
            label = row["label"].strip().lower()
            if label not in RANK:
                raise SystemExit(f"Unknown label {label!r} for {row['resume_path']}")
            resume = load_resume(base / row["resume_path"], limits)
            jd = load_jd(base / row["jd_path"], limits)
            labels.append(label)
            model_scores.append(analyze_texts(resume, jd, embedder, skills_db, params).score)
            baseline_scores.append(100 * scoring.keyword_baseline(resume, jd))

    if len(labels) < 2:
        raise SystemExit("Need at least 2 labelled pairs.")

    ranks = [RANK[y] for y in labels]
    print(f"Pairs: {len(labels)}   split: {args.split or 'all'}   embedder: {embedder.name}")
    print(f"Bands: strong >= {params.strong_threshold}, partial >= {params.partial_threshold}")
    print(f"{'':<18}{'band agreement':>16}{'Spearman':>12}")
    for name, scores in (("matcher", model_scores), ("keyword baseline", baseline_scores)):
        bands = [scoring.band_for(s, params) for s in scores]
        rho = spearmanr(scores, ranks).statistic
        print(f"{name:<18}{agreement(bands, labels):>15.1f}%{rho:>12.3f}")
    print(
        "\nNote: both rows use the same band thresholds. Tune thresholds (and weights) on the "
        "dev split only, and report the test split with its sample size."
    )


if __name__ == "__main__":
    main()
