/**
 * The sidebar, rendered the way a browser renders it.
 *
 * What these protect: the navigation comes from the registry, the current
 * page is marked machine-readably and only once, the primary action is a
 * button rather than a line in the list, counts are announced, and folding
 * the sidebar says out loud what state it is in.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/config/routes";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const pathname = vi.hoisted(() => ({ value: "/overview" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// The session, as LEKA-330 hands it over.
vi.mock("@/lib/auth", () => ({
  auth: {
    me: vi.fn().mockResolvedValue({
      user: { id: "u1", email: "nora@acme.example", email_verified_at: null, last_login_at: null },
      workspaces: [{ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }],
      active_workspace_id: "w1",
    }),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}));

const { AppSidebar } = await import("@/components/shell/app-sidebar");
const { ShellProvider } = await import("@/components/shell/shell-provider");

const fr = DICTIONARIES.fr;
const SIDEBAR_ROUTES = ROUTES.filter((route) => route.showInSidebar);

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
  pathname.value = "/overview";
});

describe("the navigation comes from the registry", () => {
  it("renders every entry it declares, and nothing else", () => {
    renderSidebar();

    const navigation = screen.getByRole("navigation", { name: fr.shell.mainNavigation });
    const links = within(navigation).getAllByRole("link");

    expect(links).toHaveLength(SIDEBAR_ROUTES.length);
    for (const route of SIDEBAR_ROUTES) {
      expect(within(navigation).getByTestId(`nav-${route.id}`)).toHaveAttribute(
        "href",
        route.path,
      );
    }
  });

  it("groups them, under the titles the dictionary gives", () => {
    renderSidebar();

    for (const title of Object.values(fr.groups)) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("speaks French by default", () => {
    renderSidebar();

    expect(screen.getByText(fr.nav.environment)).toBeInTheDocument();
    expect(screen.queryByText(DICTIONARIES.en.nav.environment)).not.toBeInTheDocument();
  });
});

describe("the primary action", () => {
  it("is a button above the list, not one of its lines", () => {
    renderSidebar();

    const navigation = screen.getByRole("navigation", { name: fr.shell.mainNavigation });

    expect(screen.getByTestId("new-intention")).toBeInTheDocument();
    expect(within(navigation).queryByTestId("new-intention")).not.toBeInTheDocument();
  });

  it("is the thing marked as current on the composer, and Intentions is not", () => {
    pathname.value = "/intentions/new";
    renderSidebar();

    expect(screen.getByTestId("new-intention")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-intentions")).not.toHaveAttribute("aria-current");
  });
});

describe("the current page", () => {
  it("is marked once, and on the parent of a detail page", () => {
    pathname.value = "/environment/services/payment-api";
    renderSidebar();

    const marked = screen.getAllByRole("link", { current: "page" });

    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("data-testid", "nav-environment");
  });
});

describe("a count beside an entry", () => {
  it("is announced as part of the link, not left as a lone number", () => {
    renderSidebar({ badges: { approvals: 3 } });

    expect(screen.getByTestId("nav-approvals")).toHaveAccessibleName(
      `${fr.nav.approvals}, 3 éléments en attente`,
    );
  });

  it("is absent at zero rather than a badge reading 0", () => {
    renderSidebar({ badges: { approvals: 0 } });

    expect(screen.getByTestId("nav-approvals")).not.toHaveTextContent("0");
  });
});

describe("availability", () => {
  it("says which pages are not built yet, rather than hiding them", () => {
    renderSidebar();

    expect(screen.getByText(fr.shell.soon)).toBeInTheDocument();
    expect(screen.getByLabelText(fr.shell.planGated)).toBeInTheDocument();
  });
});

describe("folding the sidebar", () => {
  it("says whether it is open, and is labelled either way", async () => {
    const onToggle = vi.fn();
    renderSidebar({ onToggle });

    const button = screen.getByTestId("sidebar-toggle");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAccessibleName(fr.shell.collapseSidebar);

    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("keeps every label reachable for a screen reader on the rail", () => {
    renderSidebar({ collapsed: true });

    expect(screen.getByRole("link", { name: new RegExp(fr.nav.billing) })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: fr.nav.newIntention })).toBeInTheDocument();
  });
});
