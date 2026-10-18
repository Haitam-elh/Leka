/**
 * A connector's form, from its JSON Schema: the whole number (LEKA-349).
 *
 * PostgreSQL's port is the first field that is not text. It must show with
 * its default, refuse what is not a port before the API does, and go to
 * the API as the text typed — which the API reads as a number.
 */

import { describe, expect, it } from "vitest";

import { defaultsOf, fieldsOf, filled, initialOf, zodOf } from "@/lib/sources-form";

const POSTGRESQL = {
  type: "object",
  required: ["host", "database"],
  properties: {
    host: { type: "string", maxLength: 253, title: "Host" },
    port: { type: "integer", default: 5432, minimum: 1, maximum: 65535, title: "Port" },
    database: { type: "string", minLength: 1, maxLength: 63, title: "Database" },
    schemas: { anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }] },
  },
};

describe("a whole-number field", () => {
  const fields = fieldsOf(POSTGRESQL);
  const port = fields.find((field) => field.name === "port");

  it("is read from the schema, with its default and its bounds", () => {
    expect(fields.map((field) => field.name)).toEqual(["host", "port", "database"]);
    expect(port).toMatchObject({ kind: "number", required: false, minimum: 1, maximum: 65535 });
    expect(defaultsOf(fields).port).toBe("5432");
  });

  it.each(["5432", " 6543 ", "1", "65535", ""])("accepts %j", (value) => {
    const valid = { host: "db.acme.example", database: "app", port: value };
    expect(zodOf(fields).safeParse(valid).success).toBe(true);
  });

  it.each(["0", "65536", "54a2", "-1", "5432.5"])("refuses %j", (value) => {
    const invalid = { host: "db.acme.example", database: "app", port: value };
    expect(zodOf(fields).safeParse(invalid).success).toBe(false);
  });

  it("is left out when empty, so the API's default applies", () => {
    expect(filled({ host: "db.acme.example", port: "" })).toEqual({ host: "db.acme.example" });
  });

  it("keeps the source's own when it is edited, never its default", () => {
    expect(initialOf(port!, 6543)).toBe("6543");
    expect(initialOf(port!, undefined)).toBe("5432");
  });
});

/**
 * What LEKA may write (2026-10-18): GitHub's `pull_requests`, Jira's
 * `issues`, Confluence's `pages` — a box to tick, sent as true or false,
 * kept as it is when the source is edited: the API replaces the whole
 * config, so a yes left out would come back a no.
 */
const JIRA = {
  type: "object",
  required: ["site"],
  properties: {
    site: { type: "string", maxLength: 255, title: "Site" },
    projects: { anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }] },
    issues: { type: "boolean", default: false, title: "Issues" },
  },
};

describe("a yes or no", () => {
  const fields = fieldsOf(JIRA);
  const issues = fields.find((field) => field.name === "issues")!;

  it("is a box to tick, off by default", () => {
    expect(fields.map((field) => field.name)).toEqual(["site", "issues"]);
    expect(issues).toMatchObject({ kind: "toggle", required: false, default: "false" });
    expect(initialOf(issues, undefined)).toBe(false);
  });

  it("is kept as the source has it when it is edited", () => {
    expect(initialOf(issues, true)).toBe(true);
  });

  it("is sent as true or false, never left out", () => {
    expect(zodOf(fields).safeParse({ site: "acme", issues: true }).success).toBe(true);
    expect(zodOf(fields).safeParse({ site: "acme", issues: "true" }).success).toBe(false);
    expect(filled({ site: "acme", issues: false })).toEqual({ site: "acme", issues: false });
  });
});

/**
 * A custom source's form (LEKA-350): a closed list — how the secret is sent
 * — and a document — the definition, in JSON — read from the same schema.
 */
const CUSTOM_REST = {
  type: "object",
  required: ["base_url", "definition"],
  properties: {
    base_url: { type: "string", format: "uri", minLength: 1, maxLength: 2083, title: "Base Url" },
    auth: {
      type: "string",
      enum: ["none", "bearer", "header", "query", "basic"],
      default: "bearer",
      title: "Auth",
    },
    auth_name: { anyOf: [{ type: "string", maxLength: 64 }, { type: "null" }], title: "Auth Name" },
    definition: { type: "string", format: "json", minLength: 2, maxLength: 100000, title: "Definition" },
  },
};

describe("a custom source's fields", () => {
  const fields = fieldsOf(CUSTOM_REST);
  const byName = Object.fromEntries(fields.map((field) => [field.name, field]));
  const valid = {
    base_url: "https://helpdesk.acme.example/api",
    auth: "bearer",
    auth_name: "",
    definition: '{"resources": []}',
  };

  it("offers the enum as a choice, with its default", () => {
    expect(byName.auth).toMatchObject({
      kind: "choice",
      options: ["none", "bearer", "header", "query", "basic"],
      required: false,
    });
    expect(defaultsOf(fields).auth).toBe("bearer");
  });

  it("types the definition as a JSON document", () => {
    expect(byName.definition).toMatchObject({ kind: "json", required: true });
  });

  it("accepts a choice it offers and a document that is JSON", () => {
    expect(zodOf(fields).safeParse(valid).success).toBe(true);
  });

  it.each(["oauth", "Bearer"])("refuses the choice %j", (auth) => {
    expect(zodOf(fields).safeParse({ ...valid, auth }).success).toBe(false);
  });

  it.each(['{"resources": [}', "resources: []", '{"a": }'])("refuses the document %j", (definition) => {
    const result = zodOf(fields).safeParse({ ...valid, definition });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toContain("json");
  });
});
