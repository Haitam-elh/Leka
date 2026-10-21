/**
 * Paramètres → Modèle de langage (LEKA-394).
 *
 * What these protect: LEKA's default model is said — Gemini 3.8 Flash, its
 * list price and the one to come, whether a key is set — and who answers,
 * in order; nobody, said, when no model can. An admin plugs in the
 * company's Azure OpenAI — what it takes asked, the key sent once, never
 * shown again — tests it, removes it only once asked. What was asked of
 * models over 30 days: counted, priced, by model and by use. A member
 * reads, changes nothing. Which of LEKA's models answers first here:
 * chosen in one click — Mistral rather than Gemini — and back (2026-10-21).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { ModelGateway, ModelProfile, ModelUsage } from "@/lib/models";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const api = vi.hoisted(() => ({
  get: vi.fn(),
  save: vi.fn(),
  remove: vi.fn(),
  test: vi.fn(),
  usage: vi.fn(),
  choose: vi.fn(),
  unchoose: vi.fn(),
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/models", async (original) => ({
  ...(await original<typeof import("@/lib/models")>()),
  models: api,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));

const { LanguageModel } = await import("@/components/settings/language-model");

const FLASH: ModelProfile = {
  provider: "google",
  model: "gemini-3.8-flash",
  title: "Gemini 3.8 Flash",
  context: 1_048_576,
  output: 65_536,
  structured: true,
  tools: true,
  quality: 3,
  speed: 3,
  price: { since: "2025-01-01", per_million_in: 0.75, per_million_out: 3.75 },
  next_price: { since: "2027-01-01", per_million_in: 1.5, per_million_out: 7.5 },
  known: true,
};
const LARGE: ModelProfile = { ...FLASH, provider: "mistral", model: "mistral-large-latest", title: "Mistral Large", next_price: null };

function gateway(overrides: Partial<ModelGateway> = {}): ModelGateway {
  return {
    default: FLASH,
    default_ready: true,
    fallbacks: [LARGE],
    providers: [
      { name: "google", title: "Google Gemini", needs: ["key"], default_model: "gemini-3.8-flash", leka_holds: true, models: [FLASH] },
      { name: "mistral", title: "Mistral AI", needs: ["key"], default_model: "mistral-large-latest", leka_holds: true, models: [LARGE] },
      { name: "azure_openai", title: "Azure OpenAI", needs: ["key", "model", "url"], default_model: null, leka_holds: false, models: [] },
    ],
    own: null,
    answering: [
      { provider: "google", model: "gemini-3.8-flash", title: "Gemini 3.8 Flash", owner: "leka", why: "default" },
      { provider: "mistral", model: "mistral-large-latest", title: "Mistral Large", owner: "leka", why: "fallback" },
    ],
    ready: true,
    ...overrides,
  };
}

const TALLY = {
  calls: 0,
  failed: 0,
  tokens_in: 0,
  tokens_out: 0,
  tokens_cached: 0,
  cost_usd: 0,
  unpriced: 0,
  average_latency_ms: 0,
};

function usage(overrides: Partial<ModelUsage> = {}): ModelUsage {
  return {
    days: 30,
    total: {
      ...TALLY,
      calls: 12,
      failed: 1,
      tokens_in: 9000,
      tokens_out: 3000,
      tokens_cached: 4500,
      cost_usd: 0.0181,
      unpriced: 2,
    },
    previous: TALLY,
    leka: { ...TALLY, calls: 10 },
    own: { ...TALLY, calls: 2, unpriced: 2 },
    fallbacks: 1,
    by_day: [],
    by_model: [{ provider: "google", model: "gemini-3.8-flash", title: "Gemini 3.8 Flash", tally: { ...TALLY, calls: 10, cost_usd: 0.0181 } }],
    by_purpose: [
      { purpose: "intention.understanding", tally: { ...TALLY, calls: 7, cost_usd: 0.003 } },
      { purpose: "enrichment.summary", tally: { ...TALLY, calls: 2, cost_usd: 0.0126 } },
    ],
    runs: { succeeded: 9, timed_out: 1 },
    latest_runs: [],
    intentions: 4,
    per_intention_usd: 0.0112,
    latest: [
      {
        id: "c1",
        at: new Date().toISOString(),
        purpose: "capability.synthesis",
        ref: "intention:1",
        provider: "google",
        model: "gemini-3.8-flash",
        version: "gemini-3.8-flash-001",
        owner: "leka",
        route: "default",
        attempt: 1,
        status: "ok",
        error: null,
        tokens_in: 900,
        tokens_out: 200,
        tokens_cached: 0,
        cost_usd: 0.0014,
        latency_ms: 1200,
      },
    ],
    ...overrides,
  };
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <LanguageModel />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "workspace:update"];
  api.get.mockResolvedValue(gateway());
  api.usage.mockResolvedValue(usage());
});

describe("the language model", () => {
  it("says LEKA's default, its price, who answers, and what was asked", async () => {
    show();
    const model = await screen.findByTestId("model-default");
    expect(model).toHaveTextContent("Gemini 3.8 Flash");
    expect(model).toHaveTextContent("Google Gemini");
    expect(model).toHaveTextContent("Prêt");
    expect(model).toHaveTextContent("0,75 $US / 3,75 $US par million de tokens");
    expect(model).toHaveTextContent("Puis 1,50 $US / 7,50 $US à partir du 01/01/2027");
    expect(model).toHaveTextContent("Si le modèle ne répond pas : Mistral Large");
    const order = screen.getByTestId("model-answering");
    expect(within(order).getAllByRole("listitem")[0]).toHaveTextContent("Gemini 3.8 Flash");
    expect(within(order).getAllByRole("listitem")[1]).toHaveTextContent("en repli");

    const used = await screen.findByTestId("model-usage");
    expect(screen.getByTestId("model-usage-calls")).toHaveTextContent("12");
    expect(screen.getByTestId("model-usage-tokens")).toHaveTextContent("12");
    expect(used).toHaveTextContent("2 appels à un modèle sans prix publié non comptés");
    expect(used).toHaveTextContent("Comprendre une demande");
    expect(screen.getByTestId("model-call")).toHaveTextContent("Rédiger une réponse");
    expect(screen.getByTestId("model-call")).toHaveTextContent("gemini-3.8-flash-001");
    // What the runtime had models do, by how it ended (LEKA-429).
    expect(screen.getByTestId("model-runs")).toHaveTextContent(
      "Exécutions : 9 réussies · 1 hors délai",
    );
    // What one intention costs, measured — and what a budget buys.
    expect(screen.getByTestId("model-per-intention")).toHaveTextContent(
      "Une intention coûte en moyenne 1,1 ¢, mesuré sur 4 intentions : environ 892 intentions pour 10 $.",
    );
    expect(screen.getByTestId("model-cached")).toHaveTextContent("50 % des tokens envoyés relus");
    // Where the money goes, by use.
    expect(used).toHaveTextContent("Proposer une description (À valider)");
    expect(used).toHaveTextContent("Proposer une description (À valider)2 · 0,01 $US");
  });

  it("says when no model can answer", async () => {
    api.get.mockResolvedValue(gateway({ default_ready: false, answering: [], ready: false, fallbacks: [] }));
    show();
    expect(await screen.findByTestId("model-nobody")).toHaveTextContent(
      "les intentions sont lues et analysées par les règles de LEKA",
    );
    expect(screen.getByTestId("model-default")).toHaveTextContent("Clé non configurée");
  });

  it("says no call in a sentence, not in four 0", async () => {
    api.usage.mockResolvedValue(usage({ total: { ...TALLY } }));
    show();
    expect(await screen.findByText("Aucun appel sur la période.")).toBeInTheDocument();
    expect(screen.queryByTestId("model-usage-calls")).not.toBeInTheDocument();
  });

  it("lets an admin plug in the company's Azure OpenAI, test it, remove it", async () => {
    const user = userEvent.setup();
    const own = {
      provider: "azure_openai",
      model: "gpt-prod",
      base_url: "https://acme.openai.azure.com",
      api_version: "2024-10-21",
      key_hint: "9876",
      enabled: true,
      exclusive: true,
      status: "untested" as const,
      status_detail: null,
      tested_at: null,
      changed_at: new Date().toISOString(),
    };
    api.save.mockResolvedValue(gateway({ own }));
    show();
    await user.click(await screen.findByTestId("model-bring"));
    await user.selectOptions(screen.getByTestId("model-provider"), "azure_openai");
    await user.type(screen.getByTestId("model-name"), "gpt-prod");
    await user.type(screen.getByTestId("model-url"), "https://acme.openai.azure.com");
    await user.type(screen.getByTestId("model-version"), "2024-10-21");
    await user.type(screen.getByTestId("model-key"), "azure-secret-key-9876");
    await user.click(screen.getByTestId("model-exclusive"));
    // Saved, it is read again: with the model.
    api.get.mockResolvedValue(gateway({ own }));
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
    await user.click(within(dialog).getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalled());
  });

  it("lets a member read and change nothing", async () => {
    permissions.value = ["workspace:read"];
    show();
    await screen.findByTestId("model-default");
    expect(screen.queryByTestId("model-bring")).not.toBeInTheDocument();
    expect(screen.getByText("Seuls les admins branchent un modèle.")).toBeInTheDocument();
  });
});

describe("the model used by default here (2026-10-21)", () => {
  const choosing = { choosable: [FLASH, LARGE] };

  it("is chosen in one click among LEKA's models, and back to LEKA's", async () => {
    // The server keeps what was chosen: read again, it says so.
    const unchosen = gateway(choosing);
    const chosen = gateway({ ...choosing, chosen: LARGE });
    api.get.mockResolvedValue(unchosen);
    api.usage.mockResolvedValue(usage());
    api.choose.mockImplementation(async () => {
      api.get.mockResolvedValue(chosen);
      return chosen;
    });
    api.unchoose.mockImplementation(async () => {
      api.get.mockResolvedValue(unchosen);
      return unchosen;
    });
    const user = userEvent.setup();
    show();
    const box = await screen.findByTestId("model-choose");
    const [flash, large] = within(box).getAllByRole("radio");
    expect(flash).toBeChecked();
    expect(within(box).getByText("Le modèle par défaut de LEKA")).toBeInTheDocument();
    await user.click(large!);
    await waitFor(() => expect(api.choose).toHaveBeenCalledWith("mistral", "mistral-large-latest"));
    await waitFor(() => expect(within(screen.getByTestId("model-choose")).getAllByRole("radio")[1]).toBeChecked());
    await user.click(within(screen.getByTestId("model-choose")).getAllByRole("radio")[0]!);
    await waitFor(() => expect(api.unchoose).toHaveBeenCalled());
  });

  it("is read, never changed, by a member", async () => {
    permissions.value = ["workspace:read"];
    api.get.mockResolvedValue(gateway({ ...choosing, chosen: LARGE }));
    api.usage.mockResolvedValue(usage());
    show();
    const box = await screen.findByTestId("model-choose");
    expect(box).toBeDisabled();
    expect(within(box).getAllByRole("radio")[1]).toBeChecked();
    expect(box).toHaveTextContent("Seuls les admins de l'espace");
    permissions.value = ["workspace:read", "workspace:update"];
  });
});

