"""Evaluate the coach on a question set: retrieval hit rate, citation rate, refusal accuracy.

Runs the coach core directly (no API or database needed) on the sample resume
and JD in eval/samples plus the guidance corpus.

    python -m eval.coach_eval                        # uses the settings in .env
    python -m eval.coach_eval --backend hashing      # plumbing check, no model download
    python -m eval.coach_eval --out eval/coach_answers.csv

What it reports
  - Hit rate at k: share of answerable questions where a gold passage was retrieved.
  - Refusal accuracy: out-of-scope and adversarial questions refused, and answerable
    questions not refused.
  - Citation rate (only with a language model configured): share of answerable
    questions whose answer cites at least one retrieved passage.
  - A CSV of every answer, with and without retrieval, for the manual faithfulness
    check. Faithfulness cannot be computed automatically: read each answer against its
    cited passages and fill the `faithful` column yourself.
"""

import argparse
import csv
import dataclasses
import json
from pathlib import Path

from app.config import get_settings
from app.core.chunking import chunk_text, resume_passages
from app.core.coach import Passage, answer_question, passage_id
from app.core.embeddings import build_embedder
from app.core.guardrails import extract_citations
from app.core.guidance import load_guidance
from app.core.llm import LLMUnavailable, build_llm

HERE = Path(__file__).resolve().parent
REFUSED = ("declined", "not_in_sources")
NO_RETRIEVAL_SYSTEM = (
    "You are a resume coach for students. Answer the question briefly (at most 150 words)."
)


def build_corpus(resume_text: str, jd_text: str, embedder, params):
    words, overlap = params.document_chunk_words, params.document_chunk_overlap_words
    items = [
        ("resume", section, text) for section, text in resume_passages(resume_text, words, overlap)
    ]
    items += [("jd", "job description", text) for text in chunk_text(jd_text, words, overlap)]
    for doc in load_guidance():
        items += [
            ("guidance", doc.title, text)
            for text in chunk_text(doc.text, params.chunk_words, params.chunk_overlap_words)
        ]
    passages = [
        Passage(passage_id(source, i), source, label, text)
        for i, (source, label, text) in enumerate(items, start=1)
    ]
    vectors = embedder.encode([f"{p.label}\n{p.text}" for p in passages])
    return passages, vectors


def is_hit(retrieved, gold: list[dict]) -> bool:
    return any(
        passage.source == g["source"] and g["contains"].lower() in passage.text.lower()
        for passage, _ in retrieved
        for g in gold
    )


def pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{100 * numerator / denominator:.1f}% ({numerator}/{denominator})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--questions", type=Path, default=HERE / "coach_questions.json")
    parser.add_argument("--resume", type=Path, default=HERE / "samples" / "resume.txt")
    parser.add_argument("--jd", type=Path, default=HERE / "samples" / "jd.txt")
    parser.add_argument("--backend", help="override the embedding backend (e.g. hashing)")
    parser.add_argument("--min-similarity", type=float, help="override the retrieval floor")
    parser.add_argument("--out", type=Path, help="write answers to this CSV for manual review")
    args = parser.parse_args()

    settings = get_settings()
    params = settings.coach()
    if args.min_similarity is not None:
        params = dataclasses.replace(params, min_similarity=args.min_similarity)
    embedder = build_embedder(args.backend or settings.embedding_backend, settings.embedding_model)
    llm = build_llm(
        settings.llm_provider,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_api_key,
        settings.llm_timeout_s,
    )
    passages, vectors = build_corpus(
        args.resume.read_text(encoding="utf-8"),
        args.jd.read_text(encoding="utf-8"),
        embedder,
        params,
    )
    questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]

    rows = []
    hits = answerable = cited = refusal_correct = failed = 0
    for item in questions:
        try:
            result = answer_question(item["question"], passages, vectors, embedder, llm, params)
        except LLMUnavailable as exc:
            failed += 1
            print(f"model call failed ({exc}): {item['question']}")
            continue
        refused = result.status in REFUSED
        expect_refuse = item["expect"] == "refuse"
        refusal_correct += refused == expect_refuse
        hit = None
        if not expect_refuse:
            answerable += 1
            hit = is_hit(result.retrieved, item["gold"])
            hits += hit
            cited += result.status == "answered" and bool(extract_citations(result.answer))

        baseline = ""
        if llm is not None and not expect_refuse:
            try:
                baseline = llm.complete(NO_RETRIEVAL_SYSTEM, item["question"])
            except LLMUnavailable:
                baseline = "(model call failed)"
        rows.append(
            {
                "category": item["category"],
                "question": item["question"],
                "expect": item["expect"],
                "status": result.status,
                "reason": result.reason or "",
                "gold_retrieved": "" if hit is None else hit,
                "retrieved_ids": " ".join(p.id for p, _ in result.retrieved),
                "answer": result.answer,
                "cited_passages": " || ".join(f"[{p.id}] {p.text}" for p in result.citations),
                "faithful": "",
                "answer_without_retrieval": baseline,
                "faithful_without_retrieval": "",
            }
        )

    done = len(rows)
    print(f"Questions: {done} run, {failed} failed   embedder: {embedder.name}")
    print(
        f"LLM: {llm.name if llm else 'none (retrieval-only)'}   top_k: {params.top_k}   "
        f"min_similarity: {params.min_similarity}"
    )
    print(f"Hit rate at {params.top_k} (answerable questions): {pct(hits, answerable)}")
    print(f"Refusal accuracy (all questions):            {pct(refusal_correct, done)}")
    if llm is not None:
        print(f"Citation rate (answerable questions):        {pct(cited, answerable)}")
    else:
        print(
            "Citation rate: not applicable without a language model "
            "(retrieval-only answers always show their passages)."
        )
    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Answers written to {args.out}. Fill the 'faithful' columns by hand.")
    print(
        "\nThe sample resume and JD are small and fake; treat these numbers as a check that "
        "the pipeline works, and repeat on real, consenting users' data before reporting."
    )


if __name__ == "__main__":
    main()
