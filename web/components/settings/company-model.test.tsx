/**
 * Paramètres → Le modèle de votre entreprise (LEKA-394, LEKA-530).
 *
 * What these protect: on a public plan with no model of its own, nothing —
 * no list of models, no price, no choice of which one answers, no tokens:
 * customers buy what LEKA's agents deliver. Under an Enterprise contract,
 * an admin plugs in the company's Azure OpenAI — what it takes asked, the
 * key sent once, never shown again — tests it, removes it only once asked.
 * A model plugged in before it was the contract's: said, removable, never
 * changed. A member reads, changes nothing.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { ModelSettings, WorkspaceModel } from "@/lib/models";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const api = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), remove: vi.fn(), test: vi.fn() }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/models", async (original) => ({
  ...(await original<typeof import("@/lib/models")>()),
  models: api,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));

const { CompanyModel } = await import("@/components/settings/company-model");

function settings(overrides: Partial<ModelSettings> = {}): ModelSettings {
  return {
    offered: true,
    providers: [
      { name: "google", title: "Google Gemini", needs: ["key"], default_model: "gemini-3.8-flash" },
      { name: "mistral", title: "Mistral AI", needs: ["key"], default_model: "mistral-large-latest" },
      { name: "azure_openai", title: "Azure OpenAI", needs: ["key", "model", "url"], default_model: null },
    ],
    own: null,
    ...overrides,
  };
}

const OWN: WorkspaceModel = {
  provider: "azure_openai",
  model: "gpt-prod",
  base_url: "https://acme.openai.azure.com",
  api_version: "2024-10-21",
  key_hint: "9876",
  enabled: true,
  exclusive: true,
  status: "untested",
  status_detail: null,
  tested_at: null,
  changed_at: new Date().toISOString(),
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <CompanyModel />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "workspace:update"];
  api.get.mockResolvedValue(settings());
});

describe("the company's model", () => {
  it("is nothing on a public plan without one: no model, no price, no choice", async () => {
    api.get.mockResolvedValue(settings({ offered: false }));
    const { container } = show();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByText(/Gemini|tokens|\$/)).toBeNull();
  });

  it("lets an admin under an Enterprise contract plug in the company's Azure OpenAI, test it, remove it", async () => {
    const user = userEvent.setup();
    api.save.mockResolvedValue(settings({ own: OWN }));
    show();
    expect(await screen.findByTestId("model-own-body")).toHaveTextContent("Votre contrat Enterprise");
    expect(screen.getByTestId("company-model")).not.toHaveTextContent(/tokens|\$|par million/);
    await user.click(screen.getByTestId("model-bring"));
    await user.selectOptions(screen.getByTestId("model-provider"), "azure_openai");
    await user.type(screen.getByTestId("model-name"), "gpt-prod");
    await user.type(screen.getByTestId("model-url"), "https://acme.openai.azure.com");
    await user.type(screen.getByTestId("model-version"), "2024-10-21");
    await user.type(screen.getByTestId("model-key"), "azure-secret-key-9876");
    await user.click(screen.getByTestId("model-exclusive"));
    // Saved, it is read again: with the model.
    api.get.mockResolvedValue(settings({ own: OWN }));
    await user.click(screen.getByTestId("model-save"));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith({
        provider: "azure_openai",
        model: "gpt-prod",
        base_url: "https://acme.openai.azure.com",
        api_version: "2024-10-21",
        api_key: "azure-secret-key-9876",
        enabled: true,
        exclusive: true,
      }),
    );
    expect(notices.success).toHaveBeenCalledWith({ title: "Modèle enregistré : testez-le." });

    const line = await screen.findByTestId("model-own-line");
    expect(line).toHaveTextContent("Azure OpenAI");
    expect(line).toHaveTextContent("…9876");
    expect(line).toHaveTextContent("Uniquement le vôtre");
    expect(screen.queryByText("azure-secret-key-9876")).not.toBeInTheDocument();

    api.test.mockResolvedValue({ ok: true, detail: null, latency_ms: 420, model: "gpt-prod", version: "gpt-4.1-2025-04-14" });
    await user.click(screen.getByTestId("model-test"));
    await waitFor(() =>
      expect(notices.success).toHaveBeenCalledWith({ title: "Il répond (420 ms, gpt-4.1-2025-04-14)." }),
    );

    api.remove.mockResolvedValue(undefined);
    await user.click(screen.getByTestId("model-remove"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("les modèles qu'il a choisis pour chaque agent");
    await user.click(within(dialog).getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalled());
  });

  it("says a model plugged in before it was the contract's, lets it be removed, never changed", async () => {
    api.get.mockResolvedValue(settings({ offered: false, own: { ...OWN, exclusive: false } }));
    show();
    expect(await screen.findByTestId("model-own-body")).toHaveTextContent(
      "avant que cette option soit réservée au contrat Enterprise",
    );
    expect(screen.getByTestId("model-own-line")).toHaveTextContent("Azure OpenAI");
    expect(screen.queryByTestId("model-bring")).not.toBeInTheDocument();
    expect(screen.getByTestId("model-remove")).toBeInTheDocument();
  });

  it("lets a member read and change nothing", async () => {
    permissions.value = ["workspace:read"];
    show();
    await screen.findByTestId("company-model");
    expect(screen.queryByTestId("model-bring")).not.toBeInTheDocument();
    expect(screen.getByText("Seuls les admins branchent un modèle.")).toBeInTheDocument();
  });
});
