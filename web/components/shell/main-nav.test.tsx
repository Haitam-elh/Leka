/**
 * The header's navigation (LEKA-494), its intentions named « Intentions »
 * (LEKA-529).
 *
 * What these protect: the entry reads « Intentions », never « Historique »,
 * in every language the interface has; it opens the same page, /intentions;
 * it is marked on that page and on an intention's, and only there.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DICTIONARIES, LOCALES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const at = vi.hoisted(() => ({ path: "/intentions" }));
vi.mock("next/navigation", () => ({ usePathname: () => at.path }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => ["workspace:read", "intention:read"],
}));
vi.mock("@/lib/nav-badges", () => ({ useNavBadges: () => ({}) }));

const { MainNav } = await import("@/components/shell/main-nav");

function show(path: string) {
  at.path = path;
  return render(
    <LocaleProvider>
      <MainNav />
    </LocaleProvider>,
  );
}

describe("the header's navigation", () => {
  it("names the intentions « Intentions », to the same page, marked there and on each intention", () => {
    for (const path of ["/intentions", "/intentions/i-1/analysis"]) {
      const { unmount } = show(path);
      const entry = screen.getByTestId("nav-intentions");
      expect(entry).toHaveTextContent("Intentions");
      expect(entry).toHaveAttribute("href", "/intentions");
      expect(entry).toHaveAttribute("aria-current", "page");
      expect(screen.queryByText("Historique")).toBeNull();
      expect(screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current"))).toHaveLength(1);
      unmount();
    }
  });

  it("is not marked elsewhere", () => {
    show("/environment");
    expect(screen.getByTestId("nav-intentions")).not.toHaveAttribute("aria-current");
  });

  it("is « Intentions » in every language the interface carries", () => {
    for (const locale of LOCALES) {
      expect(DICTIONARIES[locale].shell.main.intentions, locale).toBe("Intentions");
    }
  });
});
