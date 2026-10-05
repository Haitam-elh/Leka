import { type AssembledContext, BUDGET, contexts, type IntentAsk } from "@/lib/context";
import type { IntentionRequest } from "@/lib/validation/intentions";

/**
 * Submitting an intention: until LEKA-384 keeps intentions themselves,
 * submitting one assembles the context it asks for (LEKA-373) — what LEKA
 * reads of its words and its scope, what it is about, when, where, what is
 * missing — and step 2 shows it. The day intentions are kept, this posts
 * to /intentions, and the context comes with what it returns.
 *
 * WHAT THE FORM SAYS, AND WHAT IT LEAVES TO THE WORDS. The scope it shows
 * is sent as asked: an environment other than "every one", the services
 * chosen, the sources when not all of them are ticked. The period is sent
 * only when someone chose it: its default is no choice, and « depuis
 * hier » in the question says more than a preset nobody touched.
 *
 * TODO: attachments are names here. Uploading them is a separate call to
 * object storage, and the request should carry the ids it returns.
 */

const HOUR = 3_600_000;
const PRESETS: Record<string, number> = { "24h": 24 * HOUR, "7d": 7 * 24 * HOUR, "30d": 30 * 24 * HOUR };

/** The intention as the API reads it. */
export function intentAsk(
  request: IntentionRequest,
  {
    everySource,
    periodChosen,
    now = new Date(),
  }: { everySource: boolean; periodChosen: boolean; now?: Date },
): IntentAsk {
  const ask: IntentAsk = {
    text: request.text.trim(),
    services: request.services,
    sources: everySource ? [] : request.sources,
    limit: BUDGET,
  };
  if (request.environment && request.environment !== "all") ask.environment = request.environment;
  if (periodChosen) Object.assign(ask, periodOf(request.period, now));
  return ask;
}

/** A period as the form holds it — a preset, or two days — as instants. */
export function periodOf(
  period: IntentionRequest["period"],
  now: Date,
): { since: string; until: string } | Record<string, never> {
  const span = PRESETS[period.preset];
  if (span) return { since: new Date(now.getTime() - span).toISOString(), until: now.toISOString() };
  const { from, to } = period.range;
  if (!from) return {};
  // Two calendar days, the second whole: « du 1er au 3 » reads the 3rd.
  const until = to ? new Date(`${to}T00:00:00Z`).getTime() + 24 * HOUR : now.getTime();
  return {
    since: new Date(`${from}T00:00:00Z`).toISOString(),
    until: new Date(Math.min(until, now.getTime())).toISOString(),
  };
}

export function submitIntention(ask: IntentAsk): Promise<AssembledContext> {
  return contexts.intend(ask);
}

/** The intention asked again, as it now stands: the same context made
 * again — a new version that says what LEKA reads differently (LEKA-374). */
export function reaskIntention(contextId: string, ask: IntentAsk): Promise<AssembledContext> {
  return contexts.reask({ id: contextId, ask });
}
