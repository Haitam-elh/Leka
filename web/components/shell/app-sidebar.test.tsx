/**
 * The sidebar, rendered the way a browser renders it.
 *
 * What these protect: the navigation is the mockup's — one list, in its
 * order, "Nouvelle intention" as its second line, no group titles — and it
 * comes from the registry; the current page is marked machine-readably and
 * only once, counts are announced, and folding the sidebar says out loud
 * what state it is in.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/config/routes";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const pathname = vi.hoisted(() => ({ value: "/overview" }));

/** Everything an owner has, as docs/permissions.md lists it. */
const OWNER = vi.hoisted(() => [
  "workspace:read", "workspace:update", "workspace:delete", "workspace:transfer",
  "member:read", "member:invite", "member:update_role", "member:remove",
  "source:read", "source:manage",
  "intention:read", "intention:create", "intention:approve", "job:read",
]);
/** And everything a member has, which is the interesting half. */
const MEMBER = vi.hoisted(() => [
  "workspace:read", "member:read", "source:read", "intention:read", "intention:create",
]);
const permissions = vi.hoisted(() => ({ value: [] as string[] }));

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

vi.mock("@/lib/workspace", () => ({
  workspace: {
    current: vi.fn(async () => ({
      workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
      role: "owner",
      permissions: permissions.value,
    })),
  },
}));

const { AppSidebar } = await import("@/components/shell/app-sidebar");
const { ShellProvider } = await import("@/components/shell/shell-provider");

const fr = DICTIONARIES.fr;
const SIDEBAR_ROUTES = ROUTES.filter((route) => route.showInSidebar);

async function renderSidebar(props: Partial<Parameters<typeof AppSidebar>[0]> = {}) {
  const rendered = render(
    <LocaleProvider>
      <ShellProvider>
        <AppSidebar collapsed={false} onToggle={() => {}} {...props} />
      </ShellProvider>
    </LocaleProvider>,
  );
  // The permissions arrive from the API a tick later; every assertion below
  // is about what the sidebar shows once it knows them.
  await screen.findByTestId("nav-overview");
  return rendered;
}

beforeEach(() => {
  pathname.value = "/overview";
  permissions.value = OWNER;
});

describe("the navigation comes from the registry", () => {
  it("renders every entry it declares, and nothing else", async () => {
    await renderSidebar();

    const navigation = screen.getByRole("navigation", { name: fr.shell.mainNavigation });
    const links = within(navigation).getAllByRole("link");

    // Plus "Nouvelle intention", which is a line of the list but not an entry.
    expect(links).toHaveLength(SIDEBAR_ROUTES.length + 1);
    for (const route of SIDEBAR_ROUTES) {
      expect(within(navigation).getByTestId(`nav-${route.id}`)).toHaveAttribute(
        "href",
        route.path,
      );
    }
  });

  it("lists them in the mockup's order, as one list with no titles", async () => {
    await renderSidebar();

    const navigation = screen.getByRole("navigation", { name: fr.shell.mainNavigation });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent?.replace(/,.*$/, "").trim());

    // docs/product/mockups/01-vue-ensemble.jpeg, top to bottom.
    expect(labels).toEqual([
      "Vue d'ensemble",
      "Nouvelle intention",
      "Intentions",
      "Mon environnement",
      "Activité",
      "À valider",
      "Capacités",
      "Sources",
      "Sécurité & gouvernance",
      "Équipe & accès",
      "Facturation",
      "Paramètres",
    ]);
    for (const title of ["Travail", "Connaissance", "Administration"]) {
      expect(screen.queryByText(title)).not.toBeInTheDocument();
    }
  });

  it("speaks French by default", async () => {
    await renderSidebar();

    expect(screen.getByText(fr.nav.environment)).toBeInTheDocument();
    expect(screen.queryByText(DICTIONARIES.en.nav.environment)).not.toBeInTheDocument();
  });
});

describe("the primary action", () => {
  it("is the second line of the list, right under the way home", async () => {
    await renderSidebar();

    const navigation = screen.getByRole("navigation", { name: fr.shell.mainNavigation });
    const links = within(navigation).getAllByRole("link");

    expect(links[1]).toBe(within(navigation).getByTestId("new-intention"));
  });

  it("is the thing marked as current on the composer, and Intentions is not", async () => {
    pathname.value = "/intentions/new";
    await renderSidebar();

    expect(screen.getByTestId("new-intention")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-intentions")).not.toHaveAttribute("aria-current");
  });
});

describe("the current page", () => {
  it("is marked once, and on the parent of a detail page", async () => {
    pathname.value = "/environment/services/payment-api";
    await renderSidebar();

    const marked = screen.getAllByRole("link", { current: "page" });

    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("data-testid", "nav-environment");
  });
});

describe("a count beside an entry", () => {
  it("is announced as part of the link, not left as a lone number", async () => {
    await renderSidebar({ badges: { approvals: 3 } });

    expect(screen.getByTestId("nav-approvals")).toHaveAccessibleName(
      `${fr.nav.approvals}, 3 éléments en attente`,
    );
  });

  it("is absent at zero rather than a badge reading 0", async () => {
    await renderSidebar({ badges: { approvals: 0 } });

    expect(screen.getByTestId("nav-approvals")).not.toHaveTextContent("0");
  });
});

describe("availability", () => {
  it("shows every place plainly, as the mockup does", async () => {
    await renderSidebar();

    // Not built yet or not in the plan, the page says so when opened
    // (route-views.test.tsx). The line in the list stays a plain line.
    expect(screen.queryByText("Bientôt")).not.toBeInTheDocument();
    expect(screen.getByTestId("nav-capabilities")).toHaveTextContent(/^Capacités$/);
    expect(screen.getByTestId("nav-governance")).toHaveTextContent(/^Sécurité & gouvernance$/);
  });

  it("gives the role in words, not the API's", async () => {
    await renderSidebar();

    expect(await screen.findByText("Propriétaire")).toBeInTheDocument();
    expect(screen.queryByText("owner")).not.toBeInTheDocument();
  });
});

describe("folding the sidebar", () => {
  it("says whether it is open, and is labelled either way", async () => {
    const onToggle = vi.fn();
    await renderSidebar({ onToggle });

    const button = screen.getByTestId("sidebar-toggle");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAccessibleName(fr.shell.collapseSidebar);

    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("keeps every label reachable for a screen reader on the rail", async () => {
    await renderSidebar({ collapsed: true });

    expect(screen.getByRole("link", { name: new RegExp(fr.nav.billing) })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: fr.nav.newIntention })).toBeInTheDocument();
  });
});

describe("what a role may see", () => {
  it("hides from a member what a member may never open", async () => {
    permissions.value = MEMBER;
    await renderSidebar();

    // Approving, inviting and paying are an admin's business.
    expect(screen.queryByTestId("nav-approvals")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-team")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-billing")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-governance")).not.toBeInTheDocument();
  });

  it("still gives a member the product", async () => {
    permissions.value = MEMBER;
    await renderSidebar();

    // Reading the map and creating intentions is most of the value.
    expect(screen.getByTestId("nav-environment")).toBeInTheDocument();
    expect(screen.getByTestId("nav-intentions")).toBeInTheDocument();
    expect(screen.getByTestId("nav-sources")).toBeInTheDocument();
    expect(screen.getByTestId("new-intention")).toBeInTheDocument();
  });
});
