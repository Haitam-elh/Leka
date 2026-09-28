/**
 * A source's settings as lines, and back (LEKA-351).
 *
 * What these protect: what the API holds comes back as it was after a trip
 * through the editor; each way of writing an arrow is read; a line with one
 * side missing is named, not dropped; blank lines and spaces do not matter.
 */

import { describe, expect, it } from "vitest";

import { fromDraft, hasMapping, type SourceSettings, toDraft } from "@/lib/source-settings";

const SETTINGS: SourceSettings = {
  scope: { include: ["acme/*"], exclude: ["acme/legacy-*", "*/sandbox"] },
  mapping: {
    entity_types: { issues: "incident" },
    services: [{ match: "acme/pay*", service: "billing" }],
    owners: [{ match: "acme/*", team: "payments" }],
    tag_keys: { environment: ["stage"], service: ["app"], owner: [] },
    states: { "QA Review": "in_progress" },
    priorities: { P0: "highest" },
    environments: { prd: "production" },
  },
  retention: { days: 14 },
};

describe("the editor's lines", () => {
  it("give back the settings they were made from", () => {
    const draft = toDraft(SETTINGS);

    expect(draft.exclude).toBe("acme/legacy-*\n*/sandbox");
    expect(draft.services).toBe("acme/pay* → billing");
    expect(draft.states).toBe("QA Review = in_progress");
    expect(draft.retentionDays).toBe("14");
    expect(fromDraft(draft)).toEqual({ settings: SETTINGS, errors: [] });
  });

  it("read a retention in days, empty for LEKA's policy (LEKA-348)", () => {
    const empty = fromDraft({ ...toDraft(SETTINGS), retentionDays: " " });

    expect(empty.settings?.retention).toEqual({ days: null });
    for (const wrong of ["0", "-3", "400", "two weeks", "7.5"]) {
      expect(fromDraft({ ...toDraft(SETTINGS), retentionDays: wrong }).errors).toEqual([
        { field: "retentionDays", line: 1 },
      ]);
    }
  });

  it("read every way of writing an arrow, and ignore blank lines and spaces", () => {
    const draft = {
      ...toDraft({}),
      include: "  acme/api  \n\n acme/web ",
      services: "acme/api -> core\nacme/web => site\nacme/ops→ops",
      tagOwner: "squad, team ,",
    };

    const read = fromDraft(draft);

    expect(read.settings?.scope?.include).toEqual(["acme/api", "acme/web"]);
    expect(read.settings?.mapping?.services).toEqual([
      { match: "acme/api", service: "core" },
      { match: "acme/web", service: "site" },
      { match: "acme/ops", service: "ops" },
    ]);
    expect(read.settings?.mapping?.tag_keys?.owner).toEqual(["squad", "team"]);
  });

  it("name the lines they cannot read", () => {
    const draft = { ...toDraft({}), services: "acme/api → core\nacme/web", states: "= closed" };

    expect(fromDraft(draft)).toEqual({
      settings: null,
      errors: [
        { field: "services", line: 2 },
        { field: "states", line: 1 },
      ],
    });
  });

  it("drop an entity type left blank", () => {
    const draft = { ...toDraft({}), entityTypes: { issues: "incident", commits: "" } };

    expect(fromDraft(draft).settings?.mapping?.entity_types).toEqual({ issues: "incident" });
  });

  it("know when a mapping says nothing", () => {
    expect(hasMapping({})).toBe(false);
    expect(hasMapping(fromDraft(toDraft({})).settings ?? {})).toBe(false);
    expect(hasMapping(SETTINGS)).toBe(true);
  });
});
