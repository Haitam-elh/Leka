/**
 * What the custom connectors (LEKA-350) need of the screens that their
 * JSON Schemas cannot say (LEKA-426): which kinds they are, which field
 * matters for which choice, and a definition to start from.
 *
 * The schemas stay the source of truth for what exists and what is valid;
 * this only hides a field that the choice made above it makes pointless —
 * a header name without a header, a user without Basic — and fills an
 * empty definition with one that works, to edit rather than to write.
 */

import { KIND_CATEGORY, type SourceKind } from "@/lib/sources";

export const CUSTOM_KINDS = ["custom_rest", "custom_graphql", "custom_webhook"] as const;

/** A connector described by the customer's team, not one LEKA ships. */
export function isCustom(kind: string): boolean {
  return KIND_CATEGORY[kind as SourceKind] === "custom";
}

type Values = Record<string, unknown>;
type Rule = (config: Values) => boolean;

const named: Rule = (config) => config.auth === "header" || config.auth === "query";
const basic: Rule = (config) => config.auth === "basic";
const withSecret: Rule = (config) => config.auth !== "none";

const SHOWN_WHEN: Record<string, Record<string, Rule>> = {
  custom_rest: { auth_name: named, username: basic, secret: withSecret },
  custom_graphql: { auth_name: named, username: basic, secret: withSecret },
  custom_webhook: { signature_header: (config) => config.signature !== "standard_webhooks" },
};

/** Whether a field of this kind's form matters, given the choices made. */
export function shownFor(kind: string, field: string, config: Values): boolean {
  return SHOWN_WHEN[kind]?.[field]?.(config) ?? true;
}

/** Only the fields that matter: what a hidden field holds is not sent. */
export function shownOnly<T>(
  kind: string,
  values: Record<string, T>,
  config: Values,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(values).filter(([field]) => shownFor(kind, field, config)),
  );
}

const REST = {
  resources: [
    {
      name: "tickets",
      entity: "issue",
      path: "/tickets",
      params: { status: "open" },
      items: "data",
      pagination: {
        type: "cursor",
        next: "meta.next_cursor",
        param: "cursor",
        size_param: "limit",
        size: 100,
      },
      mapping: {
        id: "id",
        title: "subject",
        url: "html_url",
        state: "status",
        updated_at: "updated_at",
        author: "requester.email",
        metadata: { priority: "priority" },
      },
    },
  ],
};

const GRAPHQL = {
  resources: [
    {
      name: "issues",
      entity: "issue",
      query:
        "query Issues($first: Int!, $after: String) { issues(first: $first, after: $after) " +
        "{ nodes { id title url state updatedAt } pageInfo { endCursor hasNextPage } } }",
      items: "data.issues.nodes",
      pagination: {
        type: "cursor",
        next: "data.issues.pageInfo.endCursor",
        has_next: "data.issues.pageInfo.hasNextPage",
        variable: "after",
        size_variable: "first",
        size: 100,
      },
      mapping: { id: "id", title: "title", url: "url", state: "state", updated_at: "updatedAt" },
    },
  ],
};

const WEBHOOK = {
  resources: [
    {
      name: "tickets",
      entity: "issue",
      match: { path: "event", equals: ["ticket.created", "ticket.updated", "ticket.deleted"] },
      deleted: { path: "event", equals: "ticket.deleted" },
      items: "ticket",
      mapping: {
        id: "id",
        title: "subject",
        url: "html_url",
        state: "status",
        updated_at: "updated_at",
        author: "requester.email",
      },
    },
  ],
};

/** A definition that works, per kind — the documentation's own examples. */
export const TEMPLATES: Record<string, string> = {
  custom_rest: JSON.stringify(REST, null, 2),
  custom_graphql: JSON.stringify(GRAPHQL, null, 2),
  custom_webhook: JSON.stringify(WEBHOOK, null, 2),
};
