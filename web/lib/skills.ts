/**
 * Skills (LEKA-396): the operations LEKA's capabilities are made of, each
 * run checked and kept. Read here: what LEKA's analyst read to answer an
 * intention — every run about it (`intention:<id>`), what each was asked,
 * what it found.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type SkillRun = components["schemas"]["SkillRunRead"];

export const skills = {
  /** The workspace's runs about one thing, the latest first. */
  runs: (ref: string) =>
    apiFetch<SkillRun[]>(`/skills/runs?ref=${encodeURIComponent(ref)}&limit=100`),
};

/** The runs of one analysis: those between its start and its end — the
 * first one first. */
export function runsBetween(
  runs: readonly SkillRun[],
  startedAt: string,
  finishedAt: string | null,
): SkillRun[] {
  const from = new Date(startedAt).getTime();
  const to = finishedAt ? new Date(finishedAt).getTime() : Number.POSITIVE_INFINITY;
  return runs
    .filter((run) => {
      const at = new Date(run.at).getTime();
      return at >= from && at <= to;
    })
    .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** What a read was about, in its own words: what it looked for, the thing
 * it read, which way, where, over which period. */
export function readAbout(run: SkillRun): {
  subject: string | null;
  direction: "upstream" | "downstream" | null;
  environment: string | null;
  since: string | null;
  until: string | null;
} {
  const inputs = run.inputs ?? {};
  const output = run.output ?? {};
  const query = text(inputs.query);
  const subject =
    (query ? `« ${query} »` : null) ??
    text(output.name) ??
    text(output.of) ??
    text(output.around) ??
    null;
  const direction = output.direction ?? inputs.direction;
  return {
    subject,
    direction: direction === "upstream" || direction === "downstream" ? direction : null,
    environment: text(output.environment) ?? text(inputs.environment),
    since: text(output.since) ?? text(inputs.since),
    until: text(output.until) ?? text(inputs.until),
  };
}
