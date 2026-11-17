// ResumeFit web front end: plain JavaScript, no build step.
// Sign-in runs in the browser with Firebase's own SDK; everything else is the ResumeFit API.

import { API_URL, COACH_PROVIDER, COACH_PROVIDER_NOTE } from "./config.js";
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  EmailAuthProvider,
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  deleteUser,
  getAuth,
  onAuthStateChanged,
  reauthenticateWithCredential,
  reauthenticateWithPopup,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

// ---- state ----------------------------------------------------------------------------
const S = {
  auth: null,
  user: null, // Firebase user
  me: null, // GET /auth/me
  needsConsent: false,
  meError: null,
  ready: false, // first auth state known
  waking: false, // the API is slow to answer (free hosting sleeps)
  configError: null,
  registering: false,
  authError: null,
  authInfo: null,
  showReset: false,
  // analyse
  resume: null, // File, kept for the visit
  jdMode: "paste",
  jdText: "",
  jdSource: "text",
  jdNote: null,
  store: false,
  busy: false,
  error: null,
  analysis: null,
  coach: new Map(), // analysis id -> [{q, pending, error, id, answer, status, citations}]
  rated: new Map(), // target id -> stars
  // pages that load data
  history: { loading: false, items: null, error: null, confirm: null },
  admin: { loading: false, data: null, error: null, days: 7 },
  health: null,
};

const view = document.getElementById("view");
const nav = document.getElementById("nav");
const LIMITS = { jdMin: 200, jdMax: 10000, resumeMb: 5, qMin: 5, qMax: 500 };
const BAND_WORDS = { strong: "Strong match", partial: "Partial match", weak: "Weak match" };
const SOURCE_NAMES = { resume: "Your resume", jd: "Job description", guidance: "Guide" };
const PRIVATE = ["analyse", "history", "account", "admin"];

// ---- small helpers --------------------------------------------------------------------
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const route = () => location.hash.replace(/^#\/?/, "").split("?")[0];
const go = (r) => {
  if (route() === r) render();
  else location.hash = "#/" + r;
};
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const toDate = (s) => new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
const fmtDate = (s) =>
  toDate(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const spinner = '<span class="spin" aria-hidden="true"></span>';

function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 2600);
}

class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function api(method, path, { json, form } = {}) {
  const headers = {};
  if (S.user) headers.Authorization = "Bearer " + (await S.user.getIdToken());
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) body = form;
  let res;
  try {
    res = await fetch(API_URL + path, { method, headers, body });
  } catch {
    throw new ApiError(
      "unreachable",
      "Can't reach the ResumeFit server. If it was asleep it can take up to a minute to wake up, so please try again.",
    );
  }
  if (res.status === 204) return null;
  let data;
  try {
    data = await res.json();
  } catch {
    throw new ApiError("bad_response", `Unexpected response from the server (${res.status}).`, res.status);
  }
  if (!res.ok) {
    const e = data.error || {};
    const err = new ApiError(e.code || `http_${res.status}`, e.message || `Error ${res.status}.`, res.status);
    if (["invalid_token", "not_authenticated"].includes(err.code) && S.user) {
      await doSignOut("Your session has ended. Please sign in again.");
    }
    throw err;
  }
  return data;
}

const FIREBASE_MESSAGES = {
  "auth/invalid-credential": "Wrong email or password.",
  "auth/wrong-password": "Wrong password.",
  "auth/user-not-found": "No account uses that email.",
  "auth/email-already-in-use": "An account already uses that email. Sign in instead.",
  "auth/weak-password": "Use a password of at least 6 characters.",
  "auth/invalid-email": "That email address doesn't look right.",
  "auth/missing-password": "Enter your password.",
  "auth/too-many-requests": "Too many attempts. Wait a few minutes and try again.",
  "auth/network-request-failed": "Network problem. Check your connection and try again.",
  "auth/popup-blocked": "Your browser blocked the Google window. Allow pop-ups for this site and try again.",
  "auth/unauthorized-domain":
    "This site's address isn't allowed to sign in yet. Add it under Firebase → Authentication → Settings → Authorized domains.",
  "auth/operation-not-allowed": "This sign-in method is turned off in Firebase.",
  "auth/requires-recent-login": "For safety, confirm your sign-in again and retry.",
};
const SILENT = ["auth/popup-closed-by-user", "auth/cancelled-popup-request"];
const fbMessage = (e) => FIREBASE_MESSAGES[e?.code] || e?.message || "Something went wrong.";

// ---- boot and auth --------------------------------------------------------------------
async function boot() {
  const slow = setTimeout(() => {
    S.waking = true;
    render();
  }, 2500);
  let cfg;
  try {
    const res = await fetch(API_URL + "/auth/config");
    cfg = await res.json();
  } catch {
    cfg = null;
  }
  clearTimeout(slow);
  S.waking = false;
  if (!cfg || !cfg.api_key || !cfg.project_id) {
    S.configError = cfg
      ? "Sign-in isn't configured on the server yet."
      : "Can't reach the ResumeFit server right now. Please try again in a minute.";
    S.ready = true;
    render();
    return;
  }
  const app = initializeApp({ apiKey: cfg.api_key, authDomain: cfg.auth_domain, projectId: cfg.project_id });
  S.auth = getAuth(app);
  onAuthStateChanged(S.auth, async (user) => {
    const same = user && S.user && user.uid === S.user.uid;
    S.user = user;
    if (!same) {
      S.me = null;
      S.needsConsent = false;
      S.meError = null;
    }
    if (user && !S.registering && !S.me) await loadMe();
    S.ready = true;
    render();
  });
}

async function loadMe() {
  try {
    S.me = await api("GET", "/auth/me");
    S.needsConsent = false;
    S.meError = null;
  } catch (e) {
    S.me = null;
    if (e.code === "registration_required") S.needsConsent = true;
    else S.meError = e.message;
  }
}

async function refreshUsage() {
  try {
    S.me = await api("GET", "/auth/me");
  } catch {
    /* the next page load will show it */
  }
}

async function doSignOut(info) {
  S.me = null;
  S.needsConsent = false;
  S.analysis = null;
  S.resume = null;
  S.jdText = "";
  S.coach.clear();
  S.rated.clear();
  S.history = { loading: false, items: null, error: null, confirm: null };
  S.authInfo = info || null;
  if (S.auth) await signOut(S.auth);
  go(info ? "signin" : "");
}

// ---- nav ----------------------------------------------------------------------------------
function renderNav(r) {
  if (S.user && S.me) {
    const tabs = [
      ["analyse", "Analyse"],
      ["history", "History"],
      ["account", "Account"],
    ];
    if (S.me.is_admin) tabs.push(["admin", "Admin"]);
    nav.innerHTML = tabs
      .map(([k, t]) => `<a href="#/${k}" class="${r === k ? "on" : ""}" ${r === k ? 'aria-current="page"' : ""}>${t}</a>`)
      .join("");
  } else if (r === "signin" || r === "signup") {
    nav.innerHTML = "";
  } else {
    nav.innerHTML = `<a href="#/signin">Sign in</a>`;
  }
}

// ---- render -------------------------------------------------------------------------------
function render() {
  const r = route();
  renderNav(r);
  let html;
  if (r === "privacy") html = viewPrivacy();
  else if (r === "terms") html = viewTerms();
  else if (r === "") html = viewLanding();
  else if (!S.ready) html = viewLoading();
  else if (S.configError) html = viewMessage("Service unavailable", S.configError);
  else if (r === "signin" || r === "signup") {
    if (S.user && S.me) return go("analyse");
    html = S.user && S.needsConsent ? viewConsent() : viewAuth(r);
  } else if (PRIVATE.includes(r)) {
    if (!S.user) return go("signin");
    if (S.needsConsent) html = viewConsent();
    else if (!S.me) html = viewMessage("Couldn't load your account", S.meError || "Please reload the page.");
    else if (r === "admin" && !S.me.is_admin) html = viewMessage("Not available", "This page is for administrators.");
    else html = { analyse: viewAnalyse, history: viewHistory, account: viewAccount, admin: viewAdmin }[r]();
  } else html = viewMessage("Page not found", "That page doesn't exist.", true);
  view.innerHTML = html;
}

function onRoute() {
  const r = route();
  if (r === "history") loadHistory();
  if (r === "admin") loadAdmin();
  if (r === "privacy") loadHealth();
  render();
  window.scrollTo(0, 0);
  view.focus({ preventScroll: true });
}

const viewLoading = () =>
  S.waking
    ? `<div class="empty" style="margin-top:40px"><b>Waking up the server…</b>
        <span class="muted">ResumeFit runs on free hosting that sleeps when nobody is using it. This can take up to a minute.</span></div>`
    : `<div class="skeleton" style="width:60%;margin-top:40px"></div><div class="skeleton" style="width:40%"></div>`;

const viewMessage = (title, text, home) => `
  <div class="empty" style="margin-top:40px"><b>${esc(title)}</b><span class="muted">${esc(text)}</span>
  ${home ? '<p><a class="btn" href="#/">Go home</a></p>' : ""}</div>`;

// ---- landing ------------------------------------------------------------------------------
function viewLanding() {
  const signedIn = S.user && S.me;
  const sample = {
    score: 64,
    band: "partial",
    components: { skill_overlap: 0.58, semantic_similarity: 0.71 },
  };
  return `
  <section class="land">
    <h1>See how your resume fits the job.</h1>
    <p class="lead">Score your resume against a job description, see exactly which skills are missing, and ask a coach what to change.</p>
    <div class="cta">
      ${
        signedIn
          ? '<a class="btn primary lg" href="#/analyse">Open ResumeFit</a>'
          : '<a class="btn primary lg" href="#/signup">Get started, it\'s free</a><a class="btn lg" href="#/signin">Sign in</a>'
      }
    </div>
    <div class="card preview" aria-label="Example result">
      <div class="row-between" style="margin-bottom:10px"><span class="label" style="margin:0">Example result</span><span class="small">illustration</span></div>
      <div class="result-head">
        <div class="ring">${ring(sample.score, sample.band, 116)}</div>
        <div>
          <span class="band partial">partial</span>
          <div class="verdict">Partial match. You cover 7 of 12 skills this job lists.</div>
          ${bars(sample.components)}
        </div>
      </div>
      <div class="start"><div class="start-k">Start here</div><div><b>docker</b> is the biggest gap: the job description mentions it 4×.</div></div>
    </div>
  </section>
  <section class="features">
    <div class="feature"><b>A clear score</b><span>Skill coverage and meaning-level similarity, combined into one number with the reasons shown.</span></div>
    <div class="feature"><b>The gaps, ranked</b><span>Missing skills ordered by how often the job asks for them, plus weak or missing resume sections.</span></div>
    <div class="feature"><b>A coach that cites</b><span>Ask follow-up questions. Every answer points to the line in your resume, the job or the guide it came from.</span></div>
  </section>
  <div class="label" style="margin-top:44px">How it works</div>
  <div class="steps-how">
    <div>Upload your resume as a PDF.</div>
    <div>Paste the job description, or upload it as a PDF or Word file.</div>
    <div>Read the score and the gaps, then ask the coach how to close them.</div>
  </div>
  <p class="small" style="margin-top:32px">The score is a guide to improving a resume, not a hiring decision, and it can be wrong. Your contact details are removed before anything is stored. <a href="#/privacy">Privacy</a></p>`;
}

// ---- sign in / sign up / consent ------------------------------------------------------------
const GOOGLE_ICON = `<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>`;

function privacyList() {
  const coach = COACH_PROVIDER
    ? `The coach sends short passages (name and contact details removed) and your question to <b>${esc(COACH_PROVIDER)}</b> to write its answer. ${esc(COACH_PROVIDER_NOTE)}`
    : "The coach's language model runs on ResumeFit's own server; no text is sent to another company.";
  return `<ul>
    <li>Sign-in is handled by Firebase Authentication (Google). ResumeFit stores your email, your Firebase user id and when you agreed to this note. It never sees your password.</li>
    <li>For each analysis: the job description, the score and gap report, and short passages from your resume with your name and contact details removed. Your full resume text is stored only if you tick the box for that analysis. Uploaded files are never kept.</li>
    <li>Your coach questions (contact details removed), the answers and any ratings you give.</li>
    <li>${coach}</li>
    <li>Analyses are deleted after 30 days, or at once when you delete them. Deleting your account deletes everything linked to you, including your sign-in.</li>
    <li>An anonymous copy of each score, with no link to you, is kept to check that scoring stays stable.</li>
  </ul>`;
}

const authErrorHtml = () => (S.authError ? `<div class="alert error" role="alert">${esc(S.authError)}</div>` : "");

function viewAuth(r) {
  const up = r === "signup";
  const err = `<div id="auth-error">${authErrorHtml()}</div>`;
  const info = S.authInfo ? `<div class="alert">${esc(S.authInfo)}</div>` : "";
  const reset = S.showReset
    ? `<form data-form="reset" class="card" style="margin-top:12px;padding:16px">
        <label class="field"><span>Email for the reset link</span><input type="email" name="email" required autocomplete="email"></label>
        <button class="btn block">Send reset link</button></form>`
    : "";
  return `
  <div class="narrow">
    <div class="hero center"><h1>${up ? "Create your account" : "Welcome back"}</h1>
      <p>${up ? "Free. Takes a minute." : "Sign in to see your analyses."}</p></div>
    <div class="center" style="margin-bottom:16px"><div class="seg" role="tablist">
      <button class="${up ? "" : "on"}" data-act="goto" data-to="signin" role="tab" aria-selected="${!up}">Sign in</button>
      <button class="${up ? "on" : ""}" data-act="goto" data-to="signup" role="tab" aria-selected="${up}">Create account</button>
    </div></div>
    <div class="card">
      ${info}${err}
      <button class="btn block" data-act="google">${GOOGLE_ICON} Continue with Google</button>
      <div class="or">or</div>
      <form data-form="${up ? "signup" : "signin"}">
        <label class="field"><span>Email</span><input type="email" name="email" required autocomplete="email" placeholder="you@example.com"></label>
        <label class="field"><span>Password</span><input type="password" name="password" required minlength="6"
          autocomplete="${up ? "new-password" : "current-password"}" ${up ? 'placeholder="At least 6 characters"' : ""}></label>
        ${
          up
            ? `<details class="more"><summary>What ResumeFit stores and why</summary>${privacyList()}</details>
               <label class="check"><input type="checkbox" name="consent"> I have read what ResumeFit stores and agree to it.</label>`
            : ""
        }
        <button class="btn primary block" type="submit">${up ? "Create account" : "Sign in"}</button>
      </form>
      ${up ? "" : '<p class="center" style="margin:14px 0 0"><button class="linkish" data-act="toggle-reset">Forgot your password?</button></p>'}
    </div>
    ${reset}
    ${up ? '<p class="small center" style="margin-top:14px">Signing up with Google? You\'ll see the privacy note on the next screen.</p>' : ""}
  </div>`;
}

function viewConsent() {
  const err = `<div id="auth-error">${authErrorHtml()}</div>`;
  return `
  <div class="narrow" style="max-width:520px">
    <div class="hero"><h1>One more step.</h1><p>Read what ResumeFit keeps about you, then create your account.</p></div>
    <div class="card">
      ${err}
      <div class="label" style="margin-top:0">What ResumeFit stores and why</div>
      <div class="muted" style="font-size:.9rem">${privacyList()}</div>
      <form data-form="consent">
        <label class="check"><input type="checkbox" name="consent"> I have read the note above and agree to it.</label>
        <button class="btn primary block" type="submit">Create my account</button>
      </form>
    </div>
    <p class="center"><button class="linkish" data-act="signout">Use a different account</button></p>
  </div>`;
}

// ---- analyse: input -----------------------------------------------------------------------
function viewAnalyse() {
  return S.analysis ? viewResult(S.analysis) : viewInput();
}

function jdState() {
  const n = S.jdText.trim().length;
  return { n, ok: n >= LIMITS.jdMin && n <= LIMITS.jdMax };
}

function missingHint() {
  const { n, ok } = jdState();
  if (!S.resume && !ok) return "Add your resume and the job description to continue.";
  if (!S.resume) return "Add your resume to continue.";
  if (n === 0) return "Add the job description to continue.";
  if (n < LIMITS.jdMin) return `The job description needs at least ${LIMITS.jdMin} characters.`;
  if (n > LIMITS.jdMax) return `The job description is over ${LIMITS.jdMax.toLocaleString()} characters; trim it.`;
  return "Takes a few seconds.";
}

function countHtml() {
  const { n } = jdState();
  const bad = n > 0 && (n < LIMITS.jdMin || n > LIMITS.jdMax);
  return `<div class="count ${bad ? "bad" : ""}" id="jd-count">${n.toLocaleString()} / ${LIMITS.jdMax.toLocaleString()} characters${
    n > 0 && n < LIMITS.jdMin ? ` · at least ${LIMITS.jdMin}` : ""
  }</div>`;
}

function stepsHtml() {
  const { ok } = jdState();
  const step = !S.resume ? 1 : !ok ? 2 : 3;
  const st = (i, t) => `<div class="step ${step === i ? "on" : step > i ? "done" : ""}"><i>${step > i ? "✓" : i}</i>${t}</div>`;
  return `<div class="steps" id="steps">${st(1, "Resume")}${st(2, "Job description")}${st(3, "Score")}</div>`;
}

function viewInput() {
  const { ok } = jdState();
  const resume = S.resume
    ? `<div class="file"><span class="file-tag">PDF</span><span class="file-name">${esc(S.resume.name)}</span>
        <span class="small">${(S.resume.size / 1024).toFixed(0)} KB</span>
        <button class="btn ghost" data-act="clear-resume">Change</button></div>`
    : `<label class="drop" data-drop="resume"><input type="file" accept="application/pdf,.pdf" data-file="resume" class="sr-only">
        <b>Drop your resume here, or click to choose</b><span class="small">PDF, up to ${LIMITS.resumeMb} MB and 5 pages</span></label>`;
  const jd =
    S.jdMode === "paste"
      ? `<textarea id="jd" placeholder="Paste the full job description: responsibilities, requirements, nice-to-haves…" aria-label="Job description">${esc(S.jdText)}</textarea>${countHtml()}`
      : `<label class="drop" data-drop="jd"><input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" data-file="jd" class="sr-only">
          <b>Drop the job description here, or click to choose</b><span class="small">PDF or Word (.docx). You can check and edit the text before scoring.</span></label>`;
  return `
  <div class="hero" style="margin-top:12px"><h1>New analysis</h1><p>Two inputs, then your score and gaps.</p></div>
  ${stepsHtml()}
  ${S.error ? `<div class="alert error">${esc(S.error)}</div>` : ""}
  <div class="label">1 · Your resume</div>
  ${resume}
  <div class="label row-between"><span>2 · Job description</span>
    <span class="seg" style="text-transform:none;letter-spacing:0;font-weight:400">
      <button data-act="jd-mode" data-mode="paste" class="${S.jdMode === "paste" ? "on" : ""}">Paste</button>
      <button data-act="jd-mode" data-mode="upload" class="${S.jdMode === "upload" ? "on" : ""}">Upload</button></span></div>
  ${S.jdNote ? `<div class="alert">${esc(S.jdNote)}</div>` : ""}
  ${jd}
  <label class="check"><input type="checkbox" data-field="store" ${S.store ? "checked" : ""}>
    <span>Also store my full resume text with this analysis <span class="small">(optional; by default only short passages without your contact details are kept)</span></span></label>
  <button class="btn primary block lg" id="analyse-btn" data-act="analyse" ${S.resume && ok && !S.busy ? "" : "disabled"}>
    ${S.busy ? spinner + " Scoring your resume…" : "Analyse fit"}</button>
  <div class="hint" id="analyse-hint">${esc(missingHint())}</div>
  ${S.me ? `<p class="small center">${S.me.usage.analyses_used} of ${S.me.usage.analyses_limit} analyses used today</p>` : ""}`;
}

function setResume(file) {
  S.error = null;
  if (!file) return;
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
    S.error = "The resume must be a PDF.";
  } else if (file.size > LIMITS.resumeMb * 1024 * 1024) {
    S.error = `That file is over ${LIMITS.resumeMb} MB.`;
  } else S.resume = file;
  render();
}

async function setJdFile(file) {
  if (!file) return;
  S.error = null;
  S.jdNote = "Reading the file…";
  render();
  const form = new FormData();
  form.append("file", file);
  try {
    const out = await api("POST", "/jd/extract", { form });
    S.jdText = out.text;
    S.jdSource = out.source;
    S.jdMode = "paste";
    S.jdNote = `Text taken from ${file.name}. Check it and edit if needed.` + (out.warning ? ` ${out.warning}` : "");
  } catch (e) {
    S.jdNote = null;
    S.error = e.message;
  }
  render();
}

async function analyse() {
  if (S.busy) return;
  S.busy = true;
  S.error = null;
  render();
  const form = new FormData();
  form.append("resume", S.resume, S.resume.name);
  form.append("jd_text", S.jdText);
  form.append("jd_source", S.jdSource);
  form.append("store_resume_text", S.store ? "true" : "false");
  try {
    S.analysis = await api("POST", "/analyze", { form });
    S.history.items = null;
    refreshUsage();
  } catch (e) {
    S.error = e.message;
  }
  S.busy = false;
  render();
  window.scrollTo(0, 0);
}

// ---- analyse: result ------------------------------------------------------------------------
function ring(score, band, size = 132) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const arc = (c * Math.min(Math.max(score, 0), 100)) / 100;
  const color = { strong: "var(--strong)", partial: "var(--partial)", weak: "var(--weak)" }[band] || "var(--accent)";
  return `<svg width="${size}" height="${size}" viewBox="0 0 120 120" role="img" aria-label="Score ${score} out of 100">
    <circle cx="60" cy="60" r="${r}" fill="none" style="stroke:var(--ring-track)" stroke-width="9"/>
    <circle cx="60" cy="60" r="${r}" fill="none" style="stroke:${color}" stroke-width="9" stroke-linecap="round"
      stroke-dasharray="${arc.toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 60 60)"/>
    <text x="60" y="66" text-anchor="middle" font-size="32" font-weight="700">${score}</text>
    <text x="60" y="84" text-anchor="middle" font-size="10" class="of">of 100</text></svg>`;
}

function bars(components) {
  return Object.entries(components)
    .map(([name, v]) => {
      const label = esc(cap(name.replaceAll("_", " ")));
      if (v === null || v === undefined)
        return `<div class="bar"><div class="bar-head"><span>${label}</span><span>n/a</span></div></div>`;
      const w = Math.round(Math.min(Math.max(v, 0), 1) * 100);
      return `<div class="bar"><div class="bar-head"><span>${label}</span><span>${v.toFixed(2)}</span></div>
        <div class="track"><div class="fill" style="width:${w}%"></div></div></div>`;
    })
    .join("");
}

function verdict(a) {
  const band = String(a.band).toLowerCase();
  const words = BAND_WORDS[band] || cap(band);
  const m = a.matched_skills.length;
  const total = m + a.missing_skills.length;
  if (!total) return `${words}. No listed skills were found in the job description.`;
  return `${words}. You cover ${m} of ${total} skills this job lists.`;
}

const topGap = (a) =>
  a.missing_skills.length ? a.missing_skills.reduce((x, y) => (y.jd_mentions > x.jd_mentions ? y : x)) : null;

function stars(type, id, prompt) {
  const n = S.rated.get(id) || 0;
  const buttons = [1, 2, 3, 4, 5]
    .map(
      (i) =>
        `<button data-act="rate" data-type="${type}" data-id="${esc(id)}" data-n="${i}" class="${i <= n ? "on" : ""}" aria-label="${i} star${i > 1 ? "s" : ""}">★</button>`,
    )
    .join("");
  return `<div class="rate" data-rate="${esc(id)}"><span class="muted">${esc(prompt)}</span><span class="stars">${buttons}</span></div>`;
}

function viewResult(a) {
  const band = String(a.band).toLowerCase();
  const gap = topGap(a);
  const missing = [...a.missing_skills].sort((x, y) => y.jd_mentions - x.jd_mentions);
  const rows = [];
  if (a.sections_missing.length) rows.push(["Sections not found", a.sections_missing.join(", ")]);
  a.suggestions.forEach((s) => rows.push([cap(s.section), s.text]));
  return `
  <div class="toolbar">
    <button class="btn ghost" data-act="new">← New analysis</button>
    <button class="btn" data-act="download">Download report</button>
  </div>
  <div class="card">
    <div class="result-head">
      <div class="ring">${ring(a.score, band)}</div>
      <div><span class="band ${esc(band)}">${esc(band)}</span>
        <div class="verdict">${esc(verdict(a))}</div>${bars(a.components)}</div>
    </div>
  </div>
  ${a.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}
  ${
    gap
      ? `<div class="start"><div class="start-k">Start here</div><div><b>${esc(gap.skill)}</b> is the biggest gap: the job description mentions it ${gap.jd_mentions}×. If you have used it, say where and what came of it.</div></div>`
      : ""
  }
  <div class="label">Missing skills</div>
  ${
    missing.length
      ? `<div class="chips">${missing.map((m) => `<span class="chip miss">${esc(m.skill)}<em>×${m.jd_mentions}</em></span>`).join("")}</div>
         <div class="small" style="margin-top:6px">× = times the job description mentions it</div>`
      : '<span class="muted">None. Every listed skill was found.</span>'
  }
  <div class="label">Matched skills</div>
  ${
    a.matched_skills.length
      ? `<div class="chips">${a.matched_skills.map((s) => `<span class="chip ok">${esc(s)}</span>`).join("")}</div>`
      : '<span class="muted">None found.</span>'
  }
  ${a.semantic_matches.map((m) => `<div class="small" style="margin-top:6px">“${esc(m.resume_phrase)}” counted as ${esc(m.skill)} (similar meaning)</div>`).join("")}
  <div class="label">Suggestions</div>
  ${
    rows.length
      ? `<div>${rows.map(([k, v]) => `<div class="sugg"><b>${esc(k)}</b><div>${esc(v)}</div></div>`).join("")}</div>`
      : '<span class="muted">No weak sections flagged.</span>'
  }
  ${stars("analysis", a.id, "Was this analysis useful?")}
  <p class="small">${esc(a.id)} · ${esc(a.model_version)} · ${a.latency_ms} ms · a guide, not a hiring decision</p>
  <section id="coach">${coachHtml(a)}</section>`;
}

function reportMarkdown(a) {
  const lines = ["# ResumeFit report", "", `Score: **${a.score} / 100** (${a.band})`, "", verdict(a), "", "## How the score is built", ""];
  for (const [k, v] of Object.entries(a.components))
    lines.push(`- ${cap(k.replaceAll("_", " "))}: ${v === null ? "n/a" : v.toFixed(2)}`);
  lines.push("", "## Matched skills", "", a.matched_skills.join(", ") || "None found.", "", "## Missing skills", "");
  if (a.missing_skills.length)
    a.missing_skills.forEach((m) => lines.push(`- ${m.skill} (mentioned ${m.jd_mentions}x in the job description)`));
  else lines.push("None.");
  lines.push("", "## Suggestions", "");
  if (a.sections_missing.length) lines.push(`- Sections not found: ${a.sections_missing.join(", ")}`);
  a.suggestions.forEach((s) => lines.push(`- ${cap(s.section)}: ${s.text}`));
  if (!a.suggestions.length && !a.sections_missing.length) lines.push("No weak sections flagged.");
  lines.push("", "---", `${a.id} · ${a.model_version}. The score is a guide to improving a resume, not a hiring decision, and it can be wrong.`, "");
  return lines.join("\n");
}

function download(a) {
  const blob = new Blob([reportMarkdown(a)], { type: "text/markdown" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `resumefit-${a.id}.md`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// ---- coach ----------------------------------------------------------------------------------
function suggestedQuestions(a) {
  const q = [];
  const gap = topGap(a);
  if (gap) q.push(`How can I show ${gap.skill} for this job?`);
  q.push("Which of my projects fits this job best?");
  if (a.suggestions.length) q.push(`How do I strengthen my ${a.suggestions[0].section} section?`);
  q.push("What does this job care about most?");
  return q.slice(0, 4);
}

const answerHtml = (text) => esc(text).replace(/\[([RJG]\d+)\]/g, '<span class="cite">$1</span>');

function coachHtml(a) {
  const turns = S.coach.get(a.id) || [];
  const pending = turns.some((t) => t.pending);
  const asked = new Set(turns.map((t) => t.q));
  const ideas = suggestedQuestions(a).filter((q) => !asked.has(q));
  const turnHtml = turns
    .map((t) => {
      let bot;
      if (t.pending) bot = '<div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div>';
      else if (t.error) bot = `<div class="alert error" style="margin:0">${esc(t.error)}</div>`;
      else {
        const sources = t.citations.length
          ? `<details class="more"><summary>Sources · ${t.citations.length}</summary>${t.citations
              .map(
                (c) =>
                  `<div class="src"><span class="cite">${esc(c.id)}</span> <b>${esc(c.label)}</b> <span class="small">· ${esc(SOURCE_NAMES[c.source] || c.source)}</span><p>${esc(c.text)}</p></div>`,
              )
              .join("")}</details>`
          : "";
        bot = `<div class="bubble">${answerHtml(t.answer)}</div>${sources}${t.id ? stars("coach_message", t.id, "Useful answer?") : ""}`;
      }
      return `<div class="msg user"><div class="av">You</div><div class="body">${esc(t.q)}</div></div>
        <div class="msg bot"><div class="av">RF</div><div class="body">${bot}</div></div>`;
    })
    .join("");
  return `
    <div class="label" style="margin-top:40px">Ask the coach</div>
    <p class="muted" style="margin-top:0;font-size:.9rem">Answers come only from your resume, this job description and the guide library, with their sources. The coach doesn't predict hiring outcomes.</p>
    ${turnHtml}
    ${
      ideas.length && !pending
        ? `<div class="pills">${ideas.map((q) => `<button class="pill" data-act="ask-idea" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`
        : ""
    }
    <form class="ask" data-form="ask">
      <input type="text" name="q" placeholder="Ask about this analysis…" maxlength="${LIMITS.qMax}" autocomplete="off" ${pending ? "disabled" : ""}>
      <button class="btn primary" type="submit" ${pending ? "disabled" : ""}>${pending ? spinner : "Ask"}</button>
    </form>`;
}

function renderCoach() {
  const el = document.getElementById("coach");
  if (el && S.analysis) el.innerHTML = coachHtml(S.analysis);
}

async function ask(question) {
  const a = S.analysis;
  const q = question.trim();
  if (!a) return;
  if (q.length < LIMITS.qMin) return toast(`Ask a question of at least ${LIMITS.qMin} characters.`);
  if (!S.coach.has(a.id)) S.coach.set(a.id, []);
  const turn = { q, pending: true };
  S.coach.get(a.id).push(turn);
  renderCoach();
  try {
    Object.assign(turn, await api("POST", "/coach", { json: { analysis_id: a.id, question: q } }));
    refreshUsage();
  } catch (e) {
    turn.error = e.message;
  }
  turn.pending = false;
  renderCoach();
  document.querySelector('#coach input[name="q"]')?.focus();
}

async function rate(btn) {
  const { type, id } = btn.dataset;
  const n = Number(btn.dataset.n);
  try {
    await api("POST", "/feedback", { json: { target_type: type, target_id: id, rating: n } });
    S.rated.set(id, n);
    document.querySelectorAll(`[data-rate="${CSS.escape(id)}"] .stars button`).forEach((b) =>
      b.classList.toggle("on", Number(b.dataset.n) <= n),
    );
    toast("Thanks, your rating was saved.");
  } catch (e) {
    toast(e.message);
  }
}

// ---- history ----------------------------------------------------------------------------------
async function loadHistory() {
  if (!S.me || S.history.loading) return;
  S.history.loading = true;
  S.history.error = null;
  try {
    S.history.items = await api("GET", "/analyses?limit=100");
  } catch (e) {
    S.history.error = e.message;
  }
  S.history.loading = false;
  if (route() === "history") render();
}

function trend(items) {
  const pts = [...items].reverse().map((x) => x.score);
  const W = 600;
  const H = 90;
  const pad = 8;
  const x = (i) => pad + (i * (W - 2 * pad)) / (pts.length - 1);
  const y = (s) => H - pad - (s / 100) * (H - 2 * pad);
  const line = pts.map((s, i) => `${x(i).toFixed(1)},${y(s).toFixed(1)}`).join(" ");
  const dots = pts.map((s, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(s).toFixed(1)}" r="3.5" style="fill:var(--accent)"><title>${s}</title></circle>`).join("");
  return `<div class="card trend" style="padding:16px 18px">
    <div class="row-between"><span class="muted" style="font-size:.85rem">Score over time</span>
      <span class="small">${pts[0]} → <b style="color:var(--text)">${pts[pts.length - 1]}</b></span></div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Scores from oldest to newest: ${pts.join(", ")}">
      <line x1="0" x2="${W}" y1="${y(50)}" y2="${y(50)}" style="stroke:var(--border)" stroke-dasharray="4 4"/>
      <polyline points="${line}" fill="none" style="stroke:var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke"/>${dots}</svg>
    <div class="row-between small"><span>oldest</span><span>newest</span></div></div>`;
}

function viewHistory() {
  const h = S.history;
  const head = `<div class="hero" style="margin-top:12px"><h1>History</h1><p>Your analyses from the last 30 days.</p></div>`;
  if (h.error) return head + `<div class="alert error">${esc(h.error)}</div>`;
  if (!h.items) return head + '<div class="skeleton"></div><div class="skeleton" style="width:70%"></div>';
  if (!h.items.length)
    return head + `<div class="empty"><b>No analyses yet</b><p class="muted">Score your resume against a job to see it here.</p>
      <a class="btn primary" href="#/analyse">New analysis</a></div>`;
  const rows = h.items
    .map((x) => {
      const band = String(x.band).toLowerCase();
      const confirm = h.confirm === x.id;
      const actions = confirm
        ? `<span class="small">Delete?</span><button class="btn danger primary" data-act="del-yes" data-id="${esc(x.id)}">Delete</button><button class="btn ghost" data-act="del-no">Keep</button>`
        : `<button class="btn" data-act="open" data-id="${esc(x.id)}">Open</button><button class="btn ghost danger" data-act="del" data-id="${esc(x.id)}" aria-label="Delete analysis">Delete</button>`;
      return `<div class="hist ${esc(band)}"><div class="hist-score">${x.score}</div>
        <div class="hist-text"><div class="clamp">${esc(x.jd_preview.replace(/\s+/g, " "))}</div>
          <div class="small">${esc(fmtDate(x.created_at))} · <span class="band ${esc(band)}" style="font-size:.62rem;padding:1px 7px">${esc(band)}</span></div></div>
        <div class="hist-actions">${actions}</div></div>`;
    })
    .join("");
  return head + (h.items.length >= 2 ? trend(h.items) : "") + `<div class="label">${h.items.length} saved</div><div class="card list">${rows}</div>`;
}

async function openAnalysis(id) {
  try {
    S.analysis = await api("GET", `/analyses/${encodeURIComponent(id)}`);
    go("analyse");
  } catch (e) {
    toast(e.message);
  }
}

async function deleteAnalysis(id) {
  try {
    await api("DELETE", `/analyses/${encodeURIComponent(id)}`);
    S.history.items = S.history.items.filter((x) => x.id !== id);
    S.history.confirm = null;
    S.coach.delete(id);
    if (S.analysis?.id === id) S.analysis = null;
    render();
    toast("Analysis deleted.");
  } catch (e) {
    toast(e.message);
  }
}

// ---- account ------------------------------------------------------------------------------
function usageBar(label, used, limit) {
  const w = Math.round(Math.min(used / Math.max(limit, 1), 1) * 100);
  return `<div class="bar"><div class="bar-head"><span>${label}</span><span>${used} of ${limit}</span></div>
    <div class="track"><div class="fill" style="width:${w}%"></div></div></div>`;
}

function viewAccount() {
  const me = S.me;
  const u = me.usage;
  const google = me.sign_in_provider === "google.com";
  const verify =
    !me.email_verified && !google
      ? ` <span class="small">not verified</span> <button class="linkish" data-act="verify">Send link</button>`
      : me.email_verified
        ? ' <span class="small">verified</span>'
        : "";
  return `
  <div class="hero" style="margin-top:12px"><h1>Account</h1></div>
  <div class="card">
    <dl class="kv">
      <dt>Email</dt><dd>${esc(me.email)}${verify}</dd>
      <dt>Signed in with</dt><dd>${google ? "Google" : "Email and password"}</dd>
      <dt>Member since</dt><dd>${esc(toDate(me.created_at).toLocaleDateString())}</dd>
    </dl>
  </div>
  <div class="card">
    <div class="label" style="margin-top:0">Today's usage</div>
    ${usageBar("Analyses", u.analyses_used, u.analyses_limit)}
    ${usageBar("Coach questions", u.coach_used, u.coach_limit)}
    <p class="small" style="margin-bottom:0">Resets at ${esc(toDate(u.resets_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))} your time.</p>
  </div>
  <div class="card row-between"><span>Sign out of ResumeFit on this browser.</span><button class="btn" data-act="signout">Sign out</button></div>
  <div class="label">Danger zone</div>
  <details class="more">
    <summary>Delete my account and all my data</summary>
    <p class="muted" style="font-size:.9rem">This deletes every analysis, coach message and rating linked to you, and your sign-in. It can't be undone.</p>
    <form data-form="delete-account">
      ${google ? "" : '<label class="field"><span>Confirm your password</span><input type="password" name="password" required autocomplete="current-password"></label>'}
      <label class="check"><input type="checkbox" name="sure" required> I understand this can't be undone.</label>
      <button class="btn danger primary" type="submit">Delete my account</button>
    </form>
  </details>`;
}

async function deleteAccount(form) {
  const user = S.user;
  const btn = form.querySelector("button");
  btn.disabled = true;
  btn.innerHTML = spinner + " Deleting…";
  try {
    if (S.me.sign_in_provider === "google.com") await reauthenticateWithPopup(user, new GoogleAuthProvider());
    else await reauthenticateWithCredential(user, EmailAuthProvider.credential(user.email, form.password.value));
    await user.getIdToken(true); // fresh sign-in time for the API's recent-login check
    await api("DELETE", "/auth/me");
    await deleteUser(user);
    S.me = null;
    S.user = null;
    await doSignOut();
    toast("Your account and data were deleted.");
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Delete my account";
    if (!SILENT.includes(e.code)) toast(e instanceof ApiError ? e.message : fbMessage(e));
  }
}

// ---- admin --------------------------------------------------------------------------------
async function loadAdmin() {
  if (!S.me?.is_admin) return;
  S.admin.loading = true;
  S.admin.error = null;
  try {
    S.admin.data = await api("GET", `/admin/metrics?days=${S.admin.days}`);
  } catch (e) {
    S.admin.error = e.message;
  }
  S.admin.loading = false;
  if (route() === "admin") render();
}

function hbars(rows, labelKey, valueKey, fmt = (v) => v) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey] || 0));
  return rows
    .map(
      (r) => `<div class="hbar"><span>${esc(r[labelKey])}</span><div class="track"><div class="fill" style="width:${Math.round(((r[valueKey] || 0) / max) * 100)}%"></div></div><span>${esc(fmt(r[valueKey]))}</span></div>`,
    )
    .join("");
}

function viewAdmin() {
  const A = S.admin;
  const days = [1, 7, 14, 30]
    .map((d) => `<button data-act="admin-days" data-days="${d}" class="${A.days === d ? "on" : ""}">${d} d</button>`)
    .join("");
  const head = `<div class="hero row-between" style="margin-top:12px"><h1>Admin</h1><span class="seg">${days}</span></div>`;
  if (A.error) return head + `<div class="alert error">${esc(A.error)}</div>`;
  if (!A.data) return head + '<div class="skeleton"></div><div class="skeleton" style="width:70%"></div>';
  const m = A.data;
  const req = m.requests;
  const lat = (p) => (req.latency[p] ? `${req.latency[p].p95_ms} ms` : "n/a");
  const rate = req.server_error_rate === null ? "n/a" : `${(req.server_error_rate * 100).toFixed(1)}%`;
  const flags = m.flags.length
    ? m.flags.map((f) => `<div class="alert error">${esc(f)}</div>`).join("")
    : '<div class="alert ok">No flags for this window.</div>';
  return `${head}${flags}
  <div class="metrics">
    <div class="metric"><span>Requests</span><b>${req.requests}</b></div>
    <div class="metric"><span>Server errors</span><b>${rate}</b></div>
    <div class="metric"><span>Quota hits</span><b>${m.quota_hits.total}</b></div>
    <div class="metric"><span>Active users</span><b>${m.usage.active_users}</b></div>
    <div class="metric"><span>/analyze p95</span><b>${lat("/analyze")}</b></div>
    <div class="metric"><span>/coach p95</span><b>${lat("/coach")}</b></div>
  </div>
  <div class="label">Score distribution</div>
  <p class="small">${m.scores.count} analyses · mean ${m.scores.mean ?? "n/a"} · missing sections in ${m.scores.missing_sections_share ?? "n/a"} of resumes</p>
  <div class="card">${hbars(m.scores.histogram || [], "bucket", "count")}</div>
  <div class="label">Ratings by day</div>
  <p class="small">${m.ratings.count} ratings · mean ${m.ratings.mean ?? "n/a"}</p>
  <div class="card">${hbars(m.ratings.by_day || [], "day", "count")}</div>
  <div class="label">Requests by endpoint</div>
  <div class="card">${hbars(Object.entries(req.by_path || {}).map(([path, count]) => ({ path, count })), "path", "count")}</div>
  <p class="small">Generated ${esc(fmtDate(m.generated_at))}. User ids are pseudonymous; no emails are shown here.</p>`;
}

// ---- privacy and terms --------------------------------------------------------------------
async function loadHealth() {
  if (S.health) return;
  try {
    const res = await fetch(API_URL + "/health");
    S.health = await res.json();
    if (route() === "privacy") render();
  } catch {
    /* optional */
  }
}

function viewPrivacy() {
  return `<article class="prose">
    <div class="hero" style="margin-top:12px"><h1>Privacy</h1><p>What ResumeFit stores, why, and for how long.</p></div>
    <h2>What is stored</h2>${privacyList()}
    <h2>What is never stored</h2>
    <ul><li>Uploaded files. They are read in memory and discarded.</li>
      <li>Your password. Firebase handles it; ResumeFit never sees it.</li>
      <li>Resume or job text in server logs. Logs hold only request ids, status codes, timings and scores.</li></ul>
    <h2>Your controls</h2>
    <ul><li>Delete any analysis from History at any time.</li>
      <li>Delete your account from Account. Everything linked to you goes with it.</li></ul>
    <h2>The score</h2>
    <p>The score is a guide to improving a resume, not a hiring decision, and it can be wrong. ResumeFit does not predict whether you will get a job.</p>
    ${S.health ? `<p class="small">Coach model in use: ${esc(S.health.coach_model_version)}. Scoring model: ${esc(S.health.model_version)}.</p>` : ""}
  </article>`;
}

function viewTerms() {
  return `<article class="prose">
    <div class="hero" style="margin-top:12px"><h1>Terms</h1><p>The short version of the rules for using ResumeFit.</p></div>
    <ul>
      <li>ResumeFit is a free personal project, offered as is, with no guarantee that it is available, correct or fit for any purpose.</li>
      <li>Only upload your own resume, or one you have the owner's permission to upload.</li>
      <li>The score and the coach's answers are suggestions. Check them before relying on them; they are not hiring advice.</li>
      <li>There are daily limits on analyses and coach questions to keep the service free.</li>
      <li>Accounts that abuse the service may be removed. The service may change or stop at any time.</li>
    </ul>
    <p>See <a href="#/privacy">Privacy</a> for what is stored.</p>
  </article>`;
}

// ---- events -------------------------------------------------------------------------------
async function withAuthError(fn) {
  S.authError = null;
  try {
    await fn();
  } catch (e) {
    if (SILENT.includes(e.code)) return;
    S.authError = e instanceof ApiError ? e.message : fbMessage(e);
    const box = document.getElementById("auth-error");
    // Show the message in place so typed email and password are kept, unless the
    // screen itself must change (signed in to Firebase but not registered yet).
    if (box && !(S.user && S.needsConsent)) box.innerHTML = authErrorHtml();
    else render();
  }
}

const ACTIONS = {
  goto: (t) => {
    S.authError = null;
    S.authInfo = null;
    go(t.dataset.to);
  },
  google: () =>
    withAuthError(async () => {
      S.authInfo = null;
      await signInWithPopup(S.auth, new GoogleAuthProvider());
    }),
  "toggle-reset": () => {
    S.showReset = !S.showReset;
    render();
  },
  signout: () => doSignOut(),
  "clear-resume": () => {
    S.resume = null;
    render();
  },
  "jd-mode": (t) => {
    S.jdMode = t.dataset.mode;
    render();
  },
  analyse: () => analyse(),
  new: () => {
    S.analysis = null;
    S.jdText = "";
    S.jdSource = "text";
    S.jdNote = null;
    S.error = null;
    render();
    window.scrollTo(0, 0);
  },
  download: () => download(S.analysis),
  "ask-idea": (t) => ask(t.dataset.q),
  rate: (t) => rate(t),
  open: (t) => openAnalysis(t.dataset.id),
  del: (t) => {
    S.history.confirm = t.dataset.id;
    render();
  },
  "del-no": () => {
    S.history.confirm = null;
    render();
  },
  "del-yes": (t) => deleteAnalysis(t.dataset.id),
  verify: async () => {
    try {
      await sendEmailVerification(S.user);
      toast("Verification email sent. Open the link, then sign in again.");
    } catch (e) {
      toast(fbMessage(e));
    }
  },
  "admin-days": (t) => {
    S.admin.days = Number(t.dataset.days);
    S.admin.data = null;
    render();
    loadAdmin();
  },
};

const FORMS = {
  signin: (f) =>
    withAuthError(async () => {
      S.authInfo = null;
      await signInWithEmailAndPassword(S.auth, f.email.value.trim(), f.password.value);
    }),
  signup: (f) =>
    withAuthError(async () => {
      if (!f.consent.checked) throw new ApiError("consent", "Please agree to the privacy note to create an account.");
      S.registering = true;
      try {
        const cred = await createUserWithEmailAndPassword(S.auth, f.email.value.trim(), f.password.value);
        S.user = cred.user;
        await api("POST", "/auth/register", { json: { consent: true } });
        sendEmailVerification(cred.user).catch(() => {});
        await loadMe();
      } catch (e) {
        if (S.user) await loadMe(); // signed in to Firebase but not registered: consent screen
        throw e;
      } finally {
        S.registering = false;
      }
      if (!S.me) await loadMe();
      go("analyse");
      toast("Account created. We sent you a link to verify your email.");
    }),
  consent: (f) =>
    withAuthError(async () => {
      if (!f.consent.checked) throw new ApiError("consent", "Please agree to the privacy note to continue.");
      await api("POST", "/auth/register", { json: { consent: true } });
      S.authError = null;
      await loadMe();
      go("analyse");
    }),
  reset: async (f) => {
    try {
      await sendPasswordResetEmail(S.auth, f.email.value.trim());
    } catch (e) {
      if (e.code !== "auth/user-not-found") return toast(fbMessage(e));
    }
    S.showReset = false;
    S.authInfo = "If an account exists for that email, a reset link is on its way.";
    render();
  },
  ask: (f) => {
    const q = f.q.value;
    if (q.trim()) ask(q);
  },
  "delete-account": (f) => deleteAccount(f),
};

view.addEventListener("click", (e) => {
  const t = e.target.closest("[data-act]");
  if (!t || t.disabled) return;
  e.preventDefault();
  ACTIONS[t.dataset.act]?.(t, e);
});
view.addEventListener("submit", (e) => {
  e.preventDefault();
  FORMS[e.target.dataset.form]?.(e.target);
});
view.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.file === "resume") setResume(t.files[0]);
  if (t.dataset.file === "jd") setJdFile(t.files[0]);
  if (t.dataset.field === "store") S.store = t.checked;
});
view.addEventListener("input", (e) => {
  if (e.target.id !== "jd") return;
  S.jdText = e.target.value;
  if (S.jdSource !== "text" && !S.jdNote) S.jdSource = "text";
  // update the count, button and hint in place so the textarea keeps focus
  document.getElementById("jd-count").outerHTML = countHtml();
  document.getElementById("steps").outerHTML = stepsHtml();
  const { ok } = jdState();
  document.getElementById("analyse-btn").disabled = !(S.resume && ok && !S.busy);
  document.getElementById("analyse-hint").textContent = missingHint();
});
for (const type of ["dragenter", "dragover"])
  view.addEventListener(type, (e) => {
    const zone = e.target.closest("[data-drop]");
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("over");
  });
view.addEventListener("dragleave", (e) => e.target.closest("[data-drop]")?.classList.remove("over"));
view.addEventListener("drop", (e) => {
  const zone = e.target.closest("[data-drop]");
  if (!zone) return;
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (zone.dataset.drop === "resume") setResume(file);
  else setJdFile(file);
});
window.addEventListener("hashchange", onRoute);
window.addEventListener("scroll", () =>
  document.querySelector("header.top").classList.toggle("scrolled", window.scrollY > 4),
);

onRoute();
boot();
