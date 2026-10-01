/**
 * A source's scope rules and mapping, as an administrator writes them (LEKA-351).
 *
 * The API holds structured settings; the screen edits them as lines — one
 * pattern per line, `acme/pay* → billing`, `QA Review = in_progress` —
 * because that is how people keep such lists. This module turns one into the
 * other and back, and says which line it could not read. The rules
 * themselves are checked by the API (docs/connectors/scope-and-mapping.md).
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type SourceSettings = components["schemas"]["SourceSettings"];
export type SettingsRead = components["schemas"]["SourceSettingsRead"];
export type SettingsSaved = components["schemas"]["SettingsSaved"];
export type SettingsVersion = components["schemas"]["SettingsVersionRead"];
export type Finding = components["schemas"]["Finding"];

type Page<T> = { data: T[]; next_cursor?: string | null };

export const sourceSettings = {
  get: (sourceId: string) => apiFetch<SettingsRead>(`/sources/${sourceId}/settings`),
  /** Saves nothing: what would be wrong or doubtful, checked by the API. */
  check: (sourceId: string, settings: SourceSettings) =>
    apiFetch<{ findings: Finding[] }>(`/sources/${sourceId}/settings/check`, {
      method: "POST",
      body: JSON.stringify(settings),
    }),
  save: (sourceId: string, settings: SourceSettings) =>
    apiFetch<SettingsSaved>(`/sources/${sourceId}/settings`, {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  /** Newest first. */
  versions: (sourceId: string, limit = 5) =>
    apiFetch<Page<SettingsVersion>>(`/sources/${sourceId}/settings/versions?limit=${limit}`),
};

/** The settings as the editor's text fields. */
export type SettingsDraft = {
  include: string;
  exclude: string;
  services: string;
  owners: string;
  entityTypes: Record<string, string>;
  tagEnvironment: string;
  tagService: string;
  tagApplication: string;
  tagOwner: string;
  tagCriticality: string;
  states: string;
  priorities: string;
  environments: string;
  /** Days, or empty for LEKA's policy (LEKA-348). */
  retentionDays: string;
};

/** A line that could not be read: which field, which line (1-based). */
export type LineError = { field: keyof SettingsDraft; line: number };

const ARROW = /\s*(?:→|->|=>)\s*/;
const EQUALS = /\s*=\s*/;

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function list(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((word) => word.trim())
    .filter((word) => word.length > 0);
}

/** `left <sep> right` lines; the ones without both sides are errors. */
function pairs(
  field: keyof SettingsDraft,
  text: string,
  separator: RegExp,
  errors: LineError[],
): [string, string][] {
  const out: [string, string][] = [];
  lines(text).forEach((line, index) => {
    const parts = line.split(separator);
    const left = parts[0]?.trim() ?? "";
    const right = parts.slice(1).join(" ").trim();
    if (parts.length < 2 || !left || !right) errors.push({ field, line: index + 1 });
    else out.push([left, right]);
  });
  return out;
}

export function toDraft(settings: SourceSettings): SettingsDraft {
  const scope = settings.scope ?? { include: [], exclude: [] };
  const mapping = settings.mapping ?? {};
  const table = (entries: Record<string, string> | undefined) =>
    Object.entries(entries ?? {})
      .map(([word, value]) => `${word} = ${value}`)
      .join("\n");
  return {
    include: (scope.include ?? []).join("\n"),
    exclude: (scope.exclude ?? []).join("\n"),
    services: (mapping.services ?? []).map((r) => `${r.match} → ${r.service}`).join("\n"),
    owners: (mapping.owners ?? []).map((r) => `${r.match} → ${r.team}`).join("\n"),
    entityTypes: { ...(mapping.entity_types ?? {}) },
    tagEnvironment: (mapping.tag_keys?.environment ?? []).join(", "),
    tagService: (mapping.tag_keys?.service ?? []).join(", "),
    tagApplication: (mapping.tag_keys?.application ?? []).join(", "),
    tagOwner: (mapping.tag_keys?.owner ?? []).join(", "),
    tagCriticality: (mapping.tag_keys?.criticality ?? []).join(", "),
    states: table(mapping.states),
    priorities: table(mapping.priorities),
    environments: table(mapping.environments),
    retentionDays: settings.retention?.days ? String(settings.retention.days) : "",
  };
}

/** The days a draft keeps, null for the policy — or undefined, unreadable. */
function days(text: string): number | null | undefined {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return undefined;
  const value = Number(trimmed);
  return value >= 1 && value <= 365 ? value : undefined;
}

/** The settings the draft says — or the lines it could not read. */
export function fromDraft(
  draft: SettingsDraft,
): { settings: SourceSettings; errors: [] } | { settings: null; errors: LineError[] } {
  const errors: LineError[] = [];
  const services = pairs("services", draft.services, ARROW, errors);
  const owners = pairs("owners", draft.owners, ARROW, errors);
  const states = pairs("states", draft.states, EQUALS, errors);
  const priorities = pairs("priorities", draft.priorities, EQUALS, errors);
  const environments = pairs("environments", draft.environments, EQUALS, errors);
  const retention = days(draft.retentionDays);
  if (retention === undefined) errors.push({ field: "retentionDays", line: 1 });
  if (errors.length > 0 || retention === undefined) return { settings: null, errors };
  const entityTypes = Object.fromEntries(
    Object.entries(draft.entityTypes).filter(([, type]) => type.length > 0),
  );
  return {
    errors: [],
    settings: {
      scope: { include: lines(draft.include), exclude: lines(draft.exclude) },
      mapping: {
        entity_types: entityTypes,
        services: services.map(([match, service]) => ({ match, service })),
        owners: owners.map(([match, team]) => ({ match, team })),
        tag_keys: {
          environment: list(draft.tagEnvironment),
          service: list(draft.tagService),
          application: list(draft.tagApplication),
          owner: list(draft.tagOwner),
          criticality: list(draft.tagCriticality),
        },
        states: Object.fromEntries(states),
        priorities: Object.fromEntries(priorities),
        environments: Object.fromEntries(environments),
      },
      retention: { days: retention },
    },
  };
}

/** Whether the mapping says anything at all. */
export function hasMapping(settings: SourceSettings): boolean {
  const m = settings.mapping ?? {};
  return (
    Object.keys(m.entity_types ?? {}).length > 0 ||
    (m.services ?? []).length > 0 ||
    (m.owners ?? []).length > 0 ||
    [
      m.tag_keys?.environment,
      m.tag_keys?.service,
      m.tag_keys?.application,
      m.tag_keys?.owner,
      m.tag_keys?.criticality,
    ].some((keys) => (keys ?? []).length > 0) ||
    Object.keys(m.states ?? {}).length > 0 ||
    Object.keys(m.priorities ?? {}).length > 0 ||
    Object.keys(m.environments ?? {}).length > 0
  );
}

/** The entity types a capability can be mapped to (leka/connectors/settings.py). */
export const ENTITY_TYPES = [
  "repository",
  "pull_request",
  "issue",
  "commit",
  "branch",
  "release",
  "project",
  "service",
  "incident",
  "document",
  "deployment",
  "database",
  "infra_resource",
  "cloud_account",
  "schema",
  "data_object",
  "person",
  "team",
] as const;
