/**
 * « Premiers pas » (LEKA-445): where a new workspace stands, read from its
 * sources — empty, connected, a first read under way, failing, ready —
 * a failing source said with its cause and what to do, the examples
 * following what is read or said to be examples only, and a card that
 * blocks nothing: put away, or gone once a source is read and a first
 * question asked.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Source } from "@/lib/sources";

const counts = vi.hoisted(() => vi.fn());
vi.mock("@/lib/intentions/api", async (original) => {
  const real = await original<typeof import("@/lib/intentions/api")>();
  return {
    ...real,
    intentions: { ...real.intentions, counts: () => counts() },
  };
});

const { examplesOf, FirstStepsCard, firstStepsOf } =
  await import("@/components/overview/first-steps");

function source(overrides: Partial<Source>): Source {
  return {
    id: crypto.randomUUID(),
    type: "github",
    display_name: "acme/backend",
    status: "active",
    config: {},
    capabilities: [],
    source_metadata: {},
    health_status: "healthy",
    last_health_check_at: null,
    last_error: null,
    sync_status: "idle",
    last_sync_at: "2026-10-14T06:00:00Z",
    credentials: null,
    created_by: null,
    created_at: "2026-10-14T05:00:00Z",
    updated_at: "2026-10-14T06:00:00Z",
    ...overrides,
  } as Source;
}

const NEVER = { sync_status: "never", last_sync_at: null } as const;
const FAILED = source({
  ...NEVER,
  display_name: "Jira Acme",
  type: "jira",
  sync_status: "failed",
  status: "error",
  last_error: {
    code: "AUTH_INVALID",
    retryable: false,
    message: "Jira a refusé le jeton.",
    remediation: "Générez un nouveau jeton et collez-le dans la source.",
  },
});

describe("firstStepsOf", () => {
  it("says each stage from the sources, never assumed", () => {
    expect(firstStepsOf([]).stage).toBe("empty");
    // Begun, not switched on: nothing connected yet.
    expect(firstStepsOf([source({ status: "draft", ...NEVER })]).stage).toBe(
      "empty",
    );
    expect(firstStepsOf([source(NEVER)]).stage).toBe("connected");
    expect(
      firstStepsOf([source({ ...NEVER, sync_status: "running" })]).stage,
    ).toBe("syncing");
    expect(firstStepsOf([FAILED]).stage).toBe("failed");
    expect(firstStepsOf([source({})]).stage).toBe("ready");
  });

  it("is ready once one source is read, the failing one still said", () => {
    const steps = firstStepsOf([
      source({}),
      FAILED,
      source({ type: "datadog" }),
    ]);
    expect(steps.stage).toBe("ready");
    expect(steps.failing.map((s) => s.display_name)).toEqual(["Jira Acme"]);
    expect(steps.read).toEqual(["code", "observability"]);
  });

  it("gives examples only for what is read", () => {
    expect(examplesOf([])).toBeNull();
    expect(examplesOf(["chat"])).toBeNull();
    expect(examplesOf(["observability", "code"])).toEqual([
      "code",
      "observability",
    ]);
  });
});

function renderCard(sources: Source[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LocaleProvider>
        <FirstStepsCard sources={sources} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const asked = (all: number) => ({
  all,
  active: all,
  scheduled: 0,
  finished: 0,
  archived: 0,
});

describe("FirstStepsCard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    counts.mockResolvedValue(asked(0));
  });

  it("an empty workspace: what LEKA does, connect first, examples said to be examples", async () => {
    renderCard([]);
    const card = await screen.findByTestId("first-steps");
    expect(card).toHaveAttribute("data-stage", "empty");
    expect(card).toHaveTextContent("LEKA lit vos outils");
    expect(screen.getByTestId("first-steps-stage")).toHaveTextContent(
      "Aucune source n'est connectée",
    );
    expect(screen.getByTestId("first-steps-action")).toHaveAttribute(
      "href",
      "/welcome",
    );
    expect(card).toHaveTextContent("Exemples seulement");
    // An example opens the composer with its words, to ask or change.
    const first = within(
      screen.getByTestId("first-steps-examples"),
    ).getAllByRole("link")[0];
    expect(first.getAttribute("href")).toMatch(/^\/intentions\/new\?q=/);
  });

  it("a failing source: its cause and what to do, the way to fix it", async () => {
    renderCard([FAILED]);
    const failing = await screen.findByTestId("first-steps-failing");
    expect(failing).toHaveTextContent(
      "Jira Acme Jira a refusé le jeton. Générez un nouveau jeton et collez-le dans la source.",
    );
    expect(screen.getByTestId("first-steps-action")).toHaveAttribute(
      "href",
      `/sources/${FAILED.id}`,
    );
  });

  it("ready: what is read said, examples for it", async () => {
    renderCard([source({})]);
    const card = await screen.findByTestId("first-steps");
    expect(card).toHaveAttribute("data-stage", "ready");
    expect(screen.getByTestId("first-steps-stage")).toHaveTextContent(
      "Prêt : LEKA lit développement.",
    );
    expect(card).not.toHaveTextContent("Exemples seulement");
    expect(screen.getByTestId("first-steps-examples")).toHaveTextContent(
      "Qu'est-ce qui a changé dans le code cette semaine ?",
    );
    expect(screen.queryByTestId("first-steps-action")).toBeNull();
  });

  it("blocks nothing: gone once read and asked, and put away when asked", async () => {
    counts.mockResolvedValue(asked(1));
    const { unmount } = renderCard([source({})]);
    await vi.waitFor(() => expect(counts).toHaveBeenCalled());
    expect(screen.queryByTestId("first-steps")).toBeNull();
    unmount();

    counts.mockResolvedValue(asked(0));
    const again = renderCard([]);
    fireEvent.click(
      await screen.findByRole("button", { name: "Masquer les premiers pas" }),
    );
    expect(screen.queryByTestId("first-steps")).toBeNull();
    again.unmount();
    // Remembered: not back on the next visit.
    renderCard([]);
    await vi.waitFor(() => expect(counts).toHaveBeenCalledTimes(3));
    expect(screen.queryByTestId("first-steps")).toBeNull();
  });
});
