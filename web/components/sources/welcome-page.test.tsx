/**
 * The welcome page: where a new workspace chooses its tools, then connects
 * them one by one in Sources' wizard.
 *
 * What these protect: the catalogue is the API's, by category; what is
 * connected says so from the workspace's own sources; the wizard opens at
 * the tool's connection and, once a tool is done, on the next one; a draft
 * is taken up again rather than created twice.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { CatalogEntry, Source } from "@/lib/sources";

const api = {
  catalog: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  rotateCredentials: vi.fn(),
  scopeOptions: vi.fn(),
  test: vi.fn(),
  activate: vi.fn(),
};

vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: api,
}));

vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/welcome",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const { WelcomePage } = await import("@/components/sources/welcome-page");

const TOKEN = "github_pat_11ABCDEFG0123456789_secret";

function tool(key: string, display_name: string, category: string): CatalogEntry {
  return {
    key,
    display_name,
    category,
    auth_type: "token",
    capabilities: ["repositories"],
    read_only: true,
    config_schema: { properties: {} },
    credentials_schema: {
      properties: {
        token: { type: "string", format: "password", writeOnly: true, minLength: 20 },
      },
      required: ["token"],
    },
  } as unknown as CatalogEntry;
}

const GITHUB = tool("github", "GitHub", "code");
const SLACK = tool("slack", "Slack", "chat");
const DATADOG = tool("datadog", "Datadog", "observability");
const CUSTOM = tool("custom_rest", "API REST", "custom");

function source(overrides: Partial<Source>): Source {
  return {
    id: "s1",
    type: "github",
    display_name: "GitHub",
    status: "draft",
    config: {},
    capabilities: [],
    source_metadata: {},
    health_status: "unknown",
    last_health_check_at: null,
    last_error: null,
    sync_status: "never",
    last_sync_at: null,
    credentials: { hint: "github_pat_…cret", rotated_at: new Date().toISOString() },
    created_by: "me",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Source;
}

const DATADOG_ON = source({ id: "s-dd", type: "datadog", status: "active" });

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <WelcomePage />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.catalog.mockResolvedValue([GITHUB, SLACK, DATADOG, CUSTOM]);
  api.list.mockResolvedValue({ data: [DATADOG_ON] });
  api.create.mockImplementation(async (body: { type: string; display_name: string }) =>
    source({ id: `s-${body.type}`, type: body.type as Source["type"] }),
  );
  api.test.mockImplementation(async (id: string) => ({
    ok: true,
    result: { account: "nora", capabilities: ["repositories"], warnings: [], metadata: {} },
    diagnostic: null,
    source: source({ id, status: "tested" }),
  }));
  api.activate.mockImplementation(async (id: string) =>
    source({ id, type: id.replace("s-", "") as Source["type"], status: "active" }),
  );
});

describe("choosing the tools", () => {
  it("lists the catalogue by category, what is connected saying so", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Développement" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Bienvenue sur LEKA" })).toBeVisible();
    for (const category of ["Communication", "Observabilité"]) {
      expect(screen.getByRole("heading", { name: category })).toBeVisible();
    }
    // A custom connector is not a tool to tick: it has its own way in.
    expect(screen.queryByRole("button", { name: /API REST/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Créer un connecteur sur mesure" })).toBeVisible();

    const datadog = screen.getByRole("button", { name: /Datadog/ });
    expect(datadog).toBeDisabled();
    expect(within(datadog).getByText("Connecté")).toBeVisible();
  });

  it("starts nothing until a tool is chosen, and can be left for later", async () => {
    renderPage();

    const connect = await screen.findByRole("button", { name: "Connecter mes outils" });
    expect(connect).toBeDisabled();
    expect(screen.getByText("Aucun outil choisi pour l'instant.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Plus tard" })).toHaveAttribute("href", "/overview");

    const github = screen.getByRole("button", { name: /GitHub/ });
    await userEvent.click(github);
    expect(github).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 outil choisi")).toBeVisible();
    expect(connect).toBeEnabled();

    await userEvent.click(github);
    expect(github).toHaveAttribute("aria-pressed", "false");
    expect(connect).toBeDisabled();
  });
});

describe("connecting them", () => {
  it("opens the wizard at each tool's connection, one after the other", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /GitHub/ }));
    await userEvent.click(screen.getByRole("button", { name: /Slack/ }));
    await userEvent.click(screen.getByRole("button", { name: "Connecter mes outils" }));

    // GitHub's connection, not the catalogue again — and no way back to it.
    let wizard = await screen.findByRole("dialog");
    const choose = within(wizard).queryByText("Quel outil voulez-vous connecter ?");
    expect(choose).not.toBeInTheDocument();
    expect(within(wizard).queryByRole("button", { name: "Retour" })).not.toBeInTheDocument();
    await userEvent.type(within(wizard).getByLabelText(/Token d'accès/), TOKEN);
    await userEvent.click(within(wizard).getByRole("button", { name: "Enregistrer et continuer" }));
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ type: "github" }));

    api.list.mockResolvedValue({
      data: [DATADOG_ON, source({ id: "s-github", status: "active" })],
    });
    await userEvent.click(await within(wizard).findByRole("button", { name: "Activer la source" }));
    expect(api.activate).toHaveBeenCalledWith("s-github");

    // Then Slack's, on its own.
    wizard = await screen.findByRole("dialog");
    await userEvent.type(within(wizard).getByLabelText(/Token d'accès/), TOKEN);
    await userEvent.click(within(wizard).getByRole("button", { name: "Enregistrer et continuer" }));
    expect(api.create).toHaveBeenLastCalledWith(expect.objectContaining({ type: "slack" }));

    // Stopped there: each row says where its tool stands.
    await userEvent.click(within(wizard).getByRole("button", { name: "Fermer" }));
    expect(await screen.findByText("1 sur 2 connectés")).toBeVisible();
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByRole("link", { name: "Voir la source" })).toHaveAttribute(
      "href",
      "/sources/s-github",
    );
    expect(within(rows[1]).getByRole("button", { name: "Connecter" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Terminer" })).toHaveAttribute("href", "/sources");
  });

  it("takes up a tool left in draft, rather than creating it again", async () => {
    api.list.mockResolvedValue({ data: [source({ id: "s-draft" })] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /GitHub/ }));
    await userEvent.click(screen.getByRole("button", { name: "Connecter mes outils" }));

    const wizard = await screen.findByRole("dialog");
    expect(within(wizard).getByText(/Laissez vide pour garder le token enregistré/)).toBeVisible();
    await userEvent.click(within(wizard).getByRole("button", { name: "Fermer" }));

    expect(screen.getByText("À terminer")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reprendre" })).toBeVisible();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("goes back to the choice, keeping it", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Slack/ }));
    await userEvent.click(screen.getByRole("button", { name: "Connecter mes outils" }));
    const wizard = await screen.findByRole("dialog");
    await userEvent.click(within(wizard).getByRole("button", { name: "Fermer" }));

    await userEvent.click(screen.getByRole("button", { name: "Modifier mon choix" }));

    expect(screen.getByRole("button", { name: /Slack/ })).toHaveAttribute("aria-pressed", "true");
  });
});
