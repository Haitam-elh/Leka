/**
 * The two pieces every detail page leans on: its tabs, and what it shows
 * when it has nothing to show.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ENTITY_TABS, INTENTION_TABS } from "@/config/routes";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const pathname = vi.hoisted(() => ({ value: "/intentions/42" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

const { RouteTabs } = await import("@/components/shell/route-tabs");
const { RouteState } = await import("@/components/shell/route-state");

const fr = DICTIONARIES.fr;

function mount(children: React.ReactNode) {
  return render(<LocaleProvider>{children}</LocaleProvider>);
}

describe("the tabs of a detail page", () => {
  it("are the ones the route declares, as links", () => {
    pathname.value = "/intentions/42";
    mount(<RouteTabs />);

    const tabs = screen.getAllByRole("link");

    expect(tabs).toHaveLength(INTENTION_TABS.length);
    // The first tab is the page itself: /intentions/42, not /intentions/42/overview.
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("href", "/intentions/42");
    expect(screen.getByTestId("tab-evidence")).toHaveAttribute("href", "/intentions/42/evidence");
  });

  it("mark the one the URL names, and only that one", () => {
    pathname.value = "/intentions/42/evidence";
    mount(<RouteTabs />);

    const current = screen.getAllByRole("link", { current: "page" });

    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAttribute("data-testid", "tab-evidence");
  });

  it("fall back to the first tab when the URL names none", () => {
    pathname.value = "/environment/services/payment-api";
    mount(<RouteTabs />);

    expect(screen.getAllByRole("link")).toHaveLength(ENTITY_TABS.length);
    expect(screen.getByTestId("tab-overview")).toHaveAttribute("aria-current", "page");
  });

  it("show nothing on a page that declares no tabs", () => {
    pathname.value = "/sources";
    const { container } = mount(<RouteTabs />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("a page with nothing to show", () => {
  it("says what happened and what to do next, in every variant", () => {
    for (const variant of ["empty", "unavailable", "plan-gated", "forbidden", "not-found"] as const) {
      const { unmount } = mount(<RouteState variant={variant} />);
      const panel = screen.getByTestId(`route-state-${variant}`);

      expect(within(panel).getByRole("heading")).toBeVisible();
      if (variant !== "empty") {
        // Every dead end offers a way out of it — a button when it acts on
        // this page, a link when it takes you elsewhere.
        const ways = [
          ...within(panel).queryAllByRole("button"),
          ...within(panel).queryAllByRole("link"),
        ];
        expect(ways.length).toBeGreaterThan(0);
      }
      unmount();
    }
  });

  it("offers the plans when a plan is what is missing", () => {
    mount(<RouteState variant="plan-gated" />);

    expect(screen.getByText(fr.states.seeBilling)).toBeVisible();
    expect(screen.getByText(fr.states.planGatedBody)).toBeVisible();
  });

  it("does not pretend that asking for access works yet", () => {
    mount(<RouteState variant="forbidden" />);

    // TODO LEKA-402 gives this button somewhere to send the request. Until
    // then it is disabled rather than silently doing nothing.
    expect(screen.getByText(fr.states.requestAccess).closest("button")).toBeDisabled();
    expect(screen.getByText(fr.states.backToOverview)).toBeVisible();
  });
});
