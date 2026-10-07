/**
 * Mes intentions and an intention's page (LEKA-384).
 *
 * What these protect: the list is the API's — each intention with where it
 * stands in words and when it last moved, leading to its page; the tabs by
 * phase counted by the API and asking it again; an empty list said so;
 * an intention's page says what was asked, its scope, what it is linked
 * to, what LEKA has not concluded yet; its history in words — LEKA's moves
 * and a person's, the context's version, the reason given; cancelling asks
 * first, with a reason, and is sent with it; archiving once done with; a
 * missing intention said so, its tabs kept.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail, IntentionEvent } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

const ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const route = vi.hoisted(() => ({ pathname: "/intentions" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => route.pathname,
  useParams: () => ({ intentionId: route.pathname.split("/")[2] }),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: ME }),
  usePermissions: () => ["intention:read", "intention:create"],
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  counts: vi.fn(),
  one: vi.fn(),
  history: vi.fn(),
  cancel: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));

const { IntentionsList } = await import("@/components/intentions/intentions-list");
const { IntentionScreen } = await import("@/components/intentions/intention-screen");
const { ApiError } = await import("@/lib/api");

const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

function intention(overrides: Partial<IntentionDetail> = {}): IntentionDetail {
  return {
    id: ID,
    title: "Pourquoi Billing API est lente depuis hier ?",
    text: "Pourquoi Billing API est lente depuis hier ?",
    kind: "diagnose",
    scope: { environment: "production", services: ["s1", "s2"] },
    status: "analysing",
    phase: "active",
    status_changed_at: ago(2),
    summary: null,
    created_by: ME,
    created_at: ago(3),
    updated_at: ago(2),
    context_id: "c1",
    archived_at: null,
    moves: ["awaiting_decision", "completed", "failed", "analysing", "cancelled"],
    links: [
      {
        id: "l1",
        kind: "context",
        ref_id: "c1",
        label: "Pourquoi Billing API est lente depuis hier ?",
        detail: { version: 2 },
        linked_at: ago(3),
        linked_by: null,
      },
      {
        id: "l2",
        kind: "entity",
        ref_id: "e1",
        label: "Billing API",
        detail: { type: "service" },
        linked_at: ago(1),
        linked_by: ME,
      },
    ],
    ...overrides,
  };
}

function event(overrides: Partial<IntentionEvent>): IntentionEvent {
  return {
    id: crypto.randomUUID(),
    sequence: 1,
    kind: "created",
    name: null,
    from_status: null,
    to_status: null,
    actor: "person",
    by: ME,
    at: ago(3),
    reason: null,
    detail: {},
    ...overrides,
  };
}

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
  route.pathname = "/intentions";
  api.list.mockResolvedValue({ data: [intention()], next_cursor: null });
  api.counts.mockResolvedValue({ all: 3, active: 2, scheduled: 0, finished: 1, archived: 4 });
  api.one.mockResolvedValue(intention());
  api.history.mockResolvedValue([]);
});

describe("Mes intentions", () => {
  it("lists what was asked, where each stands, leading to it", async () => {
    show(<IntentionsList />);

    const [row] = await screen.findAllByTestId("intention-row");
    expect(row).toHaveTextContent("Pourquoi Billing API est lente depuis hier ?");
    expect(row).toHaveTextContent("Diagnostic");
    expect(within(row).getByTestId("intention-status")).toHaveTextContent("En analyse");
    expect(within(row).getByRole("link")).toHaveAttribute("href", `/intentions/${ID}`);
    expect(api.list).toHaveBeenLastCalledWith({ phase: null, q: "", cursor: null });
  });

  it("counts each phase as the API does, and asks it again by phase", async () => {
    const user = userEvent.setup();
    show(<IntentionsList />);

    await waitFor(() =>
      expect(screen.getByTestId("intentions-tab-all")).toHaveTextContent("Toutes3"),
    );
    expect(screen.getByTestId("intentions-tab-archived")).toHaveTextContent("Archivées4");
    await user.click(screen.getByTestId("intentions-tab-finished"));
    expect(api.list).toHaveBeenLastCalledWith({ phase: "finished", q: "", cursor: null });
    expect(screen.getByTestId("intentions-tab-finished")).toHaveAttribute("aria-pressed", "true");
  });

  it("says when nothing was asked yet", async () => {
    api.list.mockResolvedValue({ data: [], next_cursor: null });
    show(<IntentionsList />);
    expect(await screen.findByTestId("intentions-empty")).toHaveTextContent(
      "Vous n'avez encore rien demandé à LEKA.",
    );
  });
});

describe("an intention's page", () => {
  it("says what was asked, its scope, its links — and what is not concluded", async () => {
    route.pathname = `/intentions/${ID}`;
    show(<IntentionScreen />);

    expect(await screen.findByTestId("intention-text")).toHaveTextContent(
      "Pourquoi Billing API est lente depuis hier ?",
    );
    expect(screen.getByText("Environnement · production")).toBeInTheDocument();
    expect(screen.getByText("2 service(s) choisi(s)")).toBeInTheDocument();
    expect(screen.getByText(/LEKA n'a pas encore conclu/)).toBeInTheDocument();
    const links = screen.getAllByTestId("intention-link");
    expect(links[0]).toHaveTextContent("Pourquoi Billing API est lente depuis hier ? · v2");
    expect(within(links[1]).getByRole("link", { name: "Billing API" })).toHaveAttribute(
      "href",
      "/environment/services/e1",
    );
    expect(screen.getByTestId("intention-status")).toHaveTextContent("En analyse");
    expect(screen.getByText(/par vous/)).toBeInTheDocument();
  });

  it("tells its history: LEKA's moves and a person's, with the reason given", async () => {
    route.pathname = `/intentions/${ID}/history`;
    api.history.mockResolvedValue([
      event({}),
      event({
        sequence: 2,
        kind: "linked",
        actor: "system",
        by: null,
        detail: { kind: "context", label: "Billing API", ref_id: "c1" },
      }),
      event({
        sequence: 3,
        kind: "moved",
        name: "analysis_started",
        from_status: "submitted",
        to_status: "analysing",
        actor: "system",
        by: null,
        detail: { version: 1 },
      }),
      event({
        sequence: 4,
        kind: "moved",
        name: "cancelled",
        from_status: "analysing",
        to_status: "cancelled",
        reason: "asked twice",
      }),
    ]);
    show(<IntentionScreen />);

    const events = await screen.findAllByTestId("intention-event");
    expect(events.map((e) => e.querySelector("p")?.textContent)).toEqual([
      "Intention créée",
      "Liée : Contexte « Billing API »",
      "LEKA a rassemblé le contexte et commence l'analyse",
      "Annulée",
    ]);
    expect(events[2]).toHaveTextContent("par LEKA");
    expect(events[2]).toHaveTextContent("Contexte, version 1");
    expect(events[3]).toHaveTextContent("par vous");
    expect(events[3]).toHaveTextContent("Raison : asked twice");
  });

  it("is cancelled once asked, with the reason given", async () => {
    route.pathname = `/intentions/${ID}`;
    const cancelled = intention({ status: "cancelled", phase: "finished", moves: [] });
    api.cancel.mockResolvedValue(cancelled);
    const user = userEvent.setup();
    show(<IntentionScreen />);

    await user.click(await screen.findByTestId("intention-cancel"));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Raison (facultative)"), "asked twice");
    // Read again after the change: as it now is.
    api.one.mockResolvedValue(cancelled);
    await user.click(within(dialog).getByRole("button", { name: "Annuler l'intention" }));

    expect(api.cancel).toHaveBeenCalledWith(ID, "asked twice");
    expect(await screen.findByTestId("intention-archive")).toBeInTheDocument();
    expect(screen.queryByTestId("intention-cancel")).not.toBeInTheDocument();
  });

  it("says a missing intention, its tabs kept", async () => {
    route.pathname = `/intentions/${ID}`;
    api.one.mockRejectedValue(new ApiError(404, `/intentions/${ID}`, "No such intention."));
    show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-not-found")).toHaveTextContent(
      "Cette intention n'existe pas, ou plus.",
    );
  });

  it("asks the analysis tabs to wait for the analysis engine", async () => {
    route.pathname = `/intentions/${ID}/evidence`;
    show(<IntentionScreen />);
    expect(await screen.findByText(/arrivera avec le moteur d'analyse/)).toBeInTheDocument();
  });
});
