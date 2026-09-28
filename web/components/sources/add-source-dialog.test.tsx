/**
 * Connecting a tool, step by step, against a fake API.
 *
 * What these protect: the form is the connector's schema, not a copy of it;
 * what the API refuses is shown where it can be fixed; nothing is activated
 * before a test succeeded; and a source saved half-way is edited, not
 * created twice.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { CatalogEntry, Source } from "@/lib/sources";

const api = {
  catalog: vi.fn(),
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

const { AddSourceDialog } = await import("@/components/sources/add-source-dialog");

const TOKEN = "github_pat_11ABCDEFG0123456789_secret";

const GITHUB = {
  key: "github",
  display_name: "GitHub",
  category: "code",
  auth_type: "token",
  capabilities: ["repositories", "commits"],
  read_only: true,
  config_schema: {
    properties: {
      organization: {
        anyOf: [{ type: "string", maxLength: 100 }, { type: "null" }],
        default: null,
        title: "Organization",
      },
      base_url: {
        type: "string",
        format: "uri",
        default: "https://api.github.com/",
        title: "Base Url",
      },
      repositories: {
        anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }],
        default: null,
      },
    },
  },
  credentials_schema: {
    properties: {
      token: { type: "string", format: "password", writeOnly: true, minLength: 20, title: "Token" },
    },
    required: ["token"],
  },
} as unknown as CatalogEntry;

const SLACK = {
  ...GITHUB,
  key: "slack",
  display_name: "Slack",
  config_schema: { properties: {} },
} as unknown as CatalogEntry;

function draft(overrides: Partial<Source> = {}): Source {
  return {
    id: "s1",
    type: "github",
    display_name: "Acme GitHub",
    status: "draft",
    config: { organization: "acme", base_url: "https://api.github.com/", repositories: null },
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

const onDone = vi.fn();

function open() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <AddSourceDialog open onOpenChange={() => {}} onDone={onDone} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

async function fillConnection() {
  await userEvent.click(await screen.findByRole("button", { name: /GitHub/ }));
  await userEvent.clear(screen.getByLabelText(/Nom de la source/));
  await userEvent.type(screen.getByLabelText(/Nom de la source/), "Acme GitHub");
  await userEvent.type(screen.getByLabelText(/Token d'accès/), TOKEN);
  await userEvent.type(screen.getByLabelText(/Organisation/), "acme");
  await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));
}

const testOk = (source: Source) => ({
  ok: true,
  result: {
    account: "nora",
    capabilities: ["repositories", "commits"],
    warnings: [],
    metadata: {},
  },
  diagnostic: null,
  source: { ...source, status: "tested" },
});

beforeEach(() => {
  vi.clearAllMocks();
  api.catalog.mockResolvedValue([GITHUB, SLACK]);
  api.create.mockResolvedValue(draft());
  api.update.mockImplementation(async (_id: string, body: Partial<Source>) =>
    draft({ config: body.config ?? {} }),
  );
  api.scopeOptions.mockResolvedValue({
    ok: true,
    truncated: false,
    options: [
      { key: "acme/api", name: "acme/api", description: "The API" },
      { key: "acme/web", name: "acme/web" },
    ],
  });
  api.test.mockImplementation(async () => testOk(draft()));
  api.activate.mockResolvedValue(draft({ status: "active" }));
});

describe("adding a source", () => {
  it("goes from the tool to an active source, reading only what was chosen", async () => {
    open();
    await fillConnection();

    // The form was the schema's: the token, the organisation — the default URL left out.
    expect(api.create).toHaveBeenCalledWith({
      type: "github",
      display_name: "Acme GitHub",
      config: { organization: "acme", base_url: "https://api.github.com/" },
      credentials: { token: TOKEN },
    });

    await userEvent.click(await screen.findByLabelText("Seulement une sélection"));
    await userEvent.click(screen.getByRole("checkbox", { name: /acme\/web/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continuer" }));
    expect(api.update).toHaveBeenCalledWith("s1", {
      config: expect.objectContaining({ repositories: ["acme/web"] }),
    });

    expect(await screen.findByText("Connexion réussie")).toBeInTheDocument();
    expect(screen.getByText("Compte : nora")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Activer la source" }));

    expect(api.activate).toHaveBeenCalledWith("s1");
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ status: "active" }));
  });

  it("refuses a short token before asking the API", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /GitHub/ }));
    await userEvent.type(screen.getByLabelText(/Token d'accès/), "short");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    expect(await screen.findByText(/20 caractères/)).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("shows a setting the API refuses on its field", async () => {
    api.create.mockRejectedValue(
      new ApiError(422, "/sources", "The connector refused these settings.", "validation_failed", {
        "config.organization": "Not a valid organisation.",
      }),
    );
    open();
    await fillConnection();

    expect(await screen.findByText("Not a valid organisation.")).toBeInTheDocument();
  });

  it("shows why the vendor refused, and edits rather than creates again", async () => {
    api.scopeOptions.mockResolvedValue({
      ok: false,
      options: [],
      truncated: false,
      diagnostic: {
        code: "AUTH_INVALID",
        retryable: false,
        message: "Le token a été refusé par le fournisseur.",
        remediation: "Vérifiez qu'il a été copié en entier, puis remplacez les identifiants.",
      },
    });
    open();
    await fillConnection();

    expect(
      await screen.findByText("Le token a été refusé par le fournisseur."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Modifier la connexion" }));

    // The token may now stay empty: the stored one is kept.
    expect(screen.getByText(/Laissez vide pour garder le token enregistré/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continuer" }));
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalled();
    expect(api.rotateCredentials).not.toHaveBeenCalled();
  });

  it("does not offer activation when the test fails, and can test again", async () => {
    api.test.mockResolvedValueOnce({
      ok: false,
      result: null,
      source: draft(),
      diagnostic: {
        code: "NOT_FOUND",
        message: "GitHub ne trouve pas cette organisation.",
        remediation: "Vérifiez le nom.",
      },
    });
    open();
    await fillConnection();
    await userEvent.click(await screen.findByRole("button", { name: "Continuer" }));

    expect(await screen.findByText("GitHub ne trouve pas cette organisation.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activer la source" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Relancer le test" }));
    expect(await screen.findByRole("button", { name: "Activer la source" })).toBeInTheDocument();
  });

  it("skips the scope of a connector that has none", async () => {
    api.create.mockResolvedValue(draft({ type: "slack", config: {} }));
    api.scopeOptions.mockRejectedValue(new ApiError(409, "/scope", "No scope.", "conflict"));
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Slack/ }));
    await userEvent.type(screen.getByLabelText(/Token d'accès/), TOKEN);
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    expect(await screen.findByText("Connexion réussie")).toBeInTheDocument();
    expect(api.scopeOptions).not.toHaveBeenCalled();
  });
});
