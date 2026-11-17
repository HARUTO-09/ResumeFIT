"""Streamlit front end for the ResumeFit API.

Run the API first (uvicorn app.main:app), then:
    streamlit run ui/streamlit_app.py
"""

import os

import requests
import streamlit as st

API_URL = os.environ.get("RESUMEFIT_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 60

st.set_page_config(page_title="ResumeFit", layout="wide")
st.title("ResumeFit")
st.caption(
    "Scores your resume against a job description and explains the gaps. "
    "The score is a guide to improving a resume, not a hiring decision, and it can be wrong."
)


def api(method: str, path: str, **kwargs):
    """Call the API. Returns (data, error_message)."""
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=TIMEOUT, **kwargs)
    except requests.RequestException:
        return None, f"Cannot reach the API at {API_URL}. Is it running?"
    if response.status_code == 204:
        return {}, None
    try:
        body = response.json()
    except ValueError:
        return None, f"Unexpected response ({response.status_code})."
    if response.ok:
        return body, None
    return None, body.get("error", {}).get("message", f"Error {response.status_code}.")


def show_analysis(a: dict) -> None:
    left, right = st.columns([1, 2])
    with left:
        st.metric("Match score", f"{a['score']} / 100", a["band"].upper(), delta_color="off")
    with right:
        st.write("**How the score is built**")
        for name, value in a["components"].items():
            label = name.replace("_", " ").capitalize()
            if value is None:
                st.write(f"{label}: not available")
            else:
                st.progress(min(max(value, 0.0), 1.0), text=f"{label}: {value:.2f}")
    for note in a["notes"]:
        st.info(note)

    matched, missing = st.columns(2)
    with matched:
        st.subheader("Matched skills")
        st.write(", ".join(a["matched_skills"]) or "None found")
        for m in a["semantic_matches"]:
            st.caption(f'"{m["resume_phrase"]}" counted as {m["skill"]} (similar meaning)')
    with missing:
        st.subheader("Missing skills")
        if a["missing_skills"]:
            rows = [
                {"Skill": m["skill"], "JD mentions": m["jd_mentions"]} for m in a["missing_skills"]
            ]
            st.table(rows)
        else:
            st.write("None")

    st.subheader("Suggestions")
    if a["sections_missing"]:
        st.warning("Sections not found: " + ", ".join(a["sections_missing"]))
    for s in a["suggestions"]:
        st.markdown(f"**{s['section'].capitalize()}**: {s['text']}")
    if not a["suggestions"]:
        st.write("No weak sections flagged.")
    st.caption(f"Analysis {a['id']} · {a['model_version']} · {a['latency_ms']} ms")


def show_coach(analysis_id: str) -> None:
    st.subheader("Ask the coach")
    st.caption(
        "Answers come only from your resume, this job description and the guidance library, "
        "with the passages they came from. The coach does not predict hiring outcomes."
    )
    history = st.session_state.setdefault("coach_history", {}).setdefault(analysis_id, [])
    for turn in history:
        st.markdown(f"**You:** {turn['question']}")
        st.markdown(turn["answer"])
        if turn["citations"]:
            with st.expander(f"Sources ({len(turn['citations'])})"):
                for c in turn["citations"]:
                    st.markdown(f"**[{c['id']}] {c['label']}** · {c['source']}")
                    st.write(c["text"])
    with st.form(f"coach_{analysis_id}", clear_on_submit=True):
        question = st.text_input(
            "Your question",
            max_chars=500,
            placeholder="How do I show deployment experience for this JD?",
        )
        sent = st.form_submit_button("Ask")
    if sent and question.strip():
        with st.spinner("Looking through the sources..."):
            data, error = api(
                "POST", "/coach", json={"analysis_id": analysis_id, "question": question}
            )
        if error:
            st.error(error)
        else:
            history.append(
                {"question": question, "answer": data["answer"], "citations": data["citations"]}
            )
            st.rerun()


tab_new, tab_saved = st.tabs(["New analysis", "Saved analyses"])

with tab_new:
    resume = st.file_uploader("Resume (PDF, up to 5 MB and 5 pages)", type=["pdf"])
    mode = st.radio("Job description", ["Paste text", "Upload PDF or DOCX"], horizontal=True)

    jd_source = "text"
    if mode == "Paste text":
        jd_text = st.text_area("Job description text (200 to 10,000 characters)", height=260)
    else:
        jd_file = st.file_uploader("Job description file", type=["pdf", "docx"])
        if jd_file is not None:
            file_key = f"{jd_file.name}:{jd_file.size}"
            if st.session_state.get("jd_file_key") != file_key:
                data, error = api(
                    "POST", "/jd/extract", files={"file": (jd_file.name, jd_file.getvalue())}
                )
                st.session_state["jd_file_key"] = file_key
                st.session_state["jd_extract"] = data
                st.session_state["jd_extract_error"] = error
                if data:
                    st.session_state["jd_edit"] = data["text"]
            if st.session_state.get("jd_extract_error"):
                st.error(st.session_state["jd_extract_error"])
            extract = st.session_state.get("jd_extract")
            if extract:
                jd_source = extract["source"]
                if extract.get("warning"):
                    st.warning(extract["warning"])
                st.write("Check the extracted text and edit it if needed before scoring.")
        jd_text = (
            st.text_area("Extracted job description", key="jd_edit", height=260)
            if st.session_state.get("jd_extract") and jd_file is not None
            else ""
        )

    store = st.checkbox(
        "Store my resume text with this analysis (off by default; "
        "the uploaded file itself is never kept)"
    )
    if st.button("Analyse fit", type="primary", disabled=resume is None or not jd_text.strip()):
        with st.spinner("Scoring..."):
            data, error = api(
                "POST",
                "/analyze",
                files={"resume": (resume.name, resume.getvalue(), "application/pdf")},
                data={
                    "jd_text": jd_text,
                    "jd_source": jd_source,
                    "store_resume_text": str(store).lower(),
                },
            )
        if error:
            st.error(error)
        else:
            st.session_state["last_analysis"] = data
    if st.session_state.get("last_analysis"):
        st.divider()
        show_analysis(st.session_state["last_analysis"])
        st.divider()
        show_coach(st.session_state["last_analysis"]["id"])

with tab_saved:
    rows, error = api("GET", "/analyses")
    if error:
        st.error(error)
    elif not rows:
        st.write("No saved analyses yet.")
    else:
        st.caption("Analyses are deleted automatically after 30 days. You can delete any now.")
        for row in rows:
            title = f"{row['created_at'][:16].replace('T', ' ')} · {row['score']} ({row['band']})"
            with st.expander(title):
                st.caption(row["jd_preview"] + "…")
                open_col, delete_col = st.columns(2)
                if open_col.button("Open", key=f"open_{row['id']}"):
                    detail, error = api("GET", f"/analyses/{row['id']}")
                    if error:
                        st.error(error)
                    else:
                        show_analysis(detail)
                if delete_col.button("Delete", key=f"del_{row['id']}"):
                    _, error = api("DELETE", f"/analyses/{row['id']}")
                    if error:
                        st.error(error)
                    else:
                        if st.session_state.get("last_analysis", {}).get("id") == row["id"]:
                            st.session_state.pop("last_analysis")
                        st.rerun()
