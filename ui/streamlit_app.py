"""Streamlit front end for the ResumeFit API.

Run the API first (uvicorn app.main:app), then:
    streamlit run ui/streamlit_app.py
"""

import os
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from firebase_client import FirebaseClient, FirebaseError, FirebaseSession

API_URL = os.environ.get("RESUMEFIT_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 60

# "Sign in with Google" runs Firebase's own JavaScript in a small component (a popup
# is needed); email and password go through Firebase's REST API in firebase_client.py.
_google_button = components.declare_component(
    "firebase_google", path=str(Path(__file__).resolve().parent / "firebase_google")
)

st.set_page_config(page_title="ResumeFit", layout="wide")
st.title("ResumeFit")
st.caption(
    "Scores your resume against a job description and explains the gaps. "
    "The score is a guide to improving a resume, not a hiring decision, and it can be wrong."
)


PRIVACY_NOTE = """
**What ResumeFit stores and why**

- Sign-in is handled by **Firebase Authentication**, a Google service. It stores your
  email and either your password (hashed by Firebase; ResumeFit never sees it) or your
  Google identity. ResumeFit itself stores your email, your Firebase user id and when
  you agreed to this note.
- For each analysis: the job description, the score and gap report, and short passages
  from your resume with your name and contact details removed, so the coach can answer
  questions about it. Your full resume text is stored only if you tick the box for that
  analysis. Uploaded files are never kept.
- Your coach questions (contact details removed), the answers, and any ratings you give.
- Analyses with their passages and coach messages are deleted after 30 days, or at once
  when you delete them. Deleting your account deletes everything linked to you here and
  your Firebase sign-in.
- An anonymous copy of each score, with no link to you, is kept to check that scoring
  stays stable over time.
- If the coach uses a language model, only redacted passages and your question are sent
  to it. The model in use is shown below.

The score is a guide to improving a resume, not a hiring decision, and it can be wrong.
"""


def auth_config() -> dict | None:
    """Public Firebase settings, served by the API from its .env."""
    if "auth_config" not in st.session_state:
        try:
            response = requests.get(f"{API_URL}/auth/config", timeout=TIMEOUT)
            cfg = response.json() if response.ok else None
        except (requests.RequestException, ValueError):
            cfg = None
        if not cfg or not cfg.get("api_key") or not cfg.get("project_id"):
            return None
        st.session_state["auth_config"] = cfg
    return st.session_state["auth_config"]


def firebase() -> FirebaseClient:
    return FirebaseClient(auth_config()["api_key"])


def google_button(label: str, key: str) -> dict | None:
    """Render the Google button; return a new sign-in result once, else None."""
    cfg = auth_config()
    value = _google_button(
        api_key=cfg["api_key"],
        auth_domain=cfg["auth_domain"],
        project_id=cfg["project_id"],
        label=label,
        key=key,
        default=None,
    )
    seen = st.session_state.setdefault("google_nonces", set())
    if not value or value.get("nonce") in seen:
        return None
    seen.add(value["nonce"])
    return value


def google_session(value: dict) -> FirebaseSession:
    # Firebase ID tokens last one hour; the refresh token renews them.
    return FirebaseSession(
        id_token=value["id_token"],
        refresh_token=value["refresh_token"],
        expires_at=time.time() + 3500,
        provider="google.com",
    )


def current_session() -> FirebaseSession | None:
    """The Firebase session, refreshed when its token is about to expire."""
    session = st.session_state.get("fb")
    if session is None:
        return None
    if session.expires_soon():
        try:
            session = firebase().refresh(session)
        except FirebaseError as exc:
            sign_out(str(exc))
            return None
        st.session_state["fb"] = session
    return session


def api_full(method: str, path: str, **kwargs):
    """Call the API as the signed-in user. Returns (data, error_message, error_code)."""
    session = current_session()
    headers = {"Authorization": f"Bearer {session.id_token}"} if session else {}
    try:
        response = requests.request(
            method, f"{API_URL}{path}", timeout=TIMEOUT, headers=headers, **kwargs
        )
    except requests.RequestException:
        return None, f"Cannot reach the API at {API_URL}. Is it running?", "unreachable"
    if response.status_code == 204:
        return {}, None, None
    try:
        body = response.json()
    except ValueError:
        return None, f"Unexpected response ({response.status_code}).", "bad_response"
    if response.ok:
        return body, None, None
    error = body.get("error", {})
    code = error.get("code", f"http_{response.status_code}")
    message = error.get("message", f"Error {response.status_code}.")
    if code in ("invalid_token", "not_authenticated") and session:
        sign_out("Your session has ended. Please sign in again.")
    return None, message, code


def api(method: str, path: str, **kwargs):
    """Call the API. Returns (data, error_message)."""
    data, error, _ = api_full(method, path, **kwargs)
    return data, error


def sign_out(flash: str | None = None) -> None:
    for key in ("fb", "user", "last_analysis", "coach_history", "opened", "jd_extract"):
        st.session_state.pop(key, None)
    if flash:
        st.session_state["flash"] = flash


def start_session(session: FirebaseSession) -> None:
    st.session_state["fb"] = session
    st.rerun()


def show_auth() -> None:
    """Sign in or create an account, with Google or with email and password."""
    flash = st.session_state.pop("flash", None)
    if flash:
        st.info(flash)
    if auth_config() is None:
        st.error(
            "Sign-in is not configured. Set RESUMEFIT_FIREBASE_PROJECT_ID and "
            "RESUMEFIT_FIREBASE_API_KEY in the API's .env and restart it."
        )
        return
    health, _ = api("GET", "/health")
    sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])

    with sign_in_tab:
        result = google_button("Sign in with Google", key="google_sign_in")
        if result:
            start_session(google_session(result))
        st.caption("or with email and password")
        with st.form("sign_in"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    start_session(firebase().sign_in(email, password))
                except FirebaseError as exc:
                    st.error(str(exc))
        with st.expander("Forgot your password?"):
            with st.form("reset"):
                reset_email = st.text_input("Email for the reset link")
                if st.form_submit_button("Send reset link"):
                    try:
                        firebase().send_password_reset(reset_email)
                    except FirebaseError as exc:
                        st.error(str(exc))
                    else:
                        st.success(
                            "If an account exists for that email, a reset link is on its way."
                        )

    with sign_up_tab:
        st.markdown(PRIVACY_NOTE)
        if health:
            st.caption(f"Coach model in use: {health['coach_model_version']}")
        result = google_button("Sign up with Google", key="google_sign_up")
        if result:
            start_session(google_session(result))  # consent is asked on the next screen
        st.caption("or with email and password")
        with st.form("sign_up"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input(
                "Password (at least 6 characters)", type="password", key="signup_password"
            )
            consent = st.checkbox("I have read the note above and agree to it.")
            if st.form_submit_button("Create account", type="primary"):
                if not consent:
                    st.error("Please agree to the privacy note to create an account.")
                else:
                    try:
                        session = firebase().sign_up(email, password)
                    except FirebaseError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["fb"] = session
                        _, error = api("POST", "/auth/register", json={"consent": True})
                        if error:
                            st.error(error)
                        else:
                            try:
                                firebase().send_verification_email(session)
                            except FirebaseError:
                                pass  # they can resend it from the sidebar
                            st.rerun()


def show_consent() -> None:
    """Signed in with Firebase, but no ResumeFit account yet (e.g. first Google sign-in)."""
    st.subheader("One more step")
    st.markdown(PRIVACY_NOTE)
    with st.form("consent"):
        consent = st.checkbox("I have read the note above and agree to it.")
        if st.form_submit_button("Create my ResumeFit account", type="primary"):
            if not consent:
                st.error("Please agree to the privacy note to continue.")
            else:
                _, error = api("POST", "/auth/register", json={"consent": True})
                if error:
                    st.error(error)
                else:
                    st.rerun()
    if st.button("Use a different account"):
        sign_out()
        st.rerun()


def show_feedback(target_type: str, target_id: str, prompt: str) -> None:
    """A 1-5 rating with an optional comment for an analysis or a coach answer."""
    done = st.session_state.setdefault("rated", {})
    with st.form(f"rate_{target_type}_{target_id}"):
        rating = st.select_slider(prompt, options=[1, 2, 3, 4, 5], value=done.get(target_id, 4))
        comment = st.text_input("Comment (optional)", max_chars=1000)
        if st.form_submit_button("Send rating"):
            body = {"target_type": target_type, "target_id": target_id, "rating": rating}
            if comment.strip():
                body["comment"] = comment
            _, error = api("POST", "/feedback", json=body)
            if error:
                st.error(error)
            else:
                done[target_id] = rating
                st.success("Thanks, your rating was saved.")


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
        if turn.get("id"):
            show_feedback("coach_message", turn["id"], "Was this answer useful? (1 to 5)")
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
                {
                    "id": data["id"],
                    "question": question,
                    "answer": data["answer"],
                    "citations": data["citations"],
                }
            )
            st.rerun()


def show_usage_sidebar(me: dict) -> None:
    usage = me["usage"]
    with st.sidebar:
        st.write(f"Signed in as **{me['email']}**")
        if not me["email_verified"] and me["sign_in_provider"] == "password":
            st.warning("Your email is not verified yet.")
            if st.button("Send verification email"):
                try:
                    firebase().send_verification_email(current_session())
                    st.success("Sent. Open the link, then sign in again.")
                except FirebaseError as exc:
                    st.error(str(exc))
        st.caption(f"Today (UTC {usage['day']})")
        st.progress(
            min(usage["analyses_used"] / max(usage["analyses_limit"], 1), 1.0),
            text=f"Analyses: {usage['analyses_used']} of {usage['analyses_limit']}",
        )
        st.progress(
            min(usage["coach_used"] / max(usage["coach_limit"], 1), 1.0),
            text=f"Coach questions: {usage['coach_used']} of {usage['coach_limit']}",
        )
        st.caption(f"Limits reset at {usage['resets_at'][11:16]} UTC.")
        if st.button("Sign out"):
            sign_out()
            st.rerun()


def delete_everything(session: FirebaseSession) -> None:
    """Delete the ResumeFit data, then the Firebase sign-in, with a fresh token."""
    st.session_state["fb"] = session
    _, error = api("DELETE", "/auth/me")
    if error:
        st.error(error)
        return
    try:
        firebase().delete_account(session)
        message = "Your account, your data and your sign-in were deleted."
    except FirebaseError as exc:
        message = (
            "Your ResumeFit data was deleted, but your Firebase sign-in could not be removed "
            f"({exc}). Signing in again will ask for consent to a new, empty account."
        )
    sign_out(message)
    st.rerun()


def show_account(me: dict) -> None:
    st.markdown(PRIVACY_NOTE)
    st.subheader("Delete my account")
    st.write(
        "This deletes your account, all your analyses, resume passages, coach messages, "
        "ratings and usage records, and your Firebase sign-in. It cannot be undone. "
        "You will be asked to confirm who you are first."
    )
    sure = st.checkbox("Yes, delete everything.", key="delete_sure")
    if not sure:
        return
    if me["sign_in_provider"] == "google.com":
        result = google_button("Confirm with Google and delete", key="google_delete")
        if result:
            delete_everything(google_session(result))
    else:
        with st.form("delete_account"):
            password = st.text_input("Confirm with your password", type="password")
            if st.form_submit_button("Delete my account"):
                try:
                    fresh = firebase().sign_in(me["email"], password)
                except FirebaseError as exc:
                    st.error(str(exc))
                else:
                    delete_everything(fresh)


def show_admin() -> None:
    days = st.select_slider("Window (days)", options=[1, 7, 14, 30], value=7)
    m, error = api("GET", f"/admin/metrics?days={days}")
    if error:
        st.error(error)
        return
    for flag in m["flags"]:
        st.error(flag)
    if not m["flags"]:
        st.success("No flags for this window.")

    req = m["requests"]
    cols = st.columns(5)
    cols[0].metric("Requests", req["requests"])
    rate = req["server_error_rate"]
    cols[1].metric("Server error rate", "n/a" if rate is None else f"{rate:.1%}")
    for col, path in zip(cols[2:4], ("/analyze", "/coach"), strict=True):
        lat = req["latency"].get(path)
        col.metric(f"{path} p95", f"{lat['p95_ms']} ms" if lat else "n/a")
    cols[4].metric("Quota hits", m["quota_hits"]["total"])

    left, right = st.columns(2)
    with left:
        st.subheader("Score distribution")
        scores = m["scores"]
        st.caption(
            f"{scores['count']} analyses, mean {scores['mean']}, "
            f"missing sections in {scores['missing_sections_share']} of resumes"
        )
        hist = pd.DataFrame(scores["histogram"]).set_index("bucket")
        st.bar_chart(hist)
    with right:
        st.subheader("Rating trend")
        ratings = m["ratings"]
        st.caption(f"{ratings['count']} ratings, mean {ratings['mean']}")
        trend = pd.DataFrame(ratings["by_day"]).set_index("day")[["mean"]]
        st.line_chart(trend)

    st.subheader("Drift check (latest week against the first week)")
    drift = m["drift"]
    st.write(f"Status: **{drift['status']}**")
    for reason in drift.get("reasons", []):
        st.write(f"- {reason}")
    with st.expander("Details"):
        st.json(drift)

    st.subheader("Usage")
    usage = m["usage"]
    st.caption(
        f"{usage['active_users']} active users, {usage['analyses']} analyses, "
        f"{usage['coach_messages']} coach questions"
    )
    if usage["top_users"]:
        st.table(usage["top_users"])
    st.subheader("Requests by endpoint")
    st.table([{"endpoint": k, "requests": v} for k, v in req["by_path"].items()])


if current_session() is None:
    show_auth()
    st.stop()

me, me_error, me_code = api_full("GET", "/auth/me")
if me_code == "registration_required":
    show_consent()
    st.stop()
if me_error:
    if current_session() is None:  # the session ended; show the sign-in page
        st.rerun()
    st.error(me_error)
    st.stop()
st.session_state["user"] = me
show_usage_sidebar(me)
is_admin = me["is_admin"]
tab_names = ["New analysis", "Saved analyses", "Account"] + (["Admin"] if is_admin else [])
tabs = st.tabs(tab_names)
tab_new, tab_saved, tab_account = tabs[0], tabs[1], tabs[2]

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
        show_feedback(
            "analysis",
            st.session_state["last_analysis"]["id"],
            "How useful was this analysis? (1 to 5)",
        )
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
                    st.session_state["opened"] = row["id"]
                if st.session_state.get("opened") == row["id"]:
                    detail, error = api("GET", f"/analyses/{row['id']}")
                    if error:
                        st.error(error)
                    else:
                        show_analysis(detail)
                        show_feedback(
                            "analysis", row["id"], "How useful was this analysis? (1 to 5)"
                        )
                if delete_col.button("Delete", key=f"del_{row['id']}"):
                    _, error = api("DELETE", f"/analyses/{row['id']}")
                    if error:
                        st.error(error)
                    else:
                        if st.session_state.get("last_analysis", {}).get("id") == row["id"]:
                            st.session_state.pop("last_analysis")
                        st.rerun()

with tab_account:
    show_account(me)

if is_admin:
    with tabs[3]:
        show_admin()
