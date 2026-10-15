/**
 * Capacités (LEKA-393, mockup 13).
 *
 * What these protect: each capability in words — LEKA's own in French, an
 * agent as its file says it — with whether it can be used here and why not,
 * in words: the source to connect, named, on the card; what holds them all
 * back — no model — said once above the list (LEKA-438); chosen by need, by
 * category and by words, sorted; the week's usage only when something ran;
 * kept at hand; the configuration, for admins only —
 * turning one off only saying why; a capability's sheet says what it takes,
 * delivers and needs, its versions and history.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { Capability, CapabilityDetail, CatalogueSummary } from "@/lib/capabilities";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const route = vi.hoisted(() => ({ pathname: "/capabilities", search: "", key: "" }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:create"] }));
const api = vi.hoisted(() => ({
  list: vi.fn(),
  summary: vi.fn(),
  one: vi.fn(),
  settings: vi.fn(),
  favourite: vi.fn(),
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const replace = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => new URLSearchParams(route.search),
  usePathname: () => route.pathname,
  useParams: () => ({ capabilityId: route.key }),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: "me" }),
}));
vi.mock("@/lib/capabilities", async (original) => ({
  ...(await original<typeof import("@/lib/capabilities")>()),
  capabilities: api,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
// What is sold besides the plan (2026-10-14).
const sold = vi.hoisted(() => ({ addOns: vi.fn(), entitlements: vi.fn(), buy: vi.fn() }));
vi.mock("@/lib/billing", async (original) => ({
  ...(await original<typeof import("@/lib/billing")>()),
  billing: sold,
}));

function addOns(owned: boolean, plan = "starter") {
  return {
    available: true,
    provisional: true,
    currency: "EUR",
    minimum_plan: "starter",
    plan,
    runs_agents: plan !== "free",
    every: false,
    agents: [
      {
        key: "application-architecture",
        title: "Architecte applicatif",
        summary: "Le deck d'architecture d'un parcours.",
        category: "architecture",
        tier: "expert",
        monthly_price: 2500,
        owned,
        why: owned ? null : plan === "free" ? "plan_required" : "not_owned",
        bundles: ["architecture"],
      },
    ],
    bundles: [
      {
        key: "architecture",
        name: { fr: "Architecture", en: "Architecture" },
        value: { fr: "Documenter votre architecture.", en: "Document your architecture." },
        agents: ["application-architecture"],
        monthly_price: 4900,
        alone_price: 6400,
        discount_percent: 23,
        owned,
      },
    ],
  };
}

const { CatalogueScreen } = await import("@/components/capabilities/catalogue");
const { CapabilityScreen } = await import("@/components/capabilities/capability-detail");

function capability(overrides: Partial<Capability> = {}): Capability {
  return {
    key: "ownership",
    title: "Ownership",
    summary: "Who owns it, maintains it, leads its teams, knows it.",
    category: "knowledge",
    kind: "rules",
    version: "1.0.0",
    lifecycle: "active",
    origin: "internal",
    mode: "read_only",
    risk: "low",
    permission: "intention:create",
    inputs: [],
    output: "analysis",
    formats: ["json"],
    sources: [],
    model: false,
    model_needs: null,
    answering: null,
    goals: ["find_owner"],
    kinds: ["ownership"],
    entity_types: [],
    examples: [],
    always: false,
    available: true,
    reasons: [],
    notes: [],
    enabled: true,
    enabled_reason: null,
    enabled_changed_at: null,
    favourite: false,
    registered_at: "2026-10-09T10:00:00Z",
    lifecycle_changed_at: "2026-10-09T10:00:00Z",
    versions: 1,
    refused: null,
    usage: { runs: 12, previous: 10, failures: 0, average_ms: 40 },
    ...overrides,
  };
}

const ARCHITECT = capability({
  key: "application-architecture",
  title: "Architecte applicatif",
  summary: "Use when someone asks for the application architecture of a business journey.",
  category: "architecture",
  kind: "agent",
  version: "18.0.0",
  output: "document",
  formats: ["pptx", "pdf"],
  model: true,
  inputs: [
    { name: "parcours", type: "text", required: true, description: "Le parcours.", choices: [], entity_types: [] },
    { name: "perimetre", type: "text", required: true, description: "Le périmètre.", choices: [], entity_types: [] },
  ],
  sources: [{ any_of: ["confluence", "microsoft_365"], connected: false }],
  goals: ["map_dependencies"],
  available: false,
  reasons: [
    { code: "missing_source", detail: { any_of: ["confluence", "microsoft_365"] } },
    { code: "no_model", detail: {} },
  ],
  usage: { runs: 0, previous: 0, failures: 0, average_ms: null },
});

const SUMMARY: CatalogueSummary = {
  total: 10,
  available: 9,
  added_this_month: 10,
  categories: [
    { category: "knowledge", count: 2, available: 2 },
    { category: "architecture", count: 3, available: 2 },
  ],
  runs: 24,
  runs_previous: 20,
  analysis_ms: 90_000,
  analysis_previous_ms: 120_000,
  days: [
    { day: "2026-10-03", runs: {} },
    { day: "2026-10-09", runs: { knowledge: 24 } },
  ],
  top: [{ key: "ownership", title: "Ownership", category: "knowledge", runs: 12, previous: 10 }],
  latest: [
    {
      key: "application-architecture",
      title: "Architecte applicatif",
      summary: ARCHITECT.summary,
      category: "architecture",
      registered_at: "2026-10-09T10:00:00Z",
    },
  ],
};

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sold.addOns.mockResolvedValue(addOns(false));
  sold.entitlements.mockResolvedValue([]);
  route.pathname = "/capabilities";
  route.search = "";
  permissions.value = ["workspace:read", "intention:create"];
  api.list.mockResolvedValue([capability(), ARCHITECT]);
  api.summary.mockResolvedValue(SUMMARY);
  api.settings.mockResolvedValue(capability({ enabled: false }));
  api.favourite.mockResolvedValue(undefined);
});

describe("the catalogue", () => {
  it("says each capability, with why one cannot run — the model once, above", async () => {
    show(<CatalogueScreen />);
    await screen.findAllByTestId("capability-card");
    const card = (key: string) =>
      screen.getAllByTestId("capability-card").find((c) => c.dataset.key === key) as HTMLElement;
    const [owner, architect] = [card("ownership"), card("application-architecture")];
    // LEKA's own, in French.
    expect(owner).toHaveTextContent("Responsabilités");
    expect(owner).toHaveTextContent("Qui en est responsable");
    expect(owner).toHaveTextContent("Lancée 12 fois dans votre espace");
    expect(owner).toHaveTextContent("Disponible");
    expect(architect).toHaveTextContent("Architecte applicatif");
    // What it does in the reader's words, not the description its model reads.
    expect(architect).toHaveTextContent("Le deck d'architecture d'un parcours");
    expect(architect).not.toHaveTextContent("Use when");
    expect(architect).toHaveAttribute("data-available", "false");
    expect(within(architect).getByTestId("capability-reasons")).toHaveTextContent(
      "Source à connecter : Confluence ou Microsoft 365",
    );
    expect(within(architect).getByTestId("capability-reasons")).not.toHaveTextContent("modèle");
    expect(screen.getByTestId("catalogue-wide")).toHaveTextContent(
      "Aucun modèle de langage n'est configuré : 1 capacité ne peut pas s'exécuter ici.",
    );
    // Not run yet: nothing said about it.
    expect(architect).not.toHaveTextContent("Pas encore exécutée");
    expect(screen.queryByTestId("catalogue-stats")).not.toBeInTheDocument();
    expect(screen.getByTestId("catalogue-top")).toHaveTextContent("Responsabilités");
    expect(screen.getByTestId("catalogue-latest")).toHaveTextContent("Architecte applicatif");
    expect(screen.getByTestId("catalogue-latest")).not.toHaveTextContent("Use when");
    expect(screen.getByTestId("catalogue-ask")).toHaveAttribute("href", "/intentions/new");
  });

  it("shows one box per domain, its agents apart from LEKA's own capabilities", async () => {
    // 2026-10-14: « une case avec les agents et capacités sur le code, pareil
    // pour les autres » — never mixed.
    const user = userEvent.setup();
    show(<CatalogueScreen />);
    await screen.findAllByTestId("capability-card");
    const domains = screen.getAllByTestId("catalogue-domain");
    expect(domains.map((d) => d.dataset.domain)).toEqual(["architecture", "knowledge"]);
    const [architecture, knowledge] = domains;
    expect(within(architecture).getByRole("heading", { level: 2 })).toHaveTextContent("Architecture");
    expect(within(architecture).getByTestId("catalogue-domain-count")).toHaveTextContent("1 agent");
    expect(
      within(within(architecture).getByTestId("catalogue-domain-agents")).getByTestId("capability-card"),
    ).toHaveAttribute("data-key", "application-architecture");
    expect(within(architecture).queryByTestId("catalogue-domain-own")).not.toBeInTheDocument();
    expect(within(knowledge).getByRole("heading", { level: 2 })).toHaveTextContent("Connaissance");
    expect(
      within(within(knowledge).getByTestId("catalogue-domain-own")).getByTestId("capability-card"),
    ).toHaveAttribute("data-key", "ownership");
    expect(within(knowledge).getByTestId("catalogue-domain-count")).toHaveTextContent("1 capacité");

    // The agents only, then LEKA's own only.
    await user.click(screen.getByTestId("catalogue-show-agents"));
    expect(screen.getAllByTestId("capability-card").map((c) => c.dataset.kind)).toEqual(["agent"]);
    await user.click(screen.getByTestId("catalogue-show-capabilities"));
    expect(screen.getAllByTestId("capability-card").map((c) => c.dataset.key)).toEqual(["ownership"]);
  });

  it("chooses by need and by words, and keeps one at hand", async () => {
    const user = userEvent.setup();
    show(<CatalogueScreen />);
    await screen.findAllByTestId("capability-card");
    await user.click(screen.getByTestId("catalogue-need-map_dependencies"));
    expect(screen.getByTestId("catalogue-need-map_dependencies")).toHaveTextContent("Comprendre les dépendances1");
    expect(screen.getAllByTestId("capability-card")).toHaveLength(1);
    expect(screen.getByTestId("capability-card")).toHaveAttribute("data-key", "application-architecture");
    await user.click(screen.getByTestId("catalogue-need-map_dependencies"));
    expect(screen.getAllByTestId("capability-card")).toHaveLength(2);
    await user.type(screen.getByTestId("catalogue-search"), "archi");
    await waitFor(() =>
      expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: "archi" })),
    );
    const owner = screen
      .getAllByTestId("capability-card")
      .find((c) => c.dataset.key === "ownership") as HTMLElement;
    await user.click(within(owner).getByTestId("capability-favourite"));
    await waitFor(() => expect(api.favourite).toHaveBeenCalledWith("ownership", true));
  });

  it("leaves the usage out when nothing ran, and says the model only when it holds one back", async () => {
    api.summary.mockResolvedValue({ ...SUMMARY, runs: 0, runs_previous: 0 });
    api.list.mockResolvedValue([capability()]);
    show(<CatalogueScreen />);
    await screen.findAllByTestId("capability-card");
    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    expect(screen.queryByTestId("catalogue-usage")).not.toBeInTheDocument();
    expect(screen.queryByTestId("catalogue-wide")).not.toBeInTheDocument();
  });

  it("shows « Mes capacités »: what the workspace owns, LEKA's own with it", async () => {
    // 2026-10-14: « l'onglet Mes capacités ne sert strictement à rien ».
    route.search = "tab=mine";
    sold.entitlements.mockResolvedValue([]);
    show(<CatalogueScreen />);
    await screen.findAllByTestId("capability-card");
    const keys = screen.getAllByTestId("capability-card").map((c) => c.dataset.key);
    expect(keys).toContain("ownership");
    expect(keys).not.toContain("application-architecture");
    expect(await screen.findByText(/Aucun agent pour l'instant/)).toBeVisible();
    expect(screen.getByTestId("catalogue-view-mine")).toHaveAttribute("aria-selected", "true");
  });

  it("prices each agent, offers its bundles, and buys for who may", async () => {
    permissions.value = ["workspace:read", "workspace:update"];
    sold.buy.mockResolvedValue({ url: "https://checkout.stripe.test/cs_1" });
    const user = userEvent.setup();
    show(<CatalogueScreen />);
    const price = await screen.findByTestId("agent-price");
    expect(price).toHaveTextContent("25 € / mois");
    expect(price).toHaveTextContent("Expert");
    const bundle = await screen.findByTestId("bundle");
    expect(bundle).toHaveTextContent("Architecture");
    expect(bundle).toHaveTextContent("49 €");
    expect(bundle).toHaveTextContent("−23 %");
    await user.click(within(price).getByTestId("agent-buy"));
    await waitFor(() =>
      expect(sold.buy).toHaveBeenCalledWith({ kind: "agent", key: "application-architecture" }),
    );
  });

  it("on Free, says the plan agents need instead of selling one", async () => {
    sold.addOns.mockResolvedValue(addOns(false, "free"));
    show(<CatalogueScreen />);
    const price = await screen.findByTestId("agent-price");
    expect(price).toHaveTextContent("À partir du plan Starter");
    expect(within(price).queryByTestId("agent-buy")).not.toBeInTheDocument();
  });

  it("lets an admin turn one off, only saying why — and anyone else read it", async () => {
    const user = userEvent.setup();
    route.search = "tab=configuration";
    permissions.value = ["workspace:read", "workspace:update"];
    show(<CatalogueScreen />);
    const [row] = await screen.findAllByTestId("configuration-row");
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ everything: true }));
    await user.click(within(row).getByTestId("configuration-toggle"));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Désactiver" }));
    expect(api.settings).not.toHaveBeenCalled();
    expect(notices.error).toHaveBeenCalledWith({ title: "Dites pourquoi." });
    await user.click(within(row).getByTestId("configuration-toggle"));
    dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Pas pour nous.");
    await user.click(within(dialog).getByRole("button", { name: "Désactiver" }));
    await waitFor(() =>
      expect(api.settings).toHaveBeenCalledWith("ownership", {
        enabled: false,
        reason: "Pas pour nous.",
      }),
    );
  });

  it("shows the configuration read-only to a member", async () => {
    route.search = "tab=configuration";
    show(<CatalogueScreen />);
    expect(await screen.findByTestId("catalogue-configuration")).toHaveTextContent(
      "Seuls les admins activent ou désactivent une capacité.",
    );
    await screen.findAllByTestId("configuration-row");
    expect(screen.queryByTestId("configuration-toggle")).not.toBeInTheDocument();
  });
});

describe("a capability's sheet", () => {
  it("says what it takes, delivers and needs, and its history", async () => {
    route.pathname = "/capabilities/application-architecture";
    route.key = "application-architecture";
    const detail: CapabilityDetail = {
      ...ARCHITECT,
      history: [
        {
          version: "18.0.0",
          lifecycle: "active",
          fingerprint: "f",
          registered_at: "2026-10-09T10:00:00Z",
          lifecycle_changed_at: "2026-10-09T10:00:00Z",
          superseded_at: null,
        },
      ],
      events: [
        {
          id: "e1",
          version: "18.0.0",
          kind: "registered",
          from_lifecycle: null,
          to_lifecycle: "active",
          at: "2026-10-09T10:00:00Z",
          detail: {},
        },
      ],
      days: [],
    };
    api.one.mockResolvedValue(detail);
    show(<CapabilityScreen />);
    const sheet = await screen.findByTestId("capability");
    expect(within(sheet).getByTestId("capability-inputs")).toHaveTextContent("parcours · obligatoire");
    expect(within(sheet).getByTestId("capability-formats")).toHaveTextContent("PowerPoint (.pptx)");
    expect(within(sheet).getByTestId("capability-formats")).toHaveTextContent("PDF");
    expect(within(sheet).getByTestId("capability-needs")).toHaveTextContent(
      "Une source : Confluence ou Microsoft 365 · à connecter",
    );
    expect(within(sheet).getByTestId("capability-needs")).toHaveTextContent(
      "Un modèle de langage · aucun ne peut l'exécuter ici",
    );
    expect(within(sheet).getByTestId("capability-availability")).toHaveTextContent(
      "Aucun modèle de langage ne peut l'exécuter ici",
    );
    expect(within(sheet).getByTestId("capability-versions")).toHaveTextContent("v18.0.0");
    expect(within(sheet).getByTestId("capability-events")).toHaveTextContent("Enregistrée");
  });
});
