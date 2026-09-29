/**
 * The custom connector, from the admin's side (LEKA-426), against a fake API.
 *
 * What these protect: a custom connector has its own way in, and the
 * native catalogue leads to it; the methods say what each needs and what
 * none can do; the form asks only what the choices make useful, starts the
 * definition from an example the API accepts, and sends nothing a choice
 * made pointless; the test shows what the mapping read, says "not
 * supported" when it is that, and gives a webhook its address.
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
const { TEMPLATES } = await import("@/lib/custom-connectors");

const SECRET = "hd_live_Zq8Xn2Lk4Wv6Tr1Ys3Pm5Ob7Ic9Ua0";

// The schemas as the API sends them (CustomRestConfig, CustomCredentials,
// CustomWebhookConfig, WebhookCredentials), descriptions left out.
const REST = {
  key: "custom_rest",
  display_name: "API REST",
  category: "custom",
  auth_type: "token",
  capabilities: ["records"],
  read_only: true,
  receives: false,
  config_schema: {
    properties: {
      base_url: { type: "string", format: "uri", minLength: 1, maxLength: 2083 },
      auth: {
        type: "string",
        enum: ["none", "bearer", "header", "query", "basic"],
        default: "bearer",
      },
      auth_name: { anyOf: [{ type: "string", maxLength: 64 }, { type: "null" }], default: null },
      definition: { type: "string", format: "json", minLength: 2, maxLength: 100000 },
    },
    required: ["base_url", "definition"],
  },
  credentials_schema: {
    properties: {
      secret: {
        anyOf: [
          { type: "string", format: "password", writeOnly: true, maxLength: 4096 },
          { type: "null" },
        ],
        format: "password",
        writeOnly: true,
        default: null,
      },
      username: { anyOf: [{ type: "string", maxLength: 256 }, { type: "null" }], default: null },
    },
  },
} as unknown as CatalogEntry;

const WEBHOOK = {
  ...REST,
  key: "custom_webhook",
  display_name: "Webhook entrant",
  receives: true,
  config_schema: {
    properties: {
      signature: {
        type: "string",
        enum: ["hmac_sha256", "standard_webhooks", "token"],
        default: "hmac_sha256",
      },
      signature_header: {
        anyOf: [{ type: "string", maxLength: 64 }, { type: "null" }],
        default: null,
      },
      definition: { type: "string", format: "json", minLength: 2, maxLength: 100000 },
    },
    required: ["definition"],
  },
  credentials_schema: {
    properties: {
      secret: {
        type: "string",
        format: "password",
        writeOnly: true,
        minLength: 16,
        maxLength: 4096,
      },
    },
    required: ["secret"],
  },
} as unknown as CatalogEntry;

const GITHUB = {
  ...REST,
  key: "github",
  display_name: "GitHub",
  category: "code",
  capabilities: ["repositories"],
} as unknown as CatalogEntry;

function made(overrides: Partial<Source> = {}): Source {
  return {
    id: "c1",
    type: "custom_rest",
    display_name: "Helpdesk",
    status: "draft",
    config: { base_url: "https://helpdesk.acme.example/api/v2", auth: "bearer", definition: "{}" },
    capabilities: [],
    source_metadata: {},
    health_status: "unknown",
    last_health_check_at: null,
    last_error: null,
    sync_status: "never",
    last_sync_at: null,
    credentials: { hint: "hd_l…9Ua0", rotated_at: new Date().toISOString() },
    created_by: "me",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Source;
}

function open(props: Partial<Parameters<typeof AddSourceDialog>[0]> = {}) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <AddSourceDialog open onOpenChange={() => {}} onDone={vi.fn()} start="custom" {...props} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const PREVIEW = [
  {
    name: "tickets",
    entity: "issue",
    read: 25,
    fields: {
      id: "101",
      title: "VPN drops every hour",
      author: "ada@acme.example",
      "metadata.priority": "high",
    },
    missing: ["url"],
  },
  { name: "agents", entity: null, read: 0, fields: {}, missing: [] },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.catalog.mockResolvedValue([GITHUB, REST, WEBHOOK]);
  api.create.mockResolvedValue(made());
  api.test.mockResolvedValue({
    ok: true,
    result: {
      account: "helpdesk.acme.example",
      capabilities: ["records"],
      warnings: [],
      metadata: {},
      preview: PREVIEW,
    },
    diagnostic: null,
    source: made({ status: "tested" }),
  });
});

describe("a custom connector, from its own entry", () => {
  it("offers the methods, what each needs, and what none can do", async () => {
    open();

    expect(
      await screen.findByRole("heading", { name: "Comment LEKA rejoint-il votre outil ?" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /API REST/ })).toHaveTextContent(
      "Il vous faut : l'adresse de l'API, un token ou une clé, et les ressources à lire",
    );
    expect(screen.getByRole("button", { name: /Webhook entrant/ })).toBeInTheDocument();
    // The catalogue has no GraphQL here: a method without a connector is not offered.
    expect(screen.queryByRole("button", { name: /API GraphQL/ })).not.toBeInTheDocument();
    const unsupported = screen.getByRole("region", { name: "Pas pris en charge aujourd'hui" });
    expect(within(unsupported).getByText(/OAuth, SSO, SAML/)).toBeInTheDocument();
    expect(within(unsupported).getByText(/XML, SOAP, CSV/)).toBeInTheDocument();
    expect(within(unsupported).getByText(/support@leka-core.com/)).toBeInTheDocument();
    expect(screen.getByText("1. Méthode")).toBeInTheDocument();
  });

  it("starts from an example the API accepts, and sends what the choices keep", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /API REST/ }));

    // Bearer, the default: a secret, no header name, no user.
    expect(screen.getByLabelText(/^Secret/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/En-tête ou paramètre/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Utilisateur/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Partir d'un exemple" }));
    expect(screen.getByLabelText(/^Définition/)).toHaveValue(TEMPLATES.custom_rest);
    // Written in: the example is to edit, not to insert twice.
    expect(screen.queryByRole("button", { name: "Partir d'un exemple" })).not.toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText(/Nom de la source/));
    await userEvent.type(screen.getByLabelText(/Nom de la source/), "Helpdesk");
    await userEvent.type(
      screen.getByLabelText(/Adresse de l'API/),
      "https://helpdesk.acme.example/api/v2",
    );
    await userEvent.type(screen.getByLabelText(/^Secret/), SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    expect(api.create).toHaveBeenCalledWith({
      type: "custom_rest",
      display_name: "Helpdesk",
      config: {
        base_url: "https://helpdesk.acme.example/api/v2",
        auth: "bearer",
        definition: TEMPLATES.custom_rest,
      },
      credentials: { secret: SECRET },
    });
  });

  it("asks a user only of Basic, a header's name only of a key sent in one", async () => {
    open({ editing: made({ config: { ...made().config, auth: "basic" } }) });

    expect(await screen.findByLabelText(/^Utilisateur/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/En-tête ou paramètre/)).not.toBeInTheDocument();
  });

  it("shows what the mapping read in each resource, and what it did not find", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /API REST/ }));
    await userEvent.click(screen.getByRole("button", { name: "Partir d'un exemple" }));
    await userEvent.type(
      screen.getByLabelText(/Adresse de l'API/),
      "https://helpdesk.acme.example/api/v2",
    );
    await userEvent.type(screen.getByLabelText(/^Secret/), SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    const read = await screen.findByRole("table", {
      name: "Champs lus dans le premier élément de tickets",
    });
    expect(
      within(read).getByRole("row", { name: "Titre VPN drops every hour" }),
    ).toBeInTheDocument();
    expect(
      within(read).getByRole("row", { name: "priority (métadonnée) high" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ticket ou tâche/)).toBeInTheDocument();
    expect(screen.getByText("Absent du premier élément : Lien")).toBeInTheDocument();
    expect(
      screen.getByText("Première page vide : le mapping n'a pas pu être essayé."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activer la source" })).toBeInTheDocument();
  });

  it("says plainly what is not supported, rather than that it failed", async () => {
    api.test.mockResolvedValue({
      ok: false,
      result: null,
      diagnostic: {
        code: "UNSUPPORTED",
        retryable: false,
        message:
          "« /tickets » répond en XML : les API XML et SOAP ne sont pas prises en charge.",
        remediation: "Écrivez au support LEKA (support@leka-core.com).",
      },
      source: made(),
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /API REST/ }));
    await userEvent.click(screen.getByRole("button", { name: "Partir d'un exemple" }));
    await userEvent.type(
      screen.getByLabelText(/Adresse de l'API/),
      "https://helpdesk.acme.example/api/v2",
    );
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    expect(await screen.findByText("Pas pris en charge aujourd'hui")).toBeInTheDocument();
    expect(screen.queryByText("La connexion a échoué")).not.toBeInTheDocument();
    expect(screen.getByText(/répond en XML/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activer la source" })).not.toBeInTheDocument();
  });

  it("gives a webhook source its address at the test, to copy into the tool", async () => {
    const hooks = made({ id: "w1", type: "custom_webhook", config: {} });
    api.create.mockResolvedValue(hooks);
    api.test.mockResolvedValue({
      ok: true,
      result: { account: null, capabilities: ["records"], warnings: [], metadata: {}, preview: [] },
      diagnostic: null,
      source: { ...hooks, status: "tested" },
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /Webhook entrant/ }));
    await userEvent.click(screen.getByRole("button", { name: "Partir d'un exemple" }));
    await userEvent.type(screen.getByLabelText(/^Secret/), "a-secret-both-sides-share");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer et continuer" }));

    expect(await screen.findByText(/\/api\/v1\/webhooks\/sources\/w1$/)).toBeInTheDocument();
    expect(screen.getByText(/Donnez cette adresse à votre outil/)).toBeInTheDocument();
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { signature: "hmac_sha256", definition: TEMPLATES.custom_webhook },
      }),
    );
  });
});

describe("the native catalogue", () => {
  it("lists the natives only, and leads to a custom connector for a tool not in it", async () => {
    open({ start: "native" });

    expect(await screen.findByRole("button", { name: /GitHub/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /API REST/ })).not.toBeInTheDocument();
    expect(screen.getByText("1. Outil")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Créer un connecteur sur mesure" }));

    expect(await screen.findByRole("button", { name: /API REST/ })).toBeInTheDocument();
    expect(screen.getByText("1. Méthode")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retour" }));
    expect(await screen.findByRole("button", { name: /GitHub/ })).toBeInTheDocument();
  });
});
