import type { TileTone } from "@/components/environment/parts";
import type { components } from "@/lib/api-types";
import type { Dictionary } from "@/lib/i18n/dictionaries";
import { fill } from "@/lib/i18n/dictionaries";

/**
 * Where an intention stands as a person reads it (LEKA-443): one state, the
 * same on the list, its page, its steps, its history. The API decides it
 * (leka/intentions/journey.py) from what was kept. The screens only say it:
 * - its words, its tone;
 * - why it is there, since when;
 * - what comes next and who;
 * - the controls the state allows.
 *
 * No screen derives a state of its own, and none draws a progress the API
 * did not say.
 */

export type Journey = components["schemas"]["JourneyRead"];
export type JourneyState = Journey["state"];
export type JourneyControl = Journey["controls"][number];

export const JOURNEY_TONES: Record<JourneyState, TileTone> = {
  draft: "neutral",
  needs_clarification: "warning",
  ready: "info",
  analysing: "violet",
  analysis_partial: "warning",
  analysis_failed: "danger",
  result_available: "success",
  decision_required: "warning",
  approved: "violet",
  rejected: "neutral",
  action_running: "info",
  action_failed: "danger",
  to_verify: "info",
  done: "success",
  cancelled: "neutral",
  superseded: "neutral",
};

/** The controls only who may approve uses; the others are its asker's too. */
const APPROVER_CONTROLS: ReadonlySet<JourneyControl> = new Set([
  "decide",
  "modify_decision",
  "start_actions",
  "unschedule",
  "stop_actions",
  "retry_actions",
  "report_outcome",
]);

/** Whether this person may use this control now: the state allows it, and
 * they are its asker (for what an asker does) or may approve. */
export function may(
  journey: Journey,
  control: JourneyControl,
  { yours, steward }: { yours: boolean; steward: boolean },
): boolean {
  if (!journey.controls.includes(control)) return false;
  return APPROVER_CONTROLS.has(control) ? steward : yours || steward;
}

/** Why it is there, in a sentence: its reason's, else its state's. */
export function journeyWhy(t: Dictionary, journey: Journey): string | null {
  const said = (t.intentions.journey.why as Record<string, Record<string, string>>)[
    journey.state
  ];
  if (!said) return null;
  return (journey.reason ? said[journey.reason] : undefined) ?? said.default ?? null;
}

/** What comes next, in a sentence. */
export function journeyNext(t: Dictionary, journey: Journey): string | null {
  return (t.intentions.journey.next as Record<string, string>)[journey.next] ?? null;
}

/** Said late, in a sentence — only for what waits on LEKA. */
export function journeyLate(t: Dictionary, journey: Journey): string | null {
  if (!journey.late) return null;
  const late = t.intentions.journey.late as Record<string, string>;
  return late[journey.state] ?? null;
}

/** The diagnosis it keeps, for whoever reads the details — never the words
 * a person reads first. */
export function journeyTechnical(t: Dictionary, journey: Journey, version: number): string | null {
  if (!journey.technical) return null;
  return fill(t.intentions.journey.technicalBody, { code: journey.technical, version });
}

/** States in which LEKA is working: the page is read again on its own. */
export function working(journey: Journey | undefined | null): boolean {
  if (!journey) return false;
  return journey.by === "leka";
}
