/**
 * The sidebar, rendered the way a browser renders it.
 *
 * What these protect (LEKA-428): the way home, then three pillars, each
 * saying what it is for, their pages under them; Activité and À valider
 * across all three; Administration. Intentions starts open, the others
 * closed; sections open and close, say so, and are remembered; the section
 * you are in opens on arrival, and closes again when you leave it. The
 * current page is marked machine-readably and only once, its section with
 * it; on the rail a section is an icon whose menu holds its pages. Counts
 * are announced; a member sees what a member may open.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SECTIONS_KEY } from "@/components/shell/app-sidebar";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const pathname = vi.hoisted(() => ({ value: "/overview" }));
const search = vi.hoisted(() => ({ value: "" }));

/** Everything an owner has, as docs/permissions.md lists it. */
const OWNER = vi.hoisted(() => [
  "workspace:read", "workspace:update", "workspace:delete", "workspace:transfer",
  "member:read", "member:invite", "member:update_role", "member:remove",
  "source:read", "source:manage",
  "intention:read", "intention:create", "intention:approve", "job:read", "access:read",
]);
/** And everything a member has, which is the interesting half. */
const MEMBER = vi.hoisted(() => [
  "workspace:read", "member:read", "source:read", "intention:read", "intention:create",
]);
const permissions = vi.hoisted(() => ({ value: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useSearchParams: () => new URLSearchParams(search.value),
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

function navigation() {
  return screen.getByRole("navigation", { name: fr.shell.mainNavigation });
}

/** The lines a sighted person reads, top to bottom: open sections only. */
function visibleLabels() {
  return within(navigation())
    .getAllByRole("link")
    .map((link) => link.textContent?.replace(/,.*$/, "").trim());
}

function sectionToggle(id: string) {
  return screen.getByTestId(`nav-section-${id}-toggle`);
}

beforeEach(() => {
  pathname.value = "/overview";
  search.value = "";
  permissions.value = OWNER;
  window.localStorage.clear();
});

describe("the three pillars", () => {
  it("are the product, each saying what it is for, its pages under it", async () => {
    await renderSidebar();

    for (const [id, label, sentence] of [
      ["intentions", "Intentions", "Dites à LEKA ce que vous voulez accomplir."],
      ["environment", "Mon environnement", "Le système vivant de votre entreprise."],
      ["capabilities", "Capacités", "Votre équipe technologique à la demande."],
    ]) {
      const toggle = sectionToggle(id);
      expect(toggle).toHaveTextContent(label);
      expect(toggle).toHaveTextContent(sentence);
    }
  });

  it("starts with Intentions open, the rest closed — short enough to hold whole", async () => {
    await renderSidebar();

    expect(visibleLabels()).toEqual([
      "Mon Dashboard",
      "Nouvelle intention",
      "Mes intentions",
      "À valider",
    ]);
    for (const id of ["environment", "capabilities", "administration"]) {
      expect(sectionToggle(id)).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("draws the approved hierarchy, every section open", async () => {
    const user = userEvent.setup();
    await renderSidebar();

    for (const id of ["environment", "capabilities", "administration"]) {
      await user.click(sectionToggle(id));
    }

    expect(visibleLabels()).toEqual([
      "Mon Dashboard",
      "Nouvelle intention",
      "Mes intentions",
      "À valider",
      "Vue globale",
      "Applications",
      "Infrastructure",
      "Données",
      "Dépendances",
      "Équipes",
      "Événements",
      "Domaines",
      "Qualité",
      "Activité",
      "Capacités disponibles",
      "Mes capacités",
      "Configuration",
      "Sources",
      "Sécurité & gouvernance",
      "Équipe & accès",
      "Facturation",
      "Paramètres",
    ]);
  });

  it("opens each view of « Mon environnement » by its address", async () => {
    await renderSidebar();

    expect(screen.getByTestId("nav-environment-overview")).toHaveAttribute("href", "/environment");
    expect(screen.getByTestId("nav-environment-applications")).toHaveAttribute(
      "href",
      "/environment?tab=applications",
    );
    expect(screen.getByTestId("nav-capabilities-mine")).toHaveAttribute(
      "href",
      "/capabilities?tab=mine",
    );
  });

  it("speaks French by default", async () => {
    await renderSidebar();

    expect(screen.getByText(fr.nav.environment)).toBeInTheDocument();
    expect(screen.queryByText(DICTIONARIES.en.nav.environment)).not.toBeInTheDocument();
  });
});

describe("a section", () => {
  it("opens and closes, and says which it is", async () => {
    const user = userEvent.setup();
    await renderSidebar();

    const administration = sectionToggle("administration");
    await user.click(administration);

    expect(administration).toHaveAttribute("aria-expanded", "true");
    const lines = document.getElementById(administration.getAttribute("aria-controls") ?? "");
    expect(lines).toBeVisible();
    expect(within(lines as HTMLElement).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Sources",
      "Sécurité & gouvernance",
      "Équipe & accès",
      "Facturation",
      "Paramètres",
    ]);

    await user.click(sectionToggle("intentions"));
    expect(sectionToggle("intentions")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Mes intentions" })).not.toBeInTheDocument();
  });

  it("is remembered as the person left it", async () => {
    const user = userEvent.setup();
    const { unmount } = await renderSidebar();

    await user.click(sectionToggle("intentions"));
    await user.click(sectionToggle("administration"));
    unmount();
    await renderSidebar();

    expect(JSON.parse(window.localStorage.getItem(SECTIONS_KEY) ?? "{}")).toEqual({
      intentions: false,
      administration: true,
    });
    expect(sectionToggle("intentions")).toHaveAttribute("aria-expanded", "false");
    expect(sectionToggle("administration")).toHaveAttribute("aria-expanded", "true");
  });

  it("opens on arrival when the page is in it, whatever was remembered", async () => {
    window.localStorage.setItem(SECTIONS_KEY, JSON.stringify({ administration: false }));
    pathname.value = "/settings";
    await renderSidebar();

    expect(sectionToggle("administration")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("nav-settings")).toHaveAttribute("aria-current", "page");
  });

  it("closes again when you leave it, unless you opened it", async () => {
    pathname.value = "/settings";
    const { rerender } = await renderSidebar();
    expect(sectionToggle("administration")).toHaveAttribute("aria-expanded", "true");

    pathname.value = "/activity";
    rerender(
      <LocaleProvider>
        <ShellProvider>
          <AppSidebar collapsed={false} onToggle={() => {}} />
        </ShellProvider>
      </LocaleProvider>,
    );

    expect(sectionToggle("administration")).toHaveAttribute("aria-expanded", "false");
    // Nothing was remembered for it: the person chose nothing.
    expect(window.localStorage.getItem(SECTIONS_KEY)).toBeNull();
  });

  it("survives storage holding something else", async () => {
    window.localStorage.setItem(SECTIONS_KEY, "not json");
    await renderSidebar();

    expect(sectionToggle("intentions")).toHaveAttribute("aria-expanded", "true");
  });
});

describe("the current page", () => {
  it("is marked once, and its section with it", async () => {
    pathname.value = "/intentions";
    await renderSidebar();

    const marked = within(navigation()).getAllByRole("link", { current: "page" });
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("data-testid", "nav-intentions");
    expect(screen.getByTestId("nav-section-intentions")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("nav-section-environment")).not.toHaveAttribute("data-active");
  });

  it("is the composer's line on the composer, and « Mes intentions » is not", async () => {
    pathname.value = "/intentions/new";
    await renderSidebar();

    expect(screen.getByTestId("nav-intention-new")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-intentions")).not.toHaveAttribute("aria-current");
  });

  it("is the view the address asks for", async () => {
    pathname.value = "/environment";
    search.value = "tab=dependencies";
    await renderSidebar();

    const marked = within(navigation()).getAllByRole("link", { current: "page" });
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("data-testid", "nav-environment-dependencies");
  });

  it("is the page a detail page belongs to", async () => {
    pathname.value = "/environment/services/payment-api";
    await renderSidebar();

    const marked = within(navigation()).getAllByRole("link", { current: "page" });
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAttribute("data-testid", "nav-environment-overview");
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

  it("sits under Intentions, and is said by the section when it is folded", async () => {
    const user = userEvent.setup();
    await renderSidebar({ badges: { approvals: 3 } });

    const lines = document.getElementById(
      sectionToggle("intentions").getAttribute("aria-controls") ?? "",
    );
    expect(within(lines as HTMLElement).getByTestId("nav-approvals")).toBeVisible();
    // Open, the line carries it; folded, the section does.
    expect(screen.queryByTestId("nav-section-intentions-badge")).not.toBeInTheDocument();
    await user.click(sectionToggle("intentions"));
    expect(screen.getByTestId("nav-section-intentions-badge")).toHaveTextContent("3");
    expect(sectionToggle("intentions")).toHaveAccessibleName(
      expect.stringContaining("3 éléments en attente"),
    );
  });
});

describe("availability", () => {
  it("shows every place plainly, as the mockup does", async () => {
    await renderSidebar();

    // Not built yet or not in the plan, the page says so when opened
    // (route-views.test.tsx). The line in the list stays a plain line.
    expect(screen.queryByText("Bientôt")).not.toBeInTheDocument();
    expect(screen.getByTestId("nav-capabilities-available")).toHaveTextContent(
      /^Capacités disponibles$/,
    );
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

  it("keeps every line and every section named on the rail", async () => {
    await renderSidebar({ collapsed: true });

    expect(screen.getByRole("link", { name: fr.nav.overview })).toBeInTheDocument();
    for (const id of ["intentions", "environment", "capabilities", "administration"]) {
      expect(sectionToggle(id)).toHaveAccessibleName(
        fr.nav[id as "intentions" | "environment" | "capabilities" | "administration"],
      );
    }
  });

  it("gives a section's pages in a menu beside its icon, the current one marked", async () => {
    const user = userEvent.setup();
    pathname.value = "/environment";
    search.value = "tab=data";
    await renderSidebar({ collapsed: true });

    const environment = sectionToggle("environment");
    expect(environment).toHaveAccessibleName(`${fr.nav.environment}, ${fr.shell.currentSection}`);
    await user.click(environment);

    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("Le système vivant de votre entreprise.")).toBeInTheDocument();
    const data = within(menu).getByRole("menuitem", { name: "Données" });
    expect(data).toHaveAttribute("href", "/environment?tab=data");
    expect(data).toHaveAttribute("aria-current", "page");
    expect(within(menu).getAllByRole("menuitem")).toHaveLength(10);
    // What happened in the environment is one of its lines (2026-10-07).
    expect(within(menu).getByRole("menuitem", { name: "Activité" })).toHaveAttribute(
      "href",
      "/activity",
    );
  });

  it("says on the rail what waits in a section, and in its menu", async () => {
    const user = userEvent.setup();
    await renderSidebar({ collapsed: true, badges: { approvals: 3 } });

    const intentions = sectionToggle("intentions");
    expect(intentions).toHaveAccessibleName(`${fr.nav.intentions}, 3 éléments en attente`);
    await user.click(intentions);
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: /À valider/ })).toHaveTextContent("3");
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

  it("still gives a member the product, all three pillars", async () => {
    permissions.value = MEMBER;
    await renderSidebar();

    // Reading the map and creating intentions is most of the value.
    expect(screen.getByTestId("nav-intention-new")).toBeInTheDocument();
    expect(screen.getByTestId("nav-intentions")).toBeInTheDocument();
    expect(screen.getByTestId("nav-environment-applications")).toBeInTheDocument();
    expect(screen.getByTestId("nav-capabilities-available")).toBeInTheDocument();
    expect(screen.getByTestId("nav-sources")).toBeInTheDocument();
  });
});
