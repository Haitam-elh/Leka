/**
 * One source's page: what it is, and what an admin can do to it.
 *
 * What these protect: a member sees everything and no button; a failed
 * test is explained, not just reported; activation refused for want of a
 * test says so; deletion needs the source's name typed; a source with no
 * connector cannot be tested or changed; a webhook source shows the address
 * to give its system, and what that system sent (LEKA-350).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { CatalogEntry, Source } from "@/lib/sources";

const api = {
  get: vi.fn(),
  events: vi.fn(),
  catalog: vi.fn(),
  test: vi.fn(),
  activate: vi.fn(),
  disable: vi.fn(),
  remove: vi.fn(),
  checkHealth: vi.fn(),
  syncNow: vi.fn(),
  syncs: vi.fn(),
  syncSummaries: vi.fn(),
  runs: vi.fn(),
  deliveries: vi.fn(),
};
const push = vi.fn();
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
let permissions = ["source:read", "source:manage"];

vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: api,
}));
vi.mock("@/lib/notify", () => ({ notify }));
// The settings section (LEKA-351) has its own tests: here, a source never set.
vi.mock("@/lib/source-settings", async (original) => ({
  ...(await original<typeof import("@/lib/source-settings")>()),
  sourceSettings: {
    get: vi.fn().mockResolvedValue({ version: 0, settings: {} }),
    versions: vi.fn().mockResolvedValue({ data: [] }),
    check: vi.fn(),
    save: vi.fn(),
  },
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: "me" }),
  usePermissions: () => permissions,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/sources/s1",
  useRouter: () => ({ push, back: vi.fn(), replace: vi.fn() }),
}));

const { SourcePage } = await import("@/components/sources/source-page");

const GITHUB = {
  key: "github",
  display_name: "GitHub",
  category: "code",
  capabilities: [],
  config_schema: {
    properties: {
      organization: { anyOf: [{ type: "string" }, { type: "null" }] },
      repositories: { anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }] },
    },
  },
  credentials_schema: { properties: {} },
} as unknown as CatalogEntry;

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: "s1",
    type: "github",
    display_name: "Acme GitHub",
    status: "tested",
    config: { organization: "acme", repositories: ["acme/api", "acme/web"] },
    capabilities: ["repositories"],
    source_metadata: { login: "nora" },
    health_status: "unknown",
    last_health_check_at: null,
    last_error: null,
    sync_status: "never",
    last_sync_at: null,
    credentials: null,
    created_by: "me",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Source;
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <SourcePage sourceId="s1" />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["source:read", "source:manage"];
  api.get.mockResolvedValue(source());
  api.events.mockResolvedValue({ data: [] });
  api.catalog.mockResolvedValue([GITHUB]);
  api.syncs.mockResolvedValue({ pass_state: null, capabilities: [] });
  api.syncSummaries.mockResolvedValue([]);
  api.runs.mockResolvedValue({ data: [] });
  api.deliveries.mockResolvedValue({ data: [] });
});

describe("a source's page", () => {
  it("shows its configuration and scope, in words", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Acme GitHub" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("acme/api, acme/web")).toBeInTheDocument();
    expect(screen.getByText("Organisation")).toBeInTheDocument();
  });

  it("gives a member everything to read and no button", async () => {
    permissions = ["source:read"];
    renderPage();

    await screen.findByRole("heading", { level: 1, name: "Acme GitHub" });
    expect(
      screen.queryByRole("button", { name: /Tester|Supprimer|Activer/ }),
    ).not.toBeInTheDocument();
  });

  it("explains a failed test with the vendor's reason and what to do", async () => {
    api.test.mockResolvedValue({
      ok: false,
      source: source(),
      diagnostic: {
        code: "AUTH_INVALID",
        message: "Le token a été refusé.",
        remediation: "Remplacez-le.",
      },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Tester la connexion" }));

    expect(notify.error).toHaveBeenCalledWith({
      title: "La connexion a échoué",
      description: "Le token a été refusé. Remplacez-le.",
    });
  });

  it("says why activation is refused", async () => {
    api.activate.mockRejectedValue(new ApiError(409, "/activate", "Test first.", "conflict"));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Activer" }));

    expect(notify.error).toHaveBeenCalledWith({
      title: expect.stringContaining("Testez la connexion d'abord"),
    });
  });

  it("deletes only once the source's name is typed", async () => {
    api.remove.mockResolvedValue(undefined);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Supprimer" }));

    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Supprimer la source" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole("textbox"), "Acme GitHub");
    await userEvent.click(confirm);

    expect(api.remove).toHaveBeenCalledWith("s1");
    expect(push).toHaveBeenCalledWith("/sources");
  });

  it("cannot test or change a source whose kind has no connector yet", async () => {
    api.get.mockResolvedValue(source({ type: "jira", config: {} }));
    renderPage();

    expect(await screen.findByText(/Aucun connecteur n'est encore disponible/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tester la connexion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Modifier" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supprimer" })).toBeInTheDocument();
  });

  it("says a source that does not exist is not found", async () => {
    api.get.mockRejectedValue(new ApiError(404, "/sources/s1", "No such source.", "not_found"));
    renderPage();

    expect(await screen.findByText("Page introuvable")).toBeInTheDocument();
  });
});

describe("its sync", () => {
  it("shows where each capability stands, and why the last pass failed", async () => {
    api.get.mockResolvedValue(source({ status: "active" }));
    api.syncs.mockResolvedValue({
      pass_state: "running",
      capabilities: [
        {
          capability: "commits",
          status: "idle",
          since: new Date().toISOString(),
          last_started_at: null,
          last_succeeded_at: new Date().toISOString(),
          last_full_at: "2026-09-20T10:00:00Z",
          records_last_run: 10,
          records_total: 8320,
          consecutive_failures: 0,
          last_error: null,
        },
        {
          capability: "issues",
          status: "failed",
          since: null,
          last_started_at: null,
          last_succeeded_at: null,
          last_full_at: null,
          records_last_run: 0,
          records_total: 0,
          consecutive_failures: 3,
          last_error: { code: "RATE_LIMITED", message: "Le quota d'appels est épuisé." },
        },
      ],
    });
    renderPage();

    const section = (await screen.findByRole("heading", { name: "Synchronisation" })).closest(
      "section",
    ) as HTMLElement;
    const row = (name: string) => within(section).getByText(name).closest("tr") as HTMLElement;
    expect(await within(section).findByText("8 320")).toBeInTheDocument();
    expect(within(row("issues")).getByText("Le quota d'appels est épuisé.")).toBeInTheDocument();
    expect(within(row("issues")).getByText("3")).toBeInTheDocument();
    // A worker holds the pass: said once, beside the title.
    expect(within(section).getByRole("status")).toHaveTextContent("Synchronisation…");
  });

  it("says a source not read yet will be read, rather than an empty table", async () => {
    renderPage();

    expect(await screen.findByText(/Pas encore lue/)).toBeInTheDocument();
  });

  it("starts a pass on demand, and a second one is already under way", async () => {
    api.get.mockResolvedValue(source({ status: "active" }));
    api.syncNow.mockResolvedValueOnce({ queued: true }).mockResolvedValueOnce({ queued: false });
    renderPage();
    const button = await screen.findByRole("button", { name: "Synchroniser maintenant" });

    await userEvent.click(button);
    await userEvent.click(button);

    expect(api.syncNow).toHaveBeenCalledWith("s1");
    expect(notify.info).toHaveBeenNthCalledWith(1, {
      title: "Synchronisation lancée",
      description: expect.stringContaining("Acme GitHub"),
    });
    expect(notify.info).toHaveBeenNthCalledWith(2, {
      title: "Une synchronisation de Acme GitHub est déjà en cours.",
    });
  });

  it("is not offered for a source that is not switched on", async () => {
    renderPage(); // tested, not activated

    await screen.findByRole("button", { name: "Tester la connexion" });
    expect(
      screen.queryByRole("button", { name: "Synchroniser maintenant" }),
    ).not.toBeInTheDocument();
  });
});

describe("its passes", () => {
  const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
  const run = (overrides: Record<string, unknown>) => ({
    id: crypto.randomUUID(),
    trigger: "schedule",
    full_read: false,
    status: "succeeded",
    started_at: minutesAgo(60),
    finished_at: minutesAgo(56),
    capability: null,
    records: 1240,
    payloads: 3,
    bytes: 2_400_000,
    error: null,
    ...overrides,
  });

  it("lists them, and says how far the running one has got", async () => {
    api.runs.mockResolvedValue({
      data: [
        run({ status: "running", finished_at: null, capability: "commits", records: 1500 }),
        run({ trigger: "manual", full_read: true }),
        run({ status: "failed", error: { message: "Le token a été refusé." } }),
        run({ trigger: "activation", status: "abandoned" }),
      ],
    });
    renderPage();

    const section = (
      await screen.findByRole("heading", { name: "Historique des synchronisations" })
    ).closest("section") as HTMLElement;
    const progress = await within(section).findByText(/Lecture des commits/);
    expect(progress).toHaveTextContent("Lecture des commits : 1 500 élément(s) jusqu'ici");
    expect(progress).toHaveAttribute("role", "status");
    const rows = within(section).getAllByRole("row").slice(1);
    expect(within(rows[1]).getByText("Un administrateur")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Complète")).toBeInTheDocument();
    expect(within(rows[1]).getByText("4 min 00 s")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2,3 Mo")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Le token a été refusé.")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Interrompue")).toBeInTheDocument();
  });

  it("says when there has been none", async () => {
    renderPage();

    expect(await screen.findByText("Aucune synchronisation pour l'instant.")).toBeInTheDocument();
  });
});

describe("its reception, for a source its system sends to", () => {
  const WEBHOOK = {
    key: "custom_webhook",
    display_name: "Webhook entrant",
    category: "custom",
    capabilities: ["records"],
    receives: true,
    config_schema: {
      properties: {
        signature: { type: "string", enum: ["hmac_sha256", "standard_webhooks", "token"] },
        signature_header: { anyOf: [{ type: "string" }, { type: "null" }] },
        definition: { type: "string", format: "json" },
      },
    },
    credentials_schema: { properties: {} },
  } as unknown as CatalogEntry;
  const hooks = (overrides: Partial<Source> = {}) =>
    source({
      type: "custom_webhook",
      display_name: "Helpdesk hooks",
      status: "active",
      config: {
        signature: "hmac_sha256",
        signature_header: "X-Hub-Signature-256",
        definition: '{"resources": []}',
      },
      capabilities: ["records"],
      ...overrides,
    });
  const delivery = (overrides: Record<string, unknown>) => ({
    id: crypto.randomUUID(),
    received_at: new Date().toISOString(),
    status: "stored",
    delivery_id: null,
    size_bytes: 420,
    resource: "tickets",
    records: 1,
    gone: 0,
    error: null,
    processed_at: new Date().toISOString(),
    ...overrides,
  });

  async function reception(): Promise<HTMLElement> {
    const heading = await screen.findByRole("heading", { name: "Réception" });
    return heading.closest("section") as HTMLElement;
  }

  it("gives the address to copy into the system, and how it signs", async () => {
    api.get.mockResolvedValue(hooks());
    api.catalog.mockResolvedValue([WEBHOOK]);
    renderPage();

    const section = await reception();
    expect(within(section).getByText(/\/api\/v1\/webhooks\/sources\/s1$/)).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: /Copier/ })).toBeInTheDocument();
    expect(
      within(section).getByText(
        "HMAC-SHA256 du corps, en hexadécimal ou en base64, dans l'en-tête X-Hub-Signature-256",
      ),
    ).toBeInTheDocument();
    expect(within(section).queryByText(/Activez la source/)).not.toBeInTheDocument();
  });

  it("lists what was sent: stored, ignored, refused and why", async () => {
    api.get.mockResolvedValue(hooks());
    api.catalog.mockResolvedValue([WEBHOOK]);
    api.deliveries.mockResolvedValue({
      data: [
        delivery({
          status: "rejected",
          resource: null,
          records: 0,
          error: { reason: "unmapped", message: "« tickets », record 0: no id at « id »." },
        }),
        delivery({ records: 1, gone: 1 }),
        delivery({ status: "ignored", resource: null, records: 0, processed_at: null }),
      ],
    });
    renderPage();

    const section = await reception();
    await within(section).findByText("Refusée");
    const rows = within(section).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Refusée")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Mapping incomplet")).toBeInTheDocument();
    expect(
      within(rows[0]).getByText("« tickets », record 0: no id at « id »."),
    ).toBeInTheDocument();
    expect(within(rows[1]).getByText("Enregistrée")).toBeInTheDocument();
    expect(within(rows[1]).getByText("1 · 1 supprimé(s)")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Ignorée")).toBeInTheDocument();
    expect(
      within(rows[2]).getByText("Aucune ressource de la définition ne la reconnaît."),
    ).toBeInTheDocument();
  });

  it("says a source not switched on refuses what it is sent", async () => {
    api.get.mockResolvedValue(hooks({ status: "tested" }));
    api.catalog.mockResolvedValue([WEBHOOK]);
    renderPage();

    const section = await reception();
    expect(
      within(section).getByText(
        "Activez la source pour qu'elle reçoive : d'ici là, les livraisons sont refusées.",
      ),
    ).toHaveAttribute("role", "status");
    expect(
      await within(section).findByText("Aucune livraison reçue pour l'instant."),
    ).toBeInTheDocument();
  });

  it("is not there for a source LEKA reads", async () => {
    renderPage();

    await screen.findByRole("heading", { level: 1, name: "Acme GitHub" });
    await screen.findByText("acme/api, acme/web");
    expect(screen.queryByRole("heading", { name: "Réception" })).not.toBeInTheDocument();
    expect(api.deliveries).not.toHaveBeenCalled();
  });
});
