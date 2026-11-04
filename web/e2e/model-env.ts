/**
 * The language model the browser tests run with (LEKA-429): the one every
 * agent is assigned (agents/models.yaml, LEKA-530), Gemini 3.8 Flash,
 * reached at a local stand-in (e2e/model-stub.mjs) — whatever the
 * developer's .env says, no real key is ever used here, no trial model in
 * its place. Given to the API Playwright starts, and to the analyses the
 * specs run as the job runner would (intention-helpers.ts).
 */

export const MODEL_STUB_PORT = 8899;

export const MODEL_ENV: Record<string, string> = {
  LEKA_LLM_PROVIDER: "google",
  LEKA_GOOGLE_API_KEY: "e2e-stand-in",
  LEKA_LLM_API_URL: `http://127.0.0.1:${MODEL_STUB_PORT}/v1beta`,
  LEKA_LLM_TRIAL_MODEL: "",
  LEKA_MISTRAL_API_KEY: "",
  LEKA_ANTHROPIC_API_KEY: "",
};
