/**
 * Mes intentions and an intention's page (LEKA-384).
 *
 * What these protect: the list is the API's — each intention with where it
 * stands in words and when it last moved, leading to its page; the tabs by
 * phase counted by the API and asking it again; an empty list said so;
 * an intention's page says what was asked, its scope, what it is linked
 * to, what LEKA has not concluded yet; its whole story in words, in order
 * (LEKA-392) — LEKA's moves and a person's, by name, the context's
 * version, the reason given, its analysis — filtered; cancelling asks
 * first, with a reason, and is sent with it; archiving once done with; a
 * missing intention said so, its tabs kept.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import type { TimelineItem } from "@/lib/outcomes";
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
  analysis: vi.fn(),
  answer: vi.fn(),
  feasibility: vi.fn(),
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));
const told = vi.hoisted(() => ({ timeline: vi.fn() }));
vi.mock("@/lib/outcomes", async (original) => ({
  ...(await original<typeof import("@/lib/outcomes")>()),
  outcomes: told,
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
    goal: "explain_cause",
    understanding: null,
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

function item(overrides: Partial<TimelineItem>): TimelineItem {
  return {
    id: `event:${crypto.randomUUID()}`,
    intention_id: ID,
    title: null,
    category: "intention",
    kind: "created",
    at: ago(3),
    actor: "person",
    by: ME,
    by_name: "Nora Diallo",
    reason: null,
    detail: { event: "created" },
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
  api.analysis.mockRejectedValue(new ApiError(404, `/intentions/${ID}/analysis`, "No analysis yet."));
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

  it("says when nothing was asked yet, and the way to ask", async () => {
    api.list.mockResolvedValue({ data: [], next_cursor: null });
    show(<IntentionsList />);
    const empty = await screen.findByTestId("intentions-empty");
    expect(empty).toHaveTextContent("Vous n'avez encore rien demandé à LEKA.");
    expect(within(empty).getByRole("link", { name: /Nouvelle intention/ })).toHaveAttribute(
      "href",
      "/intentions/new",
    );
  });

  it("on a wide screen, a row is shown beside the list rather than left", async () => {
    const other = intention({ id: "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41", title: "Qui maintient Billing API ?" });
    api.list.mockResolvedValue({ data: [intention(), other], next_cursor: null });
    api.one.mockImplementation(async (id: string) => (id === other.id ? other : intention()));
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const user = userEvent.setup();
    show(<IntentionsList />);

    const rows = await screen.findAllByTestId("intention-row");
    await user.click(within(rows[1]).getByRole("link"));
    const preview = await screen.findByTestId("intention-preview");
    await waitFor(() => expect(preview).toHaveTextContent("Qui maintient Billing API ?"));
    expect(preview).toHaveTextContent("Sélectionnée");
    expect(within(rows[1]).getByRole("link")).toHaveAttribute("aria-current", "true");
    delete (window as Partial<Window>).matchMedia;
  });
});

describe("an intention's page", () => {
  it("says what was asked, its scope, its links — and what is not concluded", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    show(<IntentionScreen />);

    expect(await screen.findByTestId("intention-text")).toHaveTextContent(
      "Pourquoi Billing API est lente depuis hier ?",
    );
    expect(screen.getByText("Environnement · production")).toBeInTheDocument();
    expect(screen.getByText("2 services choisis")).toBeInTheDocument();
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

  it("tells its whole story, in order, and filters it", async () => {
    const user = userEvent.setup();
    route.pathname = `/intentions/${ID}/history`;
    // As the API says it: the latest first.
    told.timeline.mockResolvedValue([
      item({
        kind: "cancelled",
        at: ago(1),
        reason: "asked twice",
        detail: { event: "moved", from_status: "analysing", to_status: "cancelled" },
      }),
      item({
        id: "vote:v1",
        category: "decision",
        kind: "vote_request_changes",
        at: ago(1.5),
        by: "8c3bc5ff-a12e-5e92-a5ae-ad6da2029a41",
        by_name: "Sara Martin",
        detail: { revision: 1 },
      }),
      item({
        id: "analysis:a1:started",
        category: "analysis",
        kind: "analysis_started",
        at: ago(2),
        actor: "system",
        by: null,
        by_name: null,
        detail: { number: 1 },
      }),
      item({
        kind: "analysis_started",
        at: ago(2.5),
        actor: "system",
        by: null,
        by_name: null,
        detail: { event: "moved", version: 1, from_status: "submitted", to_status: "analysing" },
      }),
      // A finding of LEKA's, worded as Insights words it — its statement is
      // the API's English.
      item({
        kind: "linked",
        at: ago(2.75),
        actor: "system",
        by: null,
        by_name: null,
        detail: {
          event: "linked",
          kind: "finding",
          label: "3 things rely on postgres-prod (database); nothing watches it.",
          code: "dependency.concentration",
          params: { dependents: 3, name: "postgres-prod", kind: "database" },
        },
      }),
      item({
        kind: "linked",
        at: ago(2.8),
        actor: "system",
        by: null,
        by_name: null,
        detail: { event: "linked", kind: "context", label: "Billing API" },
      }),
      item({}),
    ]);
    show(<IntentionScreen />);

    const events = await screen.findAllByTestId("intention-event");
    expect(events.map((e) => e.querySelector("p")?.textContent)).toEqual([
      "Intention créée",
      "Liée : Contexte « Billing API »",
      "Liée : Constat « 3 éléments dépendent de postgres-prod »",
      "LEKA a rassemblé le contexte et commence l'analyse",
      "Analyse lancée",
      "Modifications demandées",
      "Annulée",
    ]);
    expect(events[3]).toHaveTextContent("par LEKA");
    expect(events[3]).toHaveTextContent("Contexte, version 1");
    expect(events[4]).toHaveTextContent("Analyse n° 1");
    expect(events[5]).toHaveTextContent("par Sara Martin");
    expect(events[5]).toHaveTextContent("Décision");
    expect(events[6]).toHaveTextContent("par vous");
    expect(events[6]).toHaveTextContent("Raison : asked twice");
    expect(told.timeline).toHaveBeenLastCalledWith(ID, { categories: [], actor: null });

    // Filtered: by kind of thing, by who.
    await user.click(screen.getByTestId("timeline-category-decision"));
    await waitFor(() =>
      expect(told.timeline).toHaveBeenLastCalledWith(ID, { categories: ["decision"], actor: null }),
    );
    await user.click(screen.getByTestId("timeline-actor-person"));
    await waitFor(() =>
      expect(told.timeline).toHaveBeenLastCalledWith(ID, {
        categories: ["decision"],
        actor: "person",
      }),
    );
    told.timeline.mockResolvedValue([]);
    await user.click(screen.getByTestId("timeline-actor-system"));
    expect(await screen.findByText("Rien ne correspond à ces filtres.")).toBeInTheDocument();
  });

  it("is cancelled once asked, with the reason given", async () => {
    route.pathname = `/intentions/${ID}/overview`;
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

  it("tells its story again once it moved", async () => {
    route.pathname = `/intentions/${ID}/history`;
    told.timeline.mockResolvedValue([item({})]);
    api.cancel.mockResolvedValue(intention({ status: "cancelled", phase: "finished", moves: [] }));
    const user = userEvent.setup();
    show(<IntentionScreen />);
    expect(await screen.findAllByTestId("intention-event")).toHaveLength(1);

    told.timeline.mockResolvedValue([
      item({
        kind: "cancelled",
        at: ago(0),
        detail: { event: "moved", from_status: "analysing", to_status: "cancelled" },
      }),
      item({}),
    ]);
    await user.click(await screen.findByTestId("intention-cancel"));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Annuler l'intention" }));
    await waitFor(() => expect(screen.getAllByTestId("intention-event")).toHaveLength(2));
    expect(screen.getAllByTestId("intention-event")[1]).toHaveTextContent("Annulée");
  });

  it("says what LEKA understood, each part with its words", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.one.mockResolvedValue(
      intention({
        goal: "act",
        understanding: {
          version: 1,
          text: "Redémarre Billing API",
          mode: "request",
          mode_said: "redemarre",
          kind: "general",
          goal: { code: "act", said: ["redemarre"], confidence: 0.9 },
          actions: [{ code: "restart", said: "redemarre", changes_systems: true, polarity: "affirmed", targets: [] }],
          entities: [
            {
              entity_id: "e1",
              name: "Billing API",
              type: "service",
              how: "named",
              said: "billing api",
              confidence: 1,
            },
          ],
          period: null,
          environment: null,
          ambiguities: [
            { kind: "several_requests", blocking: false, said: "…", options: [] },
          ],
          clear: true,
        },
      }),
    );
    show(<IntentionScreen />);

    expect(await screen.findByTestId("understanding-goal")).toHaveTextContent(
      "Agir · Une demande d'action« redemarre »",
    );
    const [action] = screen.getAllByTestId("understanding-action");
    expect(action).toHaveTextContent("Redémarrer « redemarre »");
    expect(action).toHaveTextContent("modifie vos systèmes : validation requise");
    const panel = screen.getByTestId("intention-understanding");
    expect(within(panel).getByRole("link", { name: "Billing API" })).toHaveAttribute(
      "href",
      "/environment/services/e1",
    );
    expect(screen.getByTestId("understanding-notes")).toHaveTextContent(
      "Votre demande contient plusieurs demandes",
    );
    expect(screen.queryByTestId("understanding-needs")).not.toBeInTheDocument();
  });

  it("says its scope: where, when, what is excluded, under what constraints", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.one.mockResolvedValue(
      intention({
        understanding: {
          version: 2,
          text: "Qu'est-ce qui dépend de Billing API, sauf auth-service, sans rien modifier ?",
          mode: "question",
          mode_said: "?",
          kind: "dependency",
          goal: { code: "map_dependencies", said: ["depend"], confidence: 0.6 },
          actions: [],
          entities: [],
          period: null,
          environment: "production",
          ambiguities: [],
          clear: true,
          scope: {
            entities: [
              {
                entity_id: "e1",
                name: "Billing API",
                type: "service",
                how: "named",
                said: "billing api",
                confidence: 1,
                lifecycle: "dormant",
              },
            ],
            excluded: [
              {
                entity_id: "e2",
                name: "auth-service",
                type: "service",
                how: "named",
                said: "auth service",
                confidence: 1,
                lifecycle: "active",
              },
            ],
            environments: ["production"],
            environment_origin: "asked",
            period: {
              since: ago(24),
              until: ago(0),
              origin: "text",
              said: "depuis hier",
              explicit: true,
            },
            sources: [],
            constraints: [
              { kind: "exclude", said: "auth service", value: "e2", hard: true },
              { kind: "read_only", said: "sans rien modifier", value: true, hard: true },
              { kind: "deadline", said: "avant vendredi", value: "2026-10-09", hard: true },
            ],
            missing: [],
          },
        },
      }),
    );
    show(<IntentionScreen />);

    const scope = await screen.findByTestId("understanding-scope");
    expect(within(scope).getByTestId("scope-environment")).toHaveTextContent("production · choisi");
    expect(within(scope).getByTestId("scope-period")).toHaveTextContent(
      "dite dans la demande : « depuis hier »",
    );
    expect(within(scope).getByTestId("scope-excluded")).toHaveTextContent("auth-service");
    const constraints = within(scope).getByTestId("scope-constraints");
    expect(constraints).toHaveTextContent("Lecture seule");
    expect(constraints).toHaveTextContent("Échéance : 2026-10-09");
    expect(constraints).not.toHaveTextContent("Exclusion");
    expect(scope).toHaveTextContent("Billing API (inactif)");
  });

  it("says what LEKA needs to go on, and leads to clarifying it", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.one.mockResolvedValue(
      intention({
        status: "needs_clarification",
        goal: "act",
        moves: ["analysing", "cancelled"],
        understanding: {
          version: 1,
          text: "Redémarre le service",
          mode: "request",
          mode_said: "redemarre",
          kind: "general",
          goal: { code: "act", said: ["redemarre"], confidence: 0.5 },
          actions: [{ code: "restart", said: "redemarre", changes_systems: true, polarity: "affirmed", targets: [] }],
          entities: [],
          period: null,
          environment: null,
          ambiguities: [
            {
              kind: "action_without_target",
              blocking: true,
              said: "…",
              options: ["restart"],
            },
          ],
          clear: false,
        },
      }),
    );
    show(<IntentionScreen />);

    expect(await screen.findByTestId("intention-status")).toHaveTextContent("À préciser");
    const [question] = screen.getAllByTestId("understanding-question");
    expect(question).toHaveTextContent("Sur quoi faut-il agir ?");
    expect(question).toHaveTextContent("Possibilités : Redémarrer");
    expect(screen.getByTestId("understanding-clarify")).toHaveAttribute(
      "href",
      `/intentions/new?intention=${ID}`,
    );
  });

  it("asks what it needs on its page, with why, and sends the answer (LEKA-439)", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    const understanding = {
      version: 4,
      text: "Redémarre le service en production",
      mode: "request" as const,
      mode_said: "redemarre",
      kind: "general",
      goal: { code: "act" as const, said: ["redemarre"], confidence: 0.9 },
      actions: [
        { code: "restart", said: "redemarre", changes_systems: true, polarity: "affirmed" as const, targets: [] },
      ],
      withheld: [],
      entities: [],
      period: null,
      environment: "production",
      ambiguities: [],
      clear: false,
      scope: null,
    };
    const waiting = intention({
      status: "needs_clarification",
      goal: "act",
      moves: ["analysing", "cancelled"],
      understanding,
      brief: {
        version: 1,
        decision: "clarify",
        restated: null,
        acting: true,
        slots: [
          { slot: "goal", state: "known", need: "blocking", value: "act", values: [], origin: "words" },
          { slot: "target", state: "missing", need: "blocking", value: null, values: [], origin: null },
          { slot: "scope", state: "known", need: "blocking", value: "production", values: ["production"], origin: "words" },
          { slot: "expected", state: "known", need: "useful", value: "action", values: [], origin: "words" },
          { slot: "constraints", state: "missing", need: "optional", value: null, values: [], origin: null },
        ],
        questions: [
          {
            kind: "action_without_target",
            slot: "target",
            blocking: true,
            said: "On what?",
            options: ["restart"],
            choices: [{ value: "p1", label: "Payment API", type: "service" }],
            free: true,
            answer: null,
          },
        ],
        limits: [],
      },
    });
    api.one.mockResolvedValue(waiting);
    api.feasibility.mockRejectedValue(new ApiError(404, "/x", "No."));
    api.answer.mockResolvedValue({
      intention: { ...waiting, status: "analysing" },
      context: { context_id: "c1" },
    });
    const user = userEvent.setup();
    show(<IntentionScreen />);

    const question = await screen.findByTestId("brief-question");
    expect(question).toHaveTextContent("Sur quoi faut-il agir ?");
    expect(question).toHaveTextContent(
      "Pourquoi : Une action sur vos systèmes doit savoir exactement ce qu'elle touche.",
    );
    // Not the old way round: rewriting the whole request.
    expect(screen.queryByTestId("understanding-clarify")).not.toBeInTheDocument();
    await user.click(within(question).getByRole("button", { name: "Payment API" }));
    await waitFor(() =>
      expect(api.answer).toHaveBeenCalledWith(ID, [
        { question: "action_without_target", value: "p1", unknown: false },
      ]),
    );
    expect(await screen.findByTestId("intention-status")).toHaveTextContent("En analyse");
  });

  it("says whether its context can ground the analysis, and what blocks it", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.one.mockResolvedValue(
      intention({
        readiness: {
          status: "blocked",
          context_id: "c1",
          version: 2,
          level: "low",
          score: 0.4,
          elements: 6,
          facets: { technical: 4, business: 1, organizational: 1, temporal: 0 },
          sources: 2,
          critical: [
            {
              origin: "gap",
              kind: "no_source_for",
              severity: "critical",
              said: "None of the sources read…",
              refs: [],
              gap_origin: "intent",
              detail: { needs: ["incidents", "deployments"] },
              label: null,
              about: null,
            },
            {
              origin: "conflict",
              kind: "competing",
              severity: "critical",
              said: "two owners",
              refs: ["e1"],
              gap_origin: null,
              detail: {},
              label: "Billing API",
              about: "owner",
            },
          ],
          warnings: [],
        },
      }),
    );
    show(<IntentionScreen />);

    const panel = await screen.findByTestId("intention-readiness");
    expect(within(panel).getByTestId("readiness-status")).toHaveTextContent(
      "Bloqué avant l'analyse",
    );
    expect(panel).toHaveTextContent("6 éléments · 2 sources · version 2");
    expect(within(panel).getByTestId("readiness-facets")).toHaveTextContent("métier · 1");
    const critical = within(panel).getByTestId("readiness-critical");
    expect(critical).not.toHaveTextContent("None of the sources");
    expect(critical).toHaveTextContent("Billing API : owner, ses sources se contredisent");
  });

  it("says a missing intention, its tabs kept", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.one.mockRejectedValue(new ApiError(404, `/intentions/${ID}`, "No such intention."));
    show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-not-found")).toHaveTextContent(
      "Cette intention n'existe pas, ou plus.",
    );
  });

});
