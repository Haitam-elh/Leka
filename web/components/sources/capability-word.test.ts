/**
 * A capability's name, in the vendor's own terms.
 *
 * "buckets S3" was shown under Google Cloud and Azure: the word was AWS's,
 * written once for every cloud.
 */

import { describe, expect, it } from "vitest";

import { capabilityWord } from "@/components/sources/source-panel";
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
