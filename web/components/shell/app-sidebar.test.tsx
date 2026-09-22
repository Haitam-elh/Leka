/**
 * The sidebar, rendered the way a browser renders it.
 *
 * What these protect is not the markup but four promises the rest of the
 * product leans on: the navigation comes from the config, the current page
 * is marked machine-readably, a count is shown, and the fold button says
 * out loud what state it is in.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { activeEntry, NAVIGATION } from "@/config/navigation";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";

const pathname = vi.hoisted(() => ({ value: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// The session, as LEKA-330 hands it over. Mocked at the module boundary
// rather than faked inside the provider: the provider's own job — call,
// redirect on 401, surface an unreachable API — stays under test elsewhere.
vi.mock("@/lib/auth", () => ({
  auth: {
    me: vi.fn().mockResolvedValue({
      user: { id: "u1", email: "nora@acme.example", email_verified_at: null, last_login_at: null },
      workspaces: [
        { id: "w1", name: "Acme Corp", slug: "acme", role: "admin" },
        { id: "w2", name: "Globex", slug: "globex", role: "member" },
      ],
      active_workspace_id: "w1",
    }),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}));

const { AppSidebar } = await import("@/components/shell/app-sidebar");
const { ShellProvider } = await import("@/components/shell/shell-provider");

const en = DICTIONARIES.en;

function renderSidebar(props: Partial<Parameters<typeof AppSidebar>[0]> = {}) {
  return render(
    <LocaleProvider>
      <ShellProvider>
        <AppSidebar collapsed={false} onToggle={() => {}} {...props} />
      </ShellProvider>
    </LocaleProvider>,
  );
}

beforeEach(() => {
  pathname.value = "/";
});

describe("the navigation comes from the config", () => {
  it("renders every entry, in order, and nothing else", () => {
    renderSidebar();

    const navigation = screen.getByRole("navigation", { name: en.shell.mainNavigation });
    const links = within(navigation).getAllByRole("link");

    expect(links).toHaveLength(NAVIGATION.length);
    expect(links.map((link) => link.textContent?.trim())).toEqual(
      NAVIGATION.map((entry) => expect.stringContaining(en.nav[entry.labelKey])),
    );
  });

  it("speaks the language the interface is set to", () => {
    renderSidebar();

    // English by default; the French label must not be on screen.
    expect(screen.getByText(en.nav.environment)).toBeInTheDocument();
    expect(screen.queryByText(DICTIONARIES.fr.nav.environment)).not.toBeInTheDocument();
  });
});

describe("the current page", () => {
  it("is the only one marked as current", () => {
    pathname.value = "/sources";
    renderSidebar();

    const current = screen.getAllByRole("link", { current: "page" });

    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(en.nav.sources);
  });

  it("is the most specific match, not merely a prefix", () => {
    // /intentions/new matches both entries. The one the person is on wins.
    expect(activeEntry("/intentions/new")?.id).toBe("new-intention");
    expect(activeEntry("/intentions")?.id).toBe("intentions");
    expect(activeEntry("/intentions/42")?.id).toBe("intentions");
  });

  it("does not light up the overview on every route", () => {
    // "/" is a prefix of everything. Without the exact match, every page
    // would show two current items and the mark would mean nothing.
    expect(activeEntry("/sources")?.id).toBe("sources");
    expect(activeEntry("/")?.id).toBe("overview");
  });
});

describe("a count beside an entry", () => {
  it("is shown when there is one", () => {
    renderSidebar({ badges: { pendingApprovals: 3 } });

    const approvals = screen.getByTestId("nav-approvals");

    expect(approvals).toHaveTextContent("3");
  });

  it("is absent at zero, rather than a badge reading 0", () => {
    renderSidebar({ badges: { pendingApprovals: 0 } });

    expect(screen.getByTestId("nav-approvals")).not.toHaveTextContent("0");
  });
});

describe("folding the sidebar", () => {
  it("says whether it is open, and the button is labelled either way", async () => {
    const onToggle = vi.fn();
    const { rerender } = renderSidebar({ onToggle });

    const button = screen.getByTestId("sidebar-toggle");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAccessibleName(en.shell.collapseSidebar);
    expect(button).toHaveAttribute("aria-controls", "app-sidebar");

    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();

    rerender(
      <LocaleProvider>
        <ShellProvider>
          <AppSidebar collapsed onToggle={onToggle} />
        </ShellProvider>
      </LocaleProvider>,
    );

    const folded = screen.getByTestId("sidebar-toggle");
    expect(folded).toHaveAttribute("aria-expanded", "false");
    expect(folded).toHaveAccessibleName(en.shell.expandSidebar);
  });

  it("keeps every label reachable for a screen reader", () => {
    renderSidebar({ collapsed: true });

    // Hidden to the eye, still in the accessibility tree: a rail of twelve
    // unnamed icons is unusable without a mouse and a good memory.
    expect(screen.getByRole("link", { name: new RegExp(en.nav.billing) })).toBeInTheDocument();
  });
});
