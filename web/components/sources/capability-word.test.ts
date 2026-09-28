/**
 * A capability's name, and a setting's, in the vendor's own terms.
 *
 * "buckets S3" was shown under Google Cloud and Azure: the word was AWS's,
 * written once for every cloud. Trello's `api_key` would have said "lin_api_…",
 * Linear's.
 */

import { describe, expect, it } from "vitest";

import { capabilityWord, fieldWords } from "@/components/sources/source-panel";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";

const fr = DICTIONARIES.fr;

describe("a capability's word", () => {
  it.each([
    ["aws", "buckets S3"],
    ["gcp", "buckets Cloud Storage"],
    ["azure", "comptes de stockage"],
  ])("is %s's own for its storage", (kind, word) => {
    expect(capabilityWord(fr, "buckets", kind)).toBe(word);
  });

  it.each([
    ["trello", "projects", "tableaux"],
    ["trello", "issues", "cartes"],
    ["clickup", "projects", "listes"],
    ["asana", "issues", "tâches"],
    ["monday", "issues", "éléments"],
    ["slab", "pages", "articles"],
    ["gitlab", "pull_requests", "merge requests"],
    ["datadog", "alerts", "moniteurs et leurs alertes"],
    ["grafana", "events", "annotations"],
    ["bitbucket", "pull_requests", "pull requests"],
    ["guru", "pages", "fiches"],
    ["google_workspace", "drives", "Drive partagés"],
    ["microsoft_365", "drives", "bibliothèques SharePoint et OneDrive"],
    ["postgresql", "schemas", "schémas"],
    ["postgresql", "tables", "tables et vues"],
  ])("is %s's own for its %s", (kind, capability, word) => {
    expect(capabilityWord(fr, capability, kind)).toBe(word);
  });

  it("says no vendor's name when the kind is not known", () => {
    expect(capabilityWord(fr, "buckets")).toBe("stockage objet");
  });

  it("falls back to the general word for a kind with none of its own", () => {
    expect(capabilityWord(fr, "issues", "jira")).toBe("issues");
  });

  it("is the capability itself when nobody named it", () => {
    expect(capabilityWord(fr, "something_new", "aws")).toBe("something_new");
  });
});

describe("a setting's words", () => {
  it("are the tool's own where its secret is its own", () => {
    expect(fieldWords(fr, "api_key", "linear")?.help).toContain("lin_api_");
    expect(fieldWords(fr, "api_key", "trello")?.help).toContain("Power-Up");
    expect(fieldWords(fr, "token", "clickup")?.label).toBe("Jeton personnel");
    // An Atlassian token cannot be read-only; a GitHub one can.
    expect(fieldWords(fr, "token", "jira")?.help).toContain("compte dédié");
    // Datadog's site is not Atlassian's, nor its api_key Linear's.
    expect(fieldWords(fr, "site", "datadog")?.label).toBe("Site Datadog");
    expect(fieldWords(fr, "api_key", "datadog")?.help).not.toContain("lin_api_");
    expect(fieldWords(fr, "token", "github")?.help).toContain("lecture seule suffit");
    // Azure's client id has the Reader role; Microsoft 365's has Graph's permissions.
    expect(fieldWords(fr, "client_id", "microsoft_365")?.help).toContain("Files.Read.All");
    expect(fieldWords(fr, "client_id", "azure")?.help).toContain("Reader");
  });

  it("fall back to the general words, which name no vendor", () => {
    expect(fieldWords(fr, "api_key")?.help).not.toContain("lin_api_");
    expect(fieldWords(fr, "token", "github")).toEqual(fr.sources.fields.token);
  });

  it("are none for a field nobody named", () => {
    expect(fieldWords(fr, "something_new", "trello")).toBeUndefined();
  });
});
