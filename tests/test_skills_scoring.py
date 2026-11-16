import pytest
from helpers import JD_TEXT, RESUME_TEXT, WEAK_RESUME_TEXT, make_docx, make_pdf

from app.core import scoring
from app.core.documents import read_jd_file, read_resume, validate_jd_text
from app.core.embeddings import EmbeddingCache
from app.core.params import ScoringParams
from app.core.pipeline import analyze_texts
from app.core.skills import candidate_phrases, count_skills, resume_skills, synonym_matches


# ---- skill extraction (F4) ------------------------------------------------
def test_synonyms_count_as_one_skill(skills_db):
    counts = count_skills("We use ML daily. Machine learning matters. ML models too.", skills_db)
    assert counts == {"machine learning": 3}


def test_word_boundaries(skills_db):
    counts = count_skills("JavaScript, C++, C# and MySQL in our R&D team. Go to market.", skills_db)
    assert set(counts) == {"javascript", "c++", "c#", "mysql"}  # not java, c, sql, r or golang


def test_case_sensitive_short_names(skills_db):
    assert "r" in count_skills("Languages: R, Python", skills_db)
    assert "r" not in count_skills("we r hiring", skills_db)
    assert "c" in count_skills("Languages: C, C++", skills_db)


def test_overlapping_aliases_are_one_mention(skills_db):
    assert count_skills("Deploy on cloud platforms", skills_db)["cloud"] == 1


def test_specific_skill_implies_general(skills_db):
    have = resume_skills("Built dashboards on PostgreSQL and trained models in PyTorch", skills_db)
    assert {"postgresql", "sql", "pytorch", "deep learning", "machine learning"} <= have


def test_embedding_synonym_match(embedder):
    phrases = candidate_phrases("Tools: Git, Kubernetes orchestration\nOther: Data visualisations")
    assert "Kubernetes orchestration" in phrases
    matches = synonym_matches(["kubernetes", "pandas"], phrases, embedder, threshold=0.6)
    assert [m["skill"] for m in matches] == ["kubernetes"]


# ---- scoring (F5) -----------------------------------------------------------
def test_skill_overlap_is_weighted_by_jd_mentions():
    assert scoring.skill_overlap({"python": 3, "sql": 1}, {"python"}) == 0.75
    assert scoring.skill_overlap({}, set()) is None


def test_combine_and_bands():
    params = ScoringParams()
    assert scoring.combine(0.8, 0.6, params) == 70
    assert scoring.combine(None, 0.42, params) == 42
    assert [scoring.band_for(s, params) for s in (70, 69, 45, 44)] == [
        "strong", "partial", "partial", "weak",
    ]  # fmt: skip
    with pytest.raises(ValueError):
        ScoringParams(w_skill=0.7, w_semantic=0.7)


def test_keyword_baseline():
    assert scoring.keyword_baseline("python sql docker", "Python and SQL") == 1.0
    assert scoring.keyword_baseline("excel", "Python and SQL") == 0.0


# ---- full pipeline ------------------------------------------------------------
def run(resume, jd, embedder, skills_db, **kw):
    return analyze_texts(resume, jd, embedder, skills_db, **kw)


def test_result_shape_and_components(embedder, skills_db):
    r = run(RESUME_TEXT, JD_TEXT, embedder, skills_db)
    assert 0 <= r.score <= 100 and r.band in ("strong", "partial", "weak")
    assert set(r.components) == {
        "skill_overlap", "semantic_similarity", "projects_similarity", "experience_similarity",
    }  # fmt: skip
    assert all(0 <= v <= 1 for v in r.components.values())
    assert {"python", "sql", "pytorch", "docker", "git"} <= set(r.matched_skills)
    assert r.sections_missing == []
    assert r.model_version.startswith("matcher-")


def test_relevant_resume_beats_irrelevant_one(embedder, skills_db):
    strong = run(RESUME_TEXT, JD_TEXT, embedder, skills_db)
    weak = run(WEAK_RESUME_TEXT, JD_TEXT, embedder, skills_db)
    assert strong.score > weak.score + 15


def test_missing_skills_ordered_by_jd_emphasis(embedder, skills_db):
    r = run(WEAK_RESUME_TEXT, JD_TEXT, embedder, skills_db)
    mentions = [m["jd_mentions"] for m in r.missing_skills]
    assert mentions == sorted(mentions, reverse=True)
    assert r.missing_skills[0]["jd_mentions"] >= 2
    assert not set(r.matched_skills) & {m["skill"] for m in r.missing_skills}


def test_gap_report_flags_missing_and_weak_sections(embedder, skills_db):
    r = run(WEAK_RESUME_TEXT, JD_TEXT, embedder, skills_db)
    assert r.sections_missing == ["experience"]
    by_section = {s["section"]: s["text"] for s in r.suggestions}
    assert "No experience section" in by_section["experience"]
    assert "skills" in by_section and "projects" in by_section
    assert len(by_section) == len(r.suggestions)  # one suggestion per section


def test_counterfactual_name_and_contact_do_not_change_score(embedder, skills_db):
    """Fairness check from the PRD: only the name (and contact details) differ."""
    other = (
        RESUME_TEXT.replace("Asha Rao", "Mohammed Farooq Khan")
        .replace("asha.rao@example.com", "mfk@example.org")
        .replace("Hyderabad 500081", "Patna 800001")
    )
    a = run(RESUME_TEXT, JD_TEXT, embedder, skills_db)
    b = run(other, JD_TEXT, embedder, skills_db)
    assert a.score == b.score and a.components == b.components


def test_same_jd_as_text_pdf_and_docx_scores_within_two_points(embedder, skills_db, limits):
    resume = read_resume(make_pdf(RESUME_TEXT), limits)
    from_pdf, _ = read_jd_file(make_pdf(JD_TEXT), limits)
    from_docx, _ = read_jd_file(make_docx(JD_TEXT), limits)
    scores = [
        run(resume, validate_jd_text(jd, limits), embedder, skills_db).score
        for jd in (JD_TEXT, from_pdf, from_docx)
    ]
    assert max(scores) - min(scores) <= 2, scores


def test_resume_without_headings_still_scores(embedder, skills_db):
    r = run("I know Python and SQL and built a Docker image for a PyTorch model.", JD_TEXT,
            embedder, skills_db)  # fmt: skip
    assert r.score > 0
    assert len(r.sections_missing) == 4
    assert any("No section headings" in n for n in r.notes)


def test_jd_without_known_skills_uses_semantic_only(embedder, skills_db):
    jd = "We want a friendly person to greet visitors and keep the front desk tidy all day."
    r = run(RESUME_TEXT, jd, embedder, skills_db)
    assert r.components["skill_overlap"] is None
    assert r.score == round(100 * r.components["semantic_similarity"])


def test_deterministic_and_cache_reuses_jd_embeddings(embedder, skills_db):
    cache = EmbeddingCache()
    a = run(RESUME_TEXT, JD_TEXT, embedder, skills_db, cache=cache)
    b = run(RESUME_TEXT, JD_TEXT, embedder, skills_db, cache=cache)
    assert a.to_dict() == b.to_dict()
    assert cache.hits == 1
