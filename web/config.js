// Settings for the web front end. These are public values: nothing secret goes here.

const local = ["localhost", "127.0.0.1"].includes(location.hostname);

// Where the ResumeFit API runs. Set the deployed URL before publishing the site.
export const API_URL = local ? "http://127.0.0.1:8000" : "https://YOUR-API-HOST.example";

// The company that runs the coach's language model, shown on the privacy page and at
// sign-up. Leave empty when the model runs on your own machine (Ollama).
// Must match RESUMEFIT_LLM_* in the API's .env.
export const COACH_PROVIDER = "";

// Extra privacy wording for that provider, e.g. how it may use the text it receives.
export const COACH_PROVIDER_NOTE = "";
