import { describe, expect, it } from "vitest";

import { cents } from "@/lib/models";

/** A cost per intention is a fraction of a cent: it must not read « 0 ¢ ». */
describe("cents", () => {
  it("says a cost under a cent by its first figures", () => {
    expect(cents(0.0002, "fr-FR")).toBe("0,02 ¢");
    expect(cents(0.0000123, "fr-FR")).toBe("0,0012 ¢");
  });

  it("says a cent and more to a tenth, and nothing as 0", () => {
    expect(cents(0.011, "fr-FR")).toBe("1,1 ¢");
    expect(cents(0.5, "en-US")).toBe("50 ¢");
    expect(cents(0, "fr-FR")).toBe("0 ¢");
  });
});
