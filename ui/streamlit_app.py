"""Streamlit front end for the ResumeFit API.

Run the API first (uvicorn app.main:app), then:
    streamlit run ui/streamlit_app.py

The look (light theme, one dark accent) is set in .streamlit/config.toml and the
small style sheet below; run Streamlit from the repository root so it finds both.
"""

import html
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

st.set_page_config(page_title="ResumeFit", page_icon="◐", layout="centered")

STYLE = """
<style>
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display: none; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 760px; padding-top: 2.5rem; }
h1, h2, h3 { letter-spacing: -0.02em; }

.rf-brand { font-weight: 700; font-size: 1.15rem; letter-spacing: -0.02em; }
.rf-brand span { color: #9ca3af; font-weight: 500; }
.rf-hero { margin: 2.5rem 0 1.5rem; }
.rf-hero h1 { font-size: 2.2rem; font-weight: 700; margin: 0 0 .4rem; padding: 0; }
.rf-hero p { color: #6b7280; font-size: 1.02rem; margin: 0; }
.rf-label { font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: #6b7280; margin: 1.6rem 0 .55rem; }
.rf-muted { color: #6b7280; font-size: .9rem; }
.rf-small { color: #9ca3af; font-size: .8rem; }
.rf-or { display: flex; align-items: center; gap: .75rem; color: #9ca3af; font-size: .8rem;
  margin: .2rem 0 .6rem; }
.rf-or::before, .rf-or::after { content: ""; flex: 1; border-top: 1px solid #e5e7eb; }

.rf-score { font-size: 4.2rem; font-weight: 700; letter-spacing: -0.04em; line-height: 1; }
.rf-score small { font-size: 1.1rem; color: #9ca3af; font-weight: 500; letter-spacing: 0; }
.rf-band { display: inline-block; margin-top: .6rem; padding: 2px 10px; border-radius: 999px;
  font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  background: #f3f4f6; color: #374151; }
.rf-band.strong { background: #ecfdf5; color: #047857; }
.rf-band.partial { background: #fffbeb; color: #b45309; }
.rf-band.weak { background: #fef2f2; color: #b91c1c; }

.rf-bar { margin: .15rem 0 .75rem; }
.rf-bar-head { display: flex; justify-content: space-between; font-size: .85rem; color: #374151; }
.rf-bar-head span:last-child { color: #6b7280; font-variant-numeric: tabular-nums; }
.rf-track { height: 6px; background: #e5e7eb; border-radius: 999px; margin-top: 5px;
  overflow: hidden; }
.rf-fill { height: 100%; background: #111827; border-radius: 999px; }

.rf-chips { line-height: 2.1; }
.rf-chip { display: inline-block; padding: 2px 11px; margin: 0 4px 2px 0; border-radius: 999px;
  font-size: .82rem; border: 1px solid #e5e7eb; background: #fff; color: #374151; }
.rf-chip.ok { background: #ecfdf5; border-color: #a7f3d0; color: #065f46; }
.rf-chip.miss { background: #fff7ed; border-color: #fed7aa; color: #9a3412; }
.rf-chip em { font-style: normal; opacity: .6; margin-left: 4px; }

.rf-note { border-left: 3px solid #d1d5db; padding: .35rem .8rem; color: #4b5563;
  font-size: .9rem; margin: .5rem 0; background: #fff; border-radius: 0 6px 6px 0; }
.rf-suggestion { padding: .55rem 0; border-bottom: 1px solid #f0f0f0; font-size: .93rem; }
.rf-suggestion:last-child { border-bottom: none; }
.rf-suggestion b { font-weight: 600; }
.rf-clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; }
[data-testid="stChatMessageAvatarCustom"], [data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] { background: #e5e7eb !important; color: #374151; }
.rf-row-score { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


PRIVACY_NOTE = """
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

esc = html.escape


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def label(text: str) -> None:
    html_block(f'<div class="rf-label">{esc(text)}</div>')


# ---- API and Firebase plumbing --------------------------------------------------------
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


def google_button(text: str, key: str) -> dict | None:
    """Render the Google button; return a new sign-in result once, else None."""
    cfg = auth_config()
    value = _google_button(
        api_key=cfg["api_key"],
        auth_domain=cfg["auth_domain"],
        project_id=cfg["project_id"],
        label=text,
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


# ---- header -------------------------------------------------------------------------
def show_header(me: dict | None = None) -> None:
    brand, account = st.columns([3, 2], vertical_alignment="center")
    brand.markdown(
        '<div class="rf-brand">ResumeFit <span>· fit check</span></div>', unsafe_allow_html=True
    )
    if me is None:
        return
    with account, st.popover(me["email"], width="stretch"):
        usage = me["usage"]
        st.markdown(f"**{me['email']}**")
        if not me["email_verified"] and me["sign_in_provider"] == "password":
            st.caption("Your email is not verified yet.")
            if st.button("Send verification email", key="verify_email"):
                try:
                    firebase().send_verification_email(current_session())
                    st.success("Sent. Open the link, then sign in again.")
                except FirebaseError as exc:
                    st.error(str(exc))
        st.progress(
            min(usage["analyses_used"] / max(usage["analyses_limit"], 1), 1.0),
            text=f"Analyses today: {usage['analyses_used']} of {usage['analyses_limit']}",
        )
        st.progress(
            min(usage["coach_used"] / max(usage["coach_limit"], 1), 1.0),
            text=f"Coach questions today: {usage['coach_used']} of {usage['coach_limit']}",
        )
        st.caption(f"Limits reset at {usage['resets_at'][11:16]} UTC.")
        if st.button("Sign out", width="stretch"):
            sign_out()
            st.rerun()


# ---- sign-in, sign-up and consent ---------------------------------------------------------
def show_auth() -> None:
    """Sign in or create an account, with Google or with email and password."""
    show_header()
    html_block(
        '<div class="rf-hero"><h1>See how your resume fits.</h1>'
        "<p>Score it against a job description, see the gaps, and ask a coach "
        "what to change.</p></div>"
    )
    flash = st.session_state.pop("flash", None)
    if flash:
        st.info(flash)
    if auth_config() is None:
        st.error(
            "Sign-in is not configured. Set RESUMEFIT_FIREBASE_PROJECT_ID and "
            "RESUMEFIT_FIREBASE_API_KEY in the API's .env and restart it."
        )
        return

    mode = st.segmented_control(
        "Mode",
        ["Sign in", "Create account"],
        default="Sign in",
        key="auth_mode",
        label_visibility="collapsed",
    )
    with st.container(border=True):
        if mode == "Create account":
            show_sign_up()
        else:
            show_sign_in()


def show_sign_in() -> None:
    result = google_button("Continue with Google", key="google_sign_in")
    if result:
        start_session(google_session(result))
    html_block('<div class="rf-or">or</div>')
    with st.form("sign_in", border=False):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            try:
                start_session(firebase().sign_in(email, password))
            except FirebaseError as exc:
                st.error(str(exc))
    with st.expander("Forgot your password?"):
        with st.form("reset", border=False):
            reset_email = st.text_input("Email for the reset link")
            if st.form_submit_button("Send reset link"):
                try:
                    firebase().send_password_reset(reset_email)
                except FirebaseError as exc:
                    st.error(str(exc))
                else:
                    st.success("If an account exists for that email, a reset link is on its way.")


def show_sign_up() -> None:
    result = google_button("Sign up with Google", key="google_sign_up")
    if result:
        start_session(google_session(result))  # consent is asked on the next screen
    html_block('<div class="rf-or">or</div>')
    with st.form("sign_up", border=False):
        email = st.text_input("Email", key="signup_email", placeholder="you@example.com")
        password = st.text_input(
            "Password", type="password", key="signup_password", help="At least 6 characters."
        )
        privacy_note()
        consent = st.checkbox("I have read what ResumeFit stores and agree to it.")
        if st.form_submit_button("Create account", type="primary", width="stretch"):
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
                            pass  # they can resend it from the account menu
                        st.rerun()


def privacy_note(expanded: bool = False) -> None:
    with st.expander("What ResumeFit stores and why", expanded=expanded):
        st.markdown(PRIVACY_NOTE)
        health, _ = api("GET", "/health")
        if health:
            st.caption(f"Coach model in use: {health['coach_model_version']}")


def show_consent() -> None:
    """Signed in with Firebase, but no ResumeFit account yet (e.g. first Google sign-in)."""
    show_header()
    html_block(
        '<div class="rf-hero"><h1>One more step.</h1>'
        "<p>Read what ResumeFit keeps about you, then create your account.</p></div>"
    )
    with st.container(border=True):
        privacy_note(expanded=True)
        with st.form("consent", border=False):
            consent = st.checkbox("I have read the note above and agree to it.")
            if st.form_submit_button("Create my account", type="primary", width="stretch"):
                if not consent:
                    st.error("Please agree to the privacy note to continue.")
                else:
                    _, error = api("POST", "/auth/register", json={"consent": True})
                    if error:
                        st.error(error)
                    else:
                        st.rerun()
    if st.button("Use a different account", type="tertiary"):
        sign_out()
        st.rerun()


# ---- analysis, ratings and coach -----------------------------------------------------------
def show_rating(target_type: str, target_id: str, prompt: str, where: str) -> None:
    """Five stars for an analysis or a coach answer; sent as soon as one is picked."""
    sent = st.session_state.setdefault("rated", {})
    text, stars = st.columns([2, 3], vertical_alignment="center")
    text.markdown(f'<span class="rf-muted">{esc(prompt)}</span>', unsafe_allow_html=True)
    with stars:
        picked = st.feedback("stars", key=f"stars_{where}_{target_id}")
    if picked is None or sent.get(target_id) == picked + 1:
        return
    body = {"target_type": target_type, "target_id": target_id, "rating": picked + 1}
    _, error = api("POST", "/feedback", json=body)
    if error:
        st.error(error)
    else:
        sent[target_id] = picked + 1
        st.toast("Thanks, your rating was saved.")


def bar(name: str, value: float | None) -> str:
    if value is None:
        return (
            f'<div class="rf-bar"><div class="rf-bar-head"><span>{esc(name)}</span>'
            "<span>n/a</span></div></div>"
        )
    width = round(min(max(value, 0.0), 1.0) * 100)
    return (
        f'<div class="rf-bar"><div class="rf-bar-head"><span>{esc(name)}</span>'
        f"<span>{value:.2f}</span></div>"
        f'<div class="rf-track"><div class="rf-fill" style="width:{width}%"></div></div></div>'
    )


def chips(items: list[str], kind: str) -> str:
    return (
        '<div class="rf-chips">'
        + "".join(f'<span class="rf-chip {kind}">{item}</span>' for item in items)
        + "</div>"
    )


def show_analysis(a: dict, where: str) -> None:
    score_col, parts_col = st.columns([2, 3], gap="large", vertical_alignment="center")
    band = str(a["band"]).lower()
    score_col.markdown(
        f'<div class="rf-score">{int(a["score"])}<small> / 100</small></div>'
        f'<span class="rf-band {esc(band)}">{esc(band)}</span>',
        unsafe_allow_html=True,
    )
    parts_col.markdown(
        "".join(
            bar(name.replace("_", " ").capitalize(), value)
            for name, value in a["components"].items()
        ),
        unsafe_allow_html=True,
    )
    for note in a["notes"]:
        html_block(f'<div class="rf-note">{esc(note)}</div>')

    label("Matched skills")
    if a["matched_skills"]:
        html_block(chips([esc(s) for s in a["matched_skills"]], "ok"))
    else:
        html_block('<span class="rf-muted">None found.</span>')
    for m in a["semantic_matches"]:
        html_block(
            f'<div class="rf-small">"{esc(m["resume_phrase"])}" counted as '
            f"{esc(m['skill'])} (similar meaning)</div>"
        )

    label("Missing skills")
    if a["missing_skills"]:
        html_block(
            chips(
                [
                    f"{esc(m['skill'])}<em>×{int(m['jd_mentions'])}</em>"
                    for m in a["missing_skills"]
                ],
                "miss",
            )
        )
        html_block('<div class="rf-small">× = times the job description mentions it</div>')
    else:
        html_block('<span class="rf-muted">None. Every listed skill was found.</span>')

    label("Suggestions")
    rows = []
    if a["sections_missing"]:
        rows.append(f"<b>Sections not found</b>: {esc(', '.join(a['sections_missing']))}")
    rows += [f"<b>{esc(s['section'].capitalize())}</b>: {esc(s['text'])}" for s in a["suggestions"]]
    if rows:
        html_block("".join(f'<div class="rf-suggestion">{row}</div>' for row in rows))
    else:
        html_block('<span class="rf-muted">No weak sections flagged.</span>')

    st.write("")
    show_rating("analysis", a["id"], "Was this analysis useful?", where)
    html_block(
        f'<div class="rf-small">{esc(a["id"])} · {esc(a["model_version"])} · '
        f"{int(a['latency_ms'])} ms · a guide, not a hiring decision</div>"
    )


def show_coach(analysis_id: str) -> None:
    label("Ask the coach")
    html_block(
        '<div class="rf-muted">Answers come only from your resume, this job description and '
        "the guidance library, with their sources. The coach does not predict hiring "
        "outcomes.</div>"
    )
    st.write("")
    history = st.session_state.setdefault("coach_history", {}).setdefault(analysis_id, [])
    for turn in history:
        with st.chat_message("user", avatar=":material/person:"):
            st.write(turn["question"])
        with st.chat_message("assistant", avatar=":material/school:"):
            st.markdown(turn["answer"])
            if turn["citations"]:
                with st.expander(f"Sources · {len(turn['citations'])}"):
                    for c in turn["citations"]:
                        st.markdown(f"**[{c['id']}] {c['label']}** · {c['source']}")
                        st.caption(c["text"])
            if turn.get("id"):
                show_rating("coach_message", turn["id"], "Useful answer?", "coach")
    question = st.chat_input(
        "How do I show deployment experience for this job?",
        max_chars=500,
        key=f"coach_{analysis_id}",
    )
    if question and question.strip():
        with st.spinner("Reading the sources…"):
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


# ---- tabs ---------------------------------------------------------------------------
def show_new_analysis() -> None:
    label("Resume")
    resume = st.file_uploader(
        "Resume", type=["pdf"], label_visibility="collapsed", help="PDF, up to 5 MB and 5 pages."
    )

    label("Job description")
    mode = st.segmented_control(
        "Job description input",
        ["Paste text", "Upload file"],
        default="Paste text",
        key="jd_mode",
        label_visibility="collapsed",
    )
    jd_source = "text"
    if mode != "Upload file":
        jd_text = st.text_area(
            "Job description",
            height=220,
            label_visibility="collapsed",
            placeholder="Paste the job description here (200 to 10,000 characters).",
        )
    else:
        jd_file = st.file_uploader(
            "Job description file", type=["pdf", "docx"], label_visibility="collapsed"
        )
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
                st.caption("Check the extracted text and edit it if needed before scoring.")
        jd_text = (
            st.text_area("Extracted job description", key="jd_edit", height=220)
            if st.session_state.get("jd_extract") and jd_file is not None
            else ""
        )

    store = st.checkbox(
        "Keep my resume text with this analysis",
        help="Off by default. Short redacted passages are always kept for the coach; "
        "the uploaded file itself is never kept.",
    )
    ready = resume is not None and bool(jd_text.strip())
    if st.button("Analyse fit", type="primary", width="stretch", disabled=not ready):
        with st.spinner("Scoring…"):
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

    last = st.session_state.get("last_analysis")
    if last:
        st.divider()
        show_analysis(last, "new")
        st.divider()
        show_coach(last["id"])


def show_history() -> None:
    rows, error = api("GET", "/analyses")
    if error:
        st.error(error)
        return
    if not rows:
        html_block('<div class="rf-muted" style="margin-top:1rem">No saved analyses yet.</div>')
        return
    html_block(
        '<div class="rf-small" style="margin:.5rem 0 1rem">Analyses are deleted '
        "automatically after 30 days.</div>"
    )
    for row in rows:
        with st.container(border=True):
            score, text, actions = st.columns([1, 5, 2], vertical_alignment="center")
            score.markdown(
                f'<div class="rf-row-score">{int(row["score"])}</div>'
                f'<span class="rf-band {esc(str(row["band"]).lower())}">'
                f"{esc(str(row['band']))}</span>",
                unsafe_allow_html=True,
            )
            text.markdown(
                f'<div class="rf-small">{esc(row["created_at"][:16].replace("T", " "))}</div>'
                f'<div class="rf-muted rf-clamp">{esc(" ".join(row["jd_preview"].split()))}…</div>',
                unsafe_allow_html=True,
            )
            opened = st.session_state.get("opened") == row["id"]
            with actions:
                if st.button(
                    "Close" if opened else "Open", key=f"open_{row['id']}", width="stretch"
                ):
                    st.session_state["opened"] = None if opened else row["id"]
                    st.rerun()
                if st.button("Delete", key=f"del_{row['id']}", type="tertiary", width="stretch"):
                    _, error = api("DELETE", f"/analyses/{row['id']}")
                    if error:
                        st.error(error)
                    else:
                        if st.session_state.get("last_analysis", {}).get("id") == row["id"]:
                            st.session_state.pop("last_analysis")
                        st.rerun()
            if opened:
                detail, error = api("GET", f"/analyses/{row['id']}")
                if error:
                    st.error(error)
                else:
                    st.divider()
                    show_analysis(detail, "history")


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
    label("Signed in")
    provider = "Google" if me["sign_in_provider"] == "google.com" else "email and password"
    html_block(f'<div>{esc(me["email"])}</div><div class="rf-small">with {provider}</div>')

    label("Privacy")
    privacy_note()

    label("Delete account")
    html_block(
        '<div class="rf-muted">Deletes your account, all analyses, resume passages, coach '
        "messages, ratings and usage records, and your Firebase sign-in. This cannot be "
        "undone.</div>"
    )
    st.write("")
    if not st.toggle("I want to delete everything", key="delete_sure"):
        return
    if me["sign_in_provider"] == "google.com":
        result = google_button("Confirm with Google and delete", key="google_delete")
        if result:
            delete_everything(google_session(result))
    else:
        with st.form("delete_account", border=False):
            password = st.text_input("Confirm with your password", type="password")
            if st.form_submit_button("Delete my account", type="primary"):
                try:
                    fresh = firebase().sign_in(me["email"], password)
                except FirebaseError as exc:
                    st.error(str(exc))
                else:
                    delete_everything(fresh)


def show_admin() -> None:
    days = st.segmented_control(
        "Window", [1, 7, 14, 30], default=7, format_func=lambda d: f"{d} d", key="admin_days"
    )
    m, error = api("GET", f"/admin/metrics?days={days or 7}")
    if error:
        st.error(error)
        return
    for flag in m["flags"]:
        st.error(flag)
    if not m["flags"]:
        st.success("No flags for this window.")

    req = m["requests"]
    top = st.columns(3)
    top[0].metric("Requests", req["requests"])
    rate = req["server_error_rate"]
    top[1].metric("Server errors", "n/a" if rate is None else f"{rate:.1%}")
    top[2].metric("Quota hits", m["quota_hits"]["total"])
    lat = st.columns(2)
    for col, path in zip(lat, ("/analyze", "/coach"), strict=True):
        p = req["latency"].get(path)
        col.metric(f"{path} p95", f"{p['p95_ms']} ms" if p else "n/a")

    scores = m["scores"]
    label("Score distribution")
    st.caption(
        f"{scores['count']} analyses, mean {scores['mean']}, "
        f"missing sections in {scores['missing_sections_share']} of resumes"
    )
    st.bar_chart(pd.DataFrame(scores["histogram"]).set_index("bucket"), color="#111827")

    ratings = m["ratings"]
    label("Rating trend")
    st.caption(f"{ratings['count']} ratings, mean {ratings['mean']}")
    trend = pd.DataFrame(ratings["by_day"])
    if not trend.empty:
        st.line_chart(trend.set_index("day")[["mean"]], color="#111827")

    drift = m["drift"]
    label("Drift (latest week against the first)")
    st.write(f"Status: **{drift['status']}**")
    for reason in drift.get("reasons", []):
        st.write(f"- {reason}")
    with st.expander("Details"):
        st.json(drift)

    usage = m["usage"]
    label("Usage")
    st.caption(
        f"{usage['active_users']} active users, {usage['analyses']} analyses, "
        f"{usage['coach_messages']} coach questions"
    )
    if usage["top_users"]:
        st.dataframe(usage["top_users"], hide_index=True)
    label("Requests by endpoint")
    st.dataframe(
        [{"endpoint": k, "requests": v} for k, v in req["by_path"].items()], hide_index=True
    )


# ---- page -----------------------------------------------------------------------------
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
    show_header()
    st.error(me_error)
    st.stop()
st.session_state["user"] = me
show_header(me)
st.write("")

tab_names = ["Analyse", "History", "Account"] + (["Admin"] if me["is_admin"] else [])
tabs = st.tabs(tab_names)
with tabs[0]:
    show_new_analysis()
with tabs[1]:
    show_history()
with tabs[2]:
    show_account(me)
if me["is_admin"]:
    with tabs[3]:
        show_admin()
