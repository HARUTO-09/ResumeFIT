// Settings for the web front end. These are public values: nothing secret goes here.

const local = ["localhost", "127.0.0.1"].includes(location.hostname);

// Where the ResumeFit API runs. Set the deployed URL before publishing the site.
export const API_URL = local ? "http://127.0.0.1:8000" : "https://resumefit-api-x93n.onrender.com";

// The company that runs the coach's language model, shown on the privacy page and at
// sign-up. Leave empty when the model runs on your own machine (Ollama).
// Must match RESUMEFIT_LLM_* in the API's .env.
export const COACH_PROVIDER = "Google (Gemini API)";

// Extra privacy wording for that provider, e.g. how it may use the text it receives.
export const COACH_PROVIDER_NOTE =
  "ResumeFit uses Gemini's free tier, under which Google may use this text to improve its products and people at Google may read it. Don't put anything in a coach question that you wouldn't want seen.";
