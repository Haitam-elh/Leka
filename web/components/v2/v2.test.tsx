/**
 * The new interface (2026-10-14, the product call's Lot 6).
 *
 * What these protect:
 * - The environment's health in one word, from the twin: stable, attention,
 *   incident — or no source at all; never a figure drawn here.
 * - The person's agents under the bar, each a « /mot » a click puts first
 *   in the request; none owned, said so, and « Voir tous » still there.
 * - Asked from the bar, it is asked — no « Lancer l'analyse » — and its
 *   exchange opens under the bar; a request about anything but technology
 *   is said in words. In an exchange LEKA can take again, what is typed is
 *   a detail added to it, kept as the thread's next line.
 * - The thread says where LEKA is: reading, failed with « Relancer »,
 *   closed.
 * - The avatar's menu: Configuration, Facturation, Historique, Déconnexion
 *   — only what the person may open.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import type { Environment } from "@/lib/environment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

const push = vi.fn();
const search = vi.hoisted(() => ({ value: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.value),
  usePathname: () => "/v2",
}));

const permissions = vi.hoisted(() => ({ value: [] as string[] }));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: "u1", email: "nora@acme.example", first_name: "Nora", last_name: "Diallo" }),
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
  usePermissions: () => permissions.value,
}));

const offers = vi.hoisted(() => ({ value: [] as { key: string; title: string; summary: string; owned: boolean }[] }));
vi.mock("@/lib/billing-queries", async (original) => ({
  ...(await original<typeof import("@/lib/billing-queries")>()),
  useAddOns: () => ({ data: { agents: offers.value, bundles: [] } }),
}));

const environment = vi.hoisted(() => ({ value: undefined as unknown }));
vi.mock("@/lib/environment-queries", () => ({
  useEnvironment: () => ({ data: environment.value }),
}));

vi.mock("@/lib/agent-runs-queries", () => ({
  useIntentionRuns: () => ({ data: [] }),
}));

const opened = vi.hoisted(() => ({ value: undefined as unknown }));
vi.mock("@/lib/intentions/queries", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/queries")>()),
  useIntention: (id: string) => ({ data: id ? opened.value : undefined, isError: false }),
}));

const api = vi.hoisted(() => ({ create: vi.fn(), ask: vi.fn(), analyse: vi.fn() }));
vi.mock("@/lib/intentions/api", async (original) => {
  const real = await original<typeof import("@/lib/intentions/api")>();
  return { ...real, intentions: { ...real.intentions, ...api } };
});

const { healthOf } = await import("@/components/v2/health");
const { Home, slashes } = await import("@/components/v2/home");
const { splitSaid } = await import("@/components/v2/said");
const { Thread } = await import("@/components/v2/thread");
const { AvatarMenu } = await import("@/components/v2/avatar-menu");

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function env(over: Partial<Environment> = {}): Environment {
  return {
    updated_at: null,
    nodes: [],
    edges: [],
    environments: [],
    services: 0,
    services_operational: 0,
    services_deduced: 0,
    services_external: 0,
    services_unknown: 0,
    incidents_open: 0,
    services_impacted: 0,
    attention: [],
    events: [],
    states: {},
    freshness: { last_read_at: null, every_minutes: 60, late: false, webhooks: false },
    sources: [
      {
        id: "s1",
        kind: "github",
        name: "acme/backend",
        category: "code",
        state: "read",
        last_synced_at: null,
        error: null,
        webhooks: false,
      },
    ],
    ...over,
  } as Environment;
}

function intention(state: string, over: Partial<IntentionDetail> = {}): IntentionDetail {
  return {
    id: "int-1",
    text: "Construis l'architecture du parcours paiement",
    title: "Architecture du parcours paiement",
    status: "analysing",
    created_by: "u1",
    journey: {
      state,
      since: "2026-10-14T10:00:00Z",
      reason: null,
      next: "",
      by: "leka",
      controls: [],
      step: { at: "analysis", reached: 1, done: [], last: 1 },
      late: false,
      technical: null,
      path: null,
    },
    ...over,
  } as unknown as IntentionDetail;
}

beforeEach(() => {
  push.mockReset();
  for (const call of Object.values(api)) call.mockReset();
  search.value = "";
  permissions.value = [];
  offers.value = [];
  environment.value = env();
  opened.value = undefined;
});

describe("the environment's health", () => {
  it("is one word, from the twin and the sources", () => {
    expect(healthOf(undefined)).toBe("loading");
    expect(healthOf(env({ sources: [] }))).toBe("none");
    expect(healthOf(env())).toBe("stable");
    expect(healthOf(env({ states: { degraded: 1 } }))).toBe("attention");
    expect(
      healthOf(env({ freshness: { last_read_at: null, every_minutes: 60, late: true, webhooks: false } })),
    ).toBe("attention");
    const failing = env().sources?.map((s) => ({ ...s, state: "error" as const }));
    expect(healthOf(env({ sources: failing }))).toBe("attention");
    expect(healthOf(env({ states: { unavailable: 1, degraded: 2 } }))).toBe("incident");
    expect(healthOf(env({ incidents_open: 1 }))).toBe("incident");
  });
});

describe("the home's bar", () => {
  it("says the person's agents, each a « /mot » put first in the request", async () => {
    offers.value = [
      { key: "architect", title: "Architecte applicatif", summary: "", owned: true },
      { key: "architecture-analysis", title: "Architecture analysis", summary: "", owned: true },
      { key: "code-review", title: "Revue de code", summary: "", owned: false },
    ];
    const user = userEvent.setup();
    show(<Home />);

    const chips = screen.getAllByTestId("v2-agent-chip");
    expect(chips.map((chip) => chip.textContent)).toEqual(["/architecte", "/architecture"]);
    await user.type(screen.getByTestId("v2-ask"), "construis le parcours paiement");
    await user.click(chips[0]);
    expect(screen.getByTestId("v2-ask")).toHaveValue("/architecte construis le parcours paiement");
    await user.click(chips[1]);
    expect(screen.getByTestId("v2-ask")).toHaveValue("/architecture construis le parcours paiement");
    expect(screen.getByTestId("v2-see-all")).toHaveAttribute("href", "/v2/agents");
  });

  it("says when no agent is active, « Voir tous » still there", () => {
    show(<Home />);
    expect(screen.getByTestId("v2-agents")).toHaveTextContent("Aucun agent actif pour l'instant.");
    expect(screen.getByTestId("v2-see-all")).toBeVisible();
  });

  it("draws LEKA tied to each source it reads", () => {
    show(<Home />);
    const tied = within(screen.getByTestId("v2-constellation"));
    expect(tied.getAllByTestId("v2-constellation-source")).toHaveLength(1);
    expect(screen.getByTestId("v2-constellation")).toHaveTextContent("1 source connectée");
  });

  it("asks what is typed — Enter is enough — and opens its exchange", async () => {
    api.create.mockResolvedValue({ intention: { id: "int-9" }, context: {} });
    const user = userEvent.setup();
    show(<Home />);

    await user.type(screen.getByTestId("v2-ask"), "Teste mon application{Enter}");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/v2?i=int-9"));
    const [asked, key] = api.create.mock.calls[0];
    expect(asked).toMatchObject({ text: "Teste mon application", sources: [], services: [] });
    expect(typeof key).toBe("string");
  });

  it("says, in words, a request LEKA does not take", async () => {
    api.create.mockRejectedValue(
      new ApiError(422, "/api/v1/intentions", "Off topic.", "off_topic"),
    );
    const user = userEvent.setup();
    show(<Home />);

    await user.type(screen.getByTestId("v2-ask"), "Une recette de tarte{Enter}");
    expect(await screen.findByTestId("v2-ask-error")).toHaveTextContent(
      "LEKA répond aux questions liées à votre stack technique",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("adds a detail to an exchange LEKA can take again, as its next line", async () => {
    search.value = "i=int-1";
    opened.value = intention("needs_clarification", {
      journey: { ...intention("x").journey, state: "needs_clarification", controls: ["ask_again", "answer"] },
    });
    api.ask.mockResolvedValue({ intention: { ...(opened.value as object), id: "int-1" }, context: {} });
    const user = userEvent.setup();
    show(<Home />);

    expect(screen.getByTestId("v2-ask")).toHaveAttribute(
      "placeholder",
      "Précisez, relancez ou répondez à LEKA…",
    );
    await user.type(screen.getByTestId("v2-ask"), "Le parcours de paiement par carte{Enter}");
    await waitFor(() => expect(api.ask).toHaveBeenCalled());
    const [id, asked] = api.ask.mock.calls[0];
    expect(id).toBe("int-1");
    expect(asked.text).toBe(
      "Construis l'architecture du parcours paiement\n\nLe parcours de paiement par carte",
    );
    expect(api.create).not.toHaveBeenCalled();
    expect(splitSaid(asked.text)).toHaveLength(2);
  });
});

describe("the thread", () => {
  it("says LEKA is reading while it reads", () => {
    opened.value = intention("analysing");
    show(<Thread id="int-1" />);
    expect(screen.getByTestId("v2-said")).toHaveTextContent("Construis l'architecture du parcours paiement");
    expect(screen.getByTestId("v2-reading")).toHaveTextContent("LEKA lit vos sources");
    expect(screen.getByTestId("v2-detail")).toHaveAttribute("href", "/intentions/int-1");
  });

  it("says a failed analysis, with « Relancer » to whoever may", async () => {
    opened.value = intention("analysis_failed", {
      journey: { ...intention("x").journey, state: "analysis_failed", controls: ["analyse_again"], reason: "Aucune source n'a répondu." },
    });
    api.analyse.mockResolvedValue({ queued: true });
    const user = userEvent.setup();
    show(<Thread id="int-1" />);

    expect(screen.getByTestId("v2-failed")).toHaveTextContent("Aucune source n'a répondu.");
    await user.click(screen.getByTestId("v2-retry"));
    await waitFor(() => expect(api.analyse).toHaveBeenCalledWith("int-1"));
  });

  it("says a closed request is closed", () => {
    opened.value = intention("cancelled");
    show(<Thread id="int-1" />);
    expect(screen.getByTestId("v2-ended")).toHaveTextContent("Cette demande est close.");
  });

  it("reads each detail given as its own line", () => {
    expect(splitSaid("Teste l'application\n\nLe parcours paiement\n\n")).toEqual([
      "Teste l'application",
      "Le parcours paiement",
    ]);
    expect(slashes(["Revue de code", "Revue de sécurité", "Débogage"])).toEqual([
      "/revue-de-code",
      "/revue-de-securite",
      "/debogage",
    ]);
  });
});

describe("the avatar's menu", () => {
  it("holds Configuration, Facturation, Historique and Déconnexion for an owner", async () => {
    permissions.value = ["source:read", "workspace:update", "member:invite"];
    const user = userEvent.setup();
    show(<AvatarMenu />);

    await user.click(screen.getByTestId("v2-avatar"));
    for (const id of ["sources", "security", "team", "billing", "history", "classic", "sign-out"]) {
      expect(await screen.findByTestId(`v2-menu-${id}`)).toBeInTheDocument();
    }
    await user.click(screen.getByTestId("v2-menu-history"));
    expect(push).toHaveBeenCalledWith("/v2/history");
  });

  it("shows a member only what a member may open", async () => {
    permissions.value = ["source:read"];
    const user = userEvent.setup();
    show(<AvatarMenu />);

    await user.click(screen.getByTestId("v2-avatar"));
    expect(await screen.findByTestId("v2-menu-sources")).toBeInTheDocument();
    for (const id of ["security", "team", "billing"]) {
      expect(screen.queryByTestId(`v2-menu-${id}`)).not.toBeInTheDocument();
    }
  });
});
