/**
 * The audit trail (LEKA-407).
 *
 * What these protect: each event said in words — its outcome, what was
 * done, to what, by whom (LEKA for whom it acted; a deleted account said
 * so), when; the filters sent as the API reads them; more read on from the
 * last page; one event opened with what else its request did; the export
 * following the same filters; the retention changed by the owner only.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditEvent } from "@/lib/audit";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  search: vi.fn(),
  event: vi.fn(),
  settings: vi.fn(),
  keep: vi.fn(),
  exportAddress: vi.fn(() => "https://api.test/api/v1/governance/audit/export"),
}));
const people = vi.hoisted(() => ({ members: vi.fn() }));

vi.mock("@/lib/audit", async (original) => ({
  ...(await original<typeof import("@/lib/audit")>()),
  audit: api,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { AuditLogCard, AuditRetentionCard, actionSaid } = await import(
  "@/components/governance/audit-log"
);
const { DICTIONARIES } = await import("@/lib/i18n/dictionaries");
const { auditParams } = await import("@/lib/audit");

function event(over: Partial<AuditEvent>): AuditEvent {
  return {
    id: "e1",
    at: "2026-10-10T09:00:00Z",
    category: "data",
    action: "source.created",
    outcome: "success",
    actor_type: "user",
    actor_id: "u-ana",
    actor_role: "admin",
    target_type: "source",
    target_id: "s1",
    target_label: "Slack",
    request_id: "REQ1",
    ip: "10.0.0.0/24",
    user_agent: "Firefox",
    detail: { kind: "slack" },
    ...over,
  };
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  people.members.mockResolvedValue([
    { user_id: "u-ana", email: "ana@acme.fr", first_name: "Ana", last_name: null, role: "admin" },
  ]);
  api.settings.mockResolvedValue({
    retention_days: 365,
    default_days: 365,
    min_days: 90,
    max_days: 2555,
    oldest: "2026-01-01T00:00:00Z",
    updated_at: null,
    updated_by: null,
  });
});

describe("auditParams", () => {
  it("sends what is set, a period as a date", () => {
    const now = new Date("2026-10-10T12:00:00Z");
    const params = auditParams({ category: "data", outcome: "", q: " slack ", period: "week" }, now);
    expect(Object.fromEntries(params)).toEqual({
      category: "data",
      q: "slack",
      since: "2026-10-03T12:00:00.000Z",
    });
    expect(auditParams({ period: "all" }).toString()).toBe("");
  });
});

describe("actionSaid", () => {
  it("says every action in words — its own, a permission, a change, a control's", () => {
    const fr = DICTIONARIES.fr;
    expect(actionSaid(fr, "source.created")).toBe("Source créée");
    expect(actionSaid(fr, "workspace:read")).toBe(fr.governance.permissions["workspace:read"]);
    expect(actionSaid(fr, "policy.created")).toBe("Politique créé(e)");
    expect(actionSaid(fr, "ai_control.blocked")).toBe("Contrôles de l'IA · Réponse bloquée");
    expect(actionSaid(fr, "something.new")).toBe("something.new");
  });
});

describe("AuditLogCard", () => {
  it("says each event in words, by whom — LEKA for whom it acted", async () => {
    api.search.mockResolvedValue({
      events: [
        event({}),
        event({
          id: "e2",
          category: "ai",
          action: "agent_run.succeeded",
          actor_type: "system",
          actor_id: null,
          actor_role: null,
          target_label: "application-architecture",
          detail: { for: "u-ana" },
        }),
        event({ id: "e3", outcome: "denied", category: "access", action: "workspace:read", actor_id: null }),
      ],
      next: null,
    });
    show(<AuditLogCard />);
    const list = await screen.findByTestId("audit-events");
    const [created, ran, refused] = within(list).getAllByRole("listitem");
    expect(within(created).getByText("Source créée")).toBeInTheDocument();
    expect(within(created).getByText("· Slack")).toBeInTheDocument();
    await waitFor(() => expect(within(created).getByText(/Ana · Admin/)).toBeInTheDocument());
    expect(within(ran).getByText(/LEKA · pour Ana/)).toBeInTheDocument();
    expect(within(refused).getByText("Refusé")).toBeInTheDocument();
    expect(within(refused).getByText(/Compte supprimé/)).toBeInTheDocument();
  });

  it("filters as the API reads them, and reads on from the last page", async () => {
    api.search
      .mockResolvedValueOnce({ events: [event({})], next: "CUR" })
      .mockResolvedValue({ events: [event({ id: "e9", action: "source.deleted" })], next: null });
    show(<AuditLogCard />);
    await screen.findByTestId("audit-events");
    expect(api.search.mock.calls[0]).toEqual([
      { category: "", outcome: "", actor: "", period: "month", q: "" },
      null,
    ]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Afficher plus" }));
    await waitFor(() => expect(screen.getByText("Source supprimée")).toBeInTheDocument());
    expect(api.search.mock.calls.at(-1)?.[1]).toBe("CUR");

    await user.selectOptions(screen.getByLabelText("Catégorie"), "data");
    await user.selectOptions(screen.getByLabelText("Résultat"), "denied");
    await user.type(screen.getByLabelText("Rechercher"), "Slack");
    await user.click(screen.getByRole("button", { name: "Rechercher" }));
    await waitFor(() =>
      expect(api.search.mock.calls.at(-1)?.[0]).toEqual({
        category: "data",
        outcome: "denied",
        actor: "",
        period: "month",
        q: "Slack",
      }),
    );
    expect(api.exportAddress).toHaveBeenLastCalledWith(
      expect.objectContaining({ category: "data", outcome: "denied", q: "Slack" }),
    );
    expect(screen.getByRole("link", { name: /Exporter en CSV/ })).toHaveAttribute(
      "href",
      "https://api.test/api/v1/governance/audit/export",
    );
  });

  it("opens one with where it came from and what else its request did", async () => {
    api.search.mockResolvedValue({ events: [event({})], next: null });
    api.event.mockResolvedValue({
      ...event({}),
      related: [event({ id: "e5", category: "access", action: "source:manage" })],
    });
    show(<AuditLogCard />);
    const list = await screen.findByTestId("audit-events");
    const user = userEvent.setup();
    await user.click(within(list).getByRole("button", { expanded: false }));
    const detail = await screen.findByTestId("audit-detail");
    expect(within(detail).getByText(/depuis 10.0.0.0\/24 · Requête REQ1/)).toBeInTheDocument();
    expect(within(detail).getByText("kind")).toBeInTheDocument();
    expect(within(detail).getByText("Dans la même requête")).toBeInTheDocument();
  });
});

describe("AuditRetentionCard", () => {
  it("is changed by the owner", async () => {
    api.keep.mockResolvedValue({});
    show(<AuditRetentionCard canChange />);
    expect(await screen.findByTestId("audit-retention")).toHaveTextContent("Conservés 365 jours");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Conservation"), "730");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(api.keep).toHaveBeenCalledWith(730));
  });

  it("is said, not offered, to anyone else", async () => {
    show(<AuditRetentionCard canChange={false} />);
    await screen.findByTestId("audit-retention");
    expect(screen.queryByRole("button", { name: "Enregistrer" })).not.toBeInTheDocument();
    expect(screen.getByText(/Seul le propriétaire/)).toBeInTheDocument();
  });
});
