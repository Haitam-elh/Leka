/**
 * One source's page: what it is, and what an admin can do to it.
 *
 * What these protect: a member sees everything and no button; a failed
 * test is explained, not just reported; activation refused for want of a
 * test says so; deletion needs the source's name typed; a source with no
 * connector cannot be tested or changed.
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
};
const push = vi.fn();
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
let permissions = ["source:read", "source:manage"];

vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: api,
}));
vi.mock("@/lib/notify", () => ({ notify }));
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
        message: "Le jeton a été refusé.",
        remediation: "Remplacez-le.",
      },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Tester la connexion" }));

    expect(notify.error).toHaveBeenCalledWith({
      title: "La connexion a échoué",
      description: "Le jeton a été refusé. Remplacez-le.",
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
