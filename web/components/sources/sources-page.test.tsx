/**
 * The sources screen: mockup 12's layout, the workspace's own figures.
 *
 * What these protect: every number is computed from the sources the API
 * returns — never the mockup's — what is not counted yet says so, and a
 * failed source shows the admin what went wrong and what to do. A custom
 * connector has its own way in, and its sources say they are custom
 * (LEKA-426).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { Source, SourceEvent } from "@/lib/sources";

const list = vi.fn();
const events = vi.fn();
const syncSummaries = vi.fn();
const catalog = vi.fn();
let permissions: string[] = ["source:read", "source:manage"];

vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: {
    list: () => list(),
    events: (id: string) => events(id),
    syncSummaries: () => syncSummaries(),
    catalog: () => catalog(),
  },
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: "me", email: "nora@acme.example" }),
  usePermissions: () => permissions,
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/sources" }));

const { SourcesPage } = await import("@/components/sources/sources-page");

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function source(overrides: Partial<Source>): Source {
  return {
    id: crypto.randomUUID(),
    type: "github",
    display_name: "Acme GitHub",
    status: "active",
    config: {},
    capabilities: ["repositories", "commits", "pull_requests"],
    source_metadata: { login: "nora" },
    health_status: "healthy",
    last_health_check_at: minutesAgo(10),
    last_error: null,
    sync_status: "idle",
    last_sync_at: minutesAgo(4),
    credentials: { hint: "github_pat_…a1b2", rotated_at: minutesAgo(600) },
    created_by: "me",
    created_at: minutesAgo(6000),
    updated_at: minutesAgo(4),
    ...overrides,
  } as Source;
}

const GITHUB = source({});
const GITLAB = source({
  type: "gitlab",
  display_name: "Acme GitLab",
  status: "error",
  health_status: "unhealthy",
  created_by: "someone-else",
  last_error: {
    code: "AUTH_INVALID",
    retryable: false,
    retry_after: null,
    message: "Le token a été refusé par le fournisseur.",
    remediation: "Vérifiez qu'il a été copié en entier, puis remplacez les identifiants.",
    provider_status: 401,
    detail: null,
  },
} as Partial<Source>);
const JIRA = source({
  type: "jira",
  display_name: "Acme Jira",
  status: "draft",
  capabilities: [],
  last_sync_at: null,
  last_health_check_at: null,
  created_by: null,
});

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <SourcesPage />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  permissions = ["source:read", "source:manage"];
  list.mockResolvedValue({ data: [GITHUB, GITLAB, JIRA] });
  events.mockResolvedValue({ data: [] });
  syncSummaries.mockResolvedValue([]);
});

describe("the figures", () => {
  it("are the workspace's own, and what is not counted says so", async () => {
    renderPage();

    const connected = (await screen.findByText("sur 3 au total")).closest("[data-testid^='sources-stat-']") as HTMLElement;
    // Two switched on (active, and in error) of three.
    expect(within(connected).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Comptés dès la première synchronisation")).toBeInTheDocument();
    expect(screen.queryByText("48 320")).not.toBeInTheDocument();
  });
});

describe("what the sync read", () => {
  it("counts the records of each source, and all of them", async () => {
    syncSummaries.mockResolvedValue([
      {
        source_id: GITHUB.id,
        records_total: 12430,
        last_succeeded_at: minutesAgo(4),
        pass_state: "running",
      },
      {
        source_id: GITLAB.id,
        records_total: 70,
        last_succeeded_at: minutesAgo(9),
        pass_state: null,
      },
    ]);
    renderPage();

    const table = await screen.findByRole("table");
    const row = (name: string) => within(table).getByText(name).closest("tr") as HTMLElement;
    expect(await within(row("Acme GitHub")).findByText("12 430")).toBeInTheDocument();
    expect(within(row("Acme Jira")).getByLabelText("Pas encore compté")).toBeInTheDocument();

    const tile = screen.getByText("Éléments synchronisés").closest("[data-testid^='sources-stat-']") as HTMLElement;
    expect(within(tile).getByText("12 500")).toBeInTheDocument();
    expect(within(tile).getByText("lus dans 2 source(s)")).toBeInTheDocument();
    // Running is what a worker holds, not what a source's status says.
    const running = screen.getByText("Synchronisations en cours").closest("[data-testid^='sources-stat-']") as HTMLElement;
    expect(within(running).getByText("1")).toBeInTheDocument();
  });
});

describe("the list", () => {
  it("offers only the categories the workspace has, with their counts", async () => {
    renderPage();
    const filters = await screen.findByRole("group", { name: "Filtrer par catégorie" });

    const buttons = within(filters).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Toutes3", "Développement2", "Projets1"]);

    await userEvent.click(within(filters).getByRole("button", { name: /Projets/ }));
    expect(screen.getByText("Acme Jira")).toBeInTheDocument();
    expect(screen.queryByText("Acme GitHub")).not.toBeInTheDocument();
  });

  it("finds a source by its name or its connector", async () => {
    renderPage();
    await userEvent.type(await screen.findByPlaceholderText("Rechercher une source…"), "gitlab");

    // The search waits for typing to pause.
    await waitFor(() => expect(screen.queryByText("Acme GitHub")).not.toBeInTheDocument());
    expect(screen.getByText("Acme GitLab")).toBeInTheDocument();
  });

  it("names the owner without inventing one", async () => {
    renderPage();
    const table = await screen.findByRole("table");

    const row = (name: string) => within(table).getByText(name).closest("tr") as HTMLElement;
    expect(within(row("Acme GitHub")).getByText("Vous")).toBeInTheDocument();
    expect(within(row("Acme GitLab")).getByText("Un membre")).toBeInTheDocument();
    expect(within(row("Acme Jira")).getByText("Jamais")).toBeInTheDocument();
  });
});

describe("adding", () => {
  it("is offered to whoever may manage sources, and to no one else", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: "Ajouter une source" })).toBeInTheDocument();
  });

  it("is not offered to a member", async () => {
    permissions = ["source:read"];
    renderPage();
    await screen.findByText("Acme GitHub");
    expect(screen.queryByRole("button", { name: "Ajouter une source" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Connecteur sur mesure" }),
    ).not.toBeInTheDocument();
  });

  it("offers a custom connector as its own way in, straight to its methods", async () => {
    catalog.mockResolvedValue([
      {
        key: "custom_rest",
        display_name: "API REST",
        category: "custom",
        capabilities: ["records"],
        config_schema: { properties: {} },
        credentials_schema: { properties: {} },
      },
    ]);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Connecteur sur mesure" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Comment LEKA rejoint-il votre outil ?")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /API REST/ })).toBeInTheDocument();
  });
});

describe("a custom source", () => {
  it("says it is custom where natives say their category", async () => {
    list.mockResolvedValue({
      data: [GITHUB, source({ type: "custom_rest", display_name: "Helpdesk" })],
    });
    renderPage();

    const helpdesk = (await screen.findByText("Helpdesk")).closest("tr") as HTMLElement;
    expect(within(helpdesk).getByText("Sur mesure")).toHaveAttribute(
      "title",
      expect.stringContaining("pas par un connecteur natif"),
    );
    const github = screen.getByText("Acme GitHub").closest("tr") as HTMLElement;
    expect(within(github).queryByText("Sur mesure")).not.toBeInTheDocument();
  });
});

describe("the panel", () => {
  it("shows a failed source's diagnostic and what to do about it", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Acme GitLab"));

    const panel = screen.getByRole("complementary", { name: "Détail de Acme GitLab" });
    const alert = within(panel).getByRole("alert");
    expect(alert).toHaveTextContent("Le token a été refusé par le fournisseur.");
    expect(alert).toHaveTextContent("remplacez les identifiants");

    await userEvent.click(within(panel).getByRole("button", { name: "Fermer le détail" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("keeps the open source in the address, and opens it from there", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Acme GitLab"));
    expect(window.location.search).toBe(`?source=${GITLAB.id}`);
    await userEvent.click(screen.getByRole("button", { name: "Fermer le détail" }));
    expect(window.location.search).toBe("");

    cleanup();
    window.history.replaceState(null, "", `/sources?source=${GITLAB.id}`);
    renderPage();
    expect(await screen.findByRole("complementary", { name: "Détail de Acme GitLab" })).toBeVisible();
    window.history.replaceState(null, "", "/sources");
  });

  it("shows what a source reads, its credentials' hint, and its history", async () => {
    const created = {
      id: "e1",
      type: "created",
      actor_user_id: "me",
      payload: {},
      created_at: minutesAgo(60),
    };
    const failed = {
      id: "e2",
      type: "test_failed",
      actor_user_id: "me",
      payload: { code: "AUTH_INVALID" },
      created_at: minutesAgo(30),
    };
    events.mockResolvedValue({ data: [failed, created] as SourceEvent[] });
    renderPage();
    await userEvent.click(await screen.findByText("Acme GitHub"));

    const panel = screen.getByRole("complementary", { name: "Détail de Acme GitHub" });
    expect(within(panel).getByText("pull requests")).toBeInTheDocument();
    expect(within(panel).getByText(/github_pat_…a1b2/)).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("tab", { name: "Historique" }));
    expect(await within(panel).findByText("Échec du test de connexion")).toBeInTheDocument();
    expect(within(panel).getByText("Source ajoutée")).toBeInTheDocument();
  });

  it("says a source not tested yet has nothing known to read", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Acme Jira"));

    expect(screen.getByText("Connues après le premier test")).toBeInTheDocument();
  });
});

describe("the states", () => {
  it("invites a manager to connect a first source", async () => {
    list.mockResolvedValue({ data: [] });
    renderPage();

    expect(await screen.findByText("Aucune source connectée")).toBeInTheDocument();
    expect(screen.getByText(/Connectez GitHub, GitLab ou Bitbucket/)).toBeInTheDocument();
  });

  it("tells a member who can connect one", async () => {
    permissions = ["source:read"];
    list.mockResolvedValue({ data: [] });
    renderPage();

    expect(await screen.findByText(/Un administrateur du workspace/)).toBeInTheDocument();
  });

  it("says the list could not be loaded", async () => {
    list.mockRejectedValue(new Error("down"));
    renderPage();

    expect(
      await screen.findByRole("button", { name: /réessayer/i }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});
