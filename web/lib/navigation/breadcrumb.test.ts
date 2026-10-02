/**
 * The trail, and the document title, both read out of the registry.
 */

import { describe, expect, it } from "vitest";

import { buildBreadcrumb, documentTitle, humaniseIdentifier } from "@/lib/navigation/breadcrumb";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";

const fr = DICTIONARIES.fr;

describe("the breadcrumb", () => {
  it("is empty on a top-level page, which already has its own title", () => {
    expect(buildBreadcrumb("/sources", fr)).toEqual([]);
  });

  it("climbs the parents, and names the thing you are looking at", () => {
    const crumbs = buildBreadcrumb("/environment/services/payment-api", fr);

    expect(crumbs).toEqual([
      { label: "Mon environnement", href: "/environment" },
      { label: "Payment API", href: undefined },
    ]);
  });

  it("does not link the page you are on", () => {
    const crumbs = buildBreadcrumb("/intentions/42", fr);

    expect(crumbs.at(-1)?.href).toBeUndefined();
    expect(crumbs.at(0)).toEqual({ label: "Intentions", href: "/intentions" });
  });

  it("follows the language", () => {
    expect(buildBreadcrumb("/sources/github", DICTIONARIES.en).at(0)?.label).toBe("Sources");
    expect(buildBreadcrumb("/sources/github", fr).at(0)?.label).toBe("Sources");
    expect(buildBreadcrumb("/environment/services/x", DICTIONARIES.en).at(0)?.label).toBe(
      "My environment",
    );
  });

  it("says nothing for an address that is not a page", () => {
    expect(buildBreadcrumb("/nowhere", fr)).toEqual([]);
  });

  it("turns an identifier into something a person can read", () => {
    expect(humaniseIdentifier("payment-api")).toBe("Payment API");
    expect(humaniseIdentifier("auth_service")).toBe("Auth Service");
    expect(humaniseIdentifier("db")).toBe("DB");
  });
});

describe("the document title", () => {
  it("names the page, then the product", () => {
    expect(documentTitle("/sources", fr)).toBe("Sources · LEKA");
    expect(documentTitle("/activity", DICTIONARIES.en)).toBe("Activity · LEKA");
  });

  it("names the entity rather than its route on a detail page", () => {
    expect(documentTitle("/environment/services/payment-api", fr)).toBe("Payment API · LEKA");
  });

  it("says so when the address matches nothing", () => {
    expect(documentTitle("/nowhere", fr)).toBe("Page introuvable · LEKA");
  });

  it("takes the name a page says it has over its identifier", () => {
    const id = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
    expect(documentTitle(`/environment/services/${id}`, fr, "Payment API")).toBe(
      "Payment API · LEKA",
    );
    expect(documentTitle("/nowhere", fr, "Payment API")).toBe("Page introuvable · LEKA");
  });
});
