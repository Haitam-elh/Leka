/**
 * How often what is on screen is read again while it is in view
 * (2026-10-29, Haitam: « que rien dans la plateforme ne soit statique » —
 * no page to reload to see what changed): every query, unless it follows
 * something faster — a run, an analysis on its way. A hidden tab reads
 * nothing; coming back to it reads at once.
 */
export const LIVE_EVERY = 10_000;

/** What is heavy to read and changes only when the company model is built
 * again: the maps of Mon environnement. */
export const LIVE_SLOW = 60_000;
