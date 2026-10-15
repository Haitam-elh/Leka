import type { IntentionStatus } from "@/lib/intentions/api";
import type { Journey } from "@/lib/intentions/journey";

/**
 * What the API says of a lifecycle state in its plainest case (LEKA-443):
 * no failure of its actions, no stop, nothing late. Tests and samples use
 * it; the screens never do — their journey is the API's
 * (leka/intentions/journey.py).
 */

type Said = Pick<Journey, "state" | "reason" | "next" | "by" | "controls" | "step">;

const ACT = { at: "action", reached: 4, done: false, last: 4 } as const;

const PLAIN: Record<IntentionStatus, Said> = {
  // Stopped by a person: ready, resumed when they want.
  submitted: {
    state: "ready",
    reason: "stopped",
    next: "resume",
    by: "asker",
    controls: ["ask_again", "resume", "cancel"],
    step: { at: "analysis", reached: 1, done: false, last: 4 },
  },
  needs_clarification: {
    state: "needs_clarification",
    reason: "unclear",
    next: "answer",
    by: "asker",
    controls: ["answer", "ask_again", "cancel"],
    step: { at: "intention", reached: 0, done: false, last: 4 },
  },
  analysing: {
    state: "analysing",
    reason: null,
    next: "wait",
    by: "leka",
    controls: ["ask_again", "stop", "cancel"],
    step: { at: "analysis", reached: 1, done: false, last: 4 },
  },
  awaiting_decision: {
    state: "decision_required",
    reason: null,
    next: "decide",
    by: "approver",
    controls: ["ask_again", "cancel", "decide", "modify_decision", "launch_agents", "by_hand"],
    step: { at: "decision", reached: 3, done: false, last: 4 },
  },
  approved: {
    state: "approved",
    reason: null,
    next: "start_actions",
    by: "approver",
    controls: ["cancel", "start_actions"],
    step: ACT,
  },
  scheduled: {
    state: "approved",
    reason: "scheduled",
    next: "wait_schedule",
    by: "leka",
    controls: ["cancel", "unschedule"],
    step: ACT,
  },
  executing: {
    state: "action_running",
    reason: null,
    next: "follow_actions",
    by: "leka",
    controls: ["stop_actions"],
    step: ACT,
  },
  verifying: {
    state: "to_verify",
    reason: null,
    next: "wait_verification",
    by: "leka",
    controls: ["report_outcome"],
    step: ACT,
  },
  completed: {
    state: "result_available",
    reason: null,
    next: "read_result",
    by: "asker",
    controls: ["ask_again", "archive", "launch_agents"],
    step: { at: "results", reached: 3, done: true, last: 4 },
  },
  rejected: {
    state: "rejected",
    reason: "by_person",
    next: "ask_again",
    by: "asker",
    controls: ["ask_again", "archive"],
    step: { at: "decision", reached: 3, done: true, last: 3 },
  },
  failed: {
    state: "analysis_failed",
    reason: "error",
    next: "analyse_again",
    by: "asker",
    controls: ["ask_again", "analyse_again", "cancel"],
    step: { at: "analysis", reached: 1, done: false, last: 4 },
  },
  cancelled: {
    state: "cancelled",
    reason: "by_person",
    next: "nothing",
    by: null,
    controls: ["archive"],
    step: { at: "analysis", reached: 1, done: false, last: 4 },
  },
};

/** Analysing, queued: no analysis of this attempt has started yet. */
export const QUEUED: Partial<Journey> = {
  state: "ready",
  reason: "queued",
  next: "wait",
  by: "leka",
  controls: ["ask_again", "stop", "analyse_again", "cancel"],
};

export function sampleJourney(
  status: IntentionStatus,
  more: Partial<Journey> = {},
  since = new Date().toISOString(),
): Journey {
  return { ...PLAIN[status], since, late: false, technical: null, ...more };
}
