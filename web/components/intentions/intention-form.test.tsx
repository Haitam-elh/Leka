/**
 * Step 1 of "Nouvelle intention" (LEKA-341): what it offers to read and
 * where to look is the workspace's own.
 *
 * What these protect: the sources listed are the ones the workspace has
 * connected and can read — a broken one is not offered — each with its
 * tool and what kind of thing it holds, each box named by its source, all
 * ticked once they arrive; none connected says so and leads to connecting
 * one; the environments and the services are those the company model
 * knows, "Tous les environnements" first and production chosen when there
 * is one. Nothing invented. Submitted (LEKA-373): the intention is asked
 * as the form says it — every source when all are ticked, no period nobody
 * chose — and step 2 shows the context it asks for; nothing to start from
 * is said in the form. Edited after step 2 (LEKA-374), the same context is
 * asked again rather than a new one made.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
}));

const sourcesApi = { list: vi.fn() };
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));

const environmentApi = { get: vi.fn(), sheet: vi.fn() };
vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: environmentApi,
}));

// What submitting asks (LEKA-384): the intention kept, with the context it
// needs (LEKA-373).
const intentionsApi = { create: vi.fn(), ask: vi.fn(), brief: vi.fn() };
vi.mock("@/lib/intentions/api", async (original) => {
  const real = await original<typeof import("@/lib/intentions/api")>();
  return {
    ...real,
    submitIntention: intentionsApi.create,
    reaskIntention: intentionsApi.ask,
    intentions: { ...real.intentions, brief: intentionsApi.brief },
  };
});

/** What POST /intentions/brief answers (LEKA-439): what LEKA understood,
 * its brief, what it reads, what it takes. */
function preview(
  decision: "analyse" | "clarify" | "continue" | "block" = "analyse",
  questions: Record<string, unknown>[] = [],
) {
  return {
    understanding: {
      version: 4,
      text: "x",
      mode: "question",
      mode_said: null,
      kind: "diagnose",
      goal: { code: "explain_cause", said: ["pourquoi"], confidence: 0.9 },
      actions: [],
      withheld: [],
      entities: [],
      period: null,
      environment: null,
      ambiguities: [],
      clear: decision !== "clarify" && decision !== "block",
      scope: null,
    },
    brief: {
      version: 1,
      decision,
      restated: null,
      acting: false,
      slots: [
        { slot: "goal", state: "known", need: "blocking", value: "explain_cause", values: [], origin: "words" },
        { slot: "target", state: "known", need: "useful", value: null, values: ["acme/backend"], origin: "company_model" },
        { slot: "scope", state: "assumed", need: "optional", value: null, values: [], origin: "default" },
        { slot: "expected", state: "known", need: "useful", value: "answer", values: [], origin: "words" },
        { slot: "constraints", state: "missing", need: "optional", value: null, values: [], origin: null },
      ],
      questions,
      limits: [],
    },
    sources: [{ id: "s1", name: "acme/backend", kind: "github", status: "active" }],
    feasibility: {
      verdict: "ready",
      needed: [],
      credits: {
        plan: "free",
        allowance: 200,
        used: 12,
        remaining: 188,
        state: "ok",
        enforced: true,
        period_end: "2026-11-01T00:00:00Z",
      },
      estimate: null,
      path: [],
    },
  };
}

/** What POST /intentions answers: the intention, and its context. */
function created(context: Record<string, unknown>) {
  return { intention: { id: "i1", links: [], status: "analysing" }, context };
}

const { IntentionForm } = await import("@/components/intentions/intention-form");

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <IntentionForm />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function node(id: string, name: string, type = "service") {
  return { id, type, layer: "services", name, status: null, entity_id: id, key: null };
}

beforeEach(() => {
  vi.clearAllMocks();
  intentionsApi.brief.mockResolvedValue(preview());
  sourcesApi.list.mockResolvedValue({
    data: [
      { id: "s1", type: "github", display_name: "acme/backend", status: "active" },
      { id: "s2", type: "jira", display_name: "OPS board", status: "degraded" },
      { id: "s3", type: "slack", display_name: "#incidents", status: "error" },
    ],
    next_cursor: null,
  });
  environmentApi.get.mockResolvedValue({
    environments: ["production", "staging"],
    nodes: [
      node("e1", "payment-api"),
      node("e2", "auth-service"),
      node("e3", "postgres-prod", "database"),
    ],
  });
});

describe("the new intention's context and scope", () => {
  it("offers the sources the workspace can read, each said, all ticked once they arrive", async () => {
    show();

    const backend = await screen.findByText("acme/backend");
    const list = backend.closest('[role="group"]') as HTMLElement;
    expect(list).toHaveTextContent("GitHub · Développement");
    expect(list).toHaveTextContent("OPS board");
    // Broken: nothing to read from it.
    expect(list).not.toHaveTextContent("#incidents");
    // Each box named by its own source, not by the panel: GitHub is not Jira.
    expect(within(list).getAllByRole("checkbox")).toHaveLength(2);
    expect(await screen.findByRole("checkbox", { name: "acme/backend" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "OPS board" })).toBeChecked();
  });

  it("lists one of each kind first, five at once, the rest on asking", async () => {
    const user = userEvent.setup();
    const source = (id: string, type: string, display_name: string) => ({
      id,
      type,
      display_name,
      status: "active",
    });
    sourcesApi.list.mockResolvedValue({
      data: [
        source("a", "slack", "#incidents"),
        source("b", "github", "acme/frontend"),
        source("c", "github", "acme/backend"),
        source("d", "jira", "OPS board"),
        source("e", "datadog", "acme-eu"),
        source("f", "confluence", "Engineering space"),
        source("g", "aws", "production account"),
      ],
      next_cursor: null,
    });
    show();
    await screen.findByText("acme/backend");
    const list = screen.getByText("acme/backend").closest('[role="group"]') as HTMLElement;
    // Code, tickets, docs, cloud, observability — then the next of each.
    // Each box is named by its row's title.
    const named = (box: HTMLElement) =>
      document.getElementById(box.getAttribute("aria-labelledby") ?? "")?.textContent;
    expect(within(list).getAllByRole("checkbox").map(named)).toEqual([
      "acme/backend",
      "OPS board",
      "Engineering space",
      "production account",
      "acme-eu",
    ]);
    await user.click(screen.getByTestId("selectable-more"));
    expect(within(list).getAllByRole("checkbox")).toHaveLength(7);
    expect(screen.getByTestId("selectable-more")).toHaveTextContent("Voir moins");
  });

  it("says when none is connected, and leads to connecting one", async () => {
    sourcesApi.list.mockResolvedValue({ data: [], next_cursor: null });
    show();

    const empty = await screen.findByTestId("intention-no-sources");
    expect(empty).toHaveTextContent("Aucune source connectée");
    expect(within(empty).getByRole("link", { name: "Connecter une source" })).toHaveAttribute(
      "href",
      "/sources",
    );
  });

  it("scopes to the environments and services the company model knows", async () => {
    const user = userEvent.setup();
    show();

    const scope = screen.getByRole("heading", { name: "Périmètre de l'analyse" })
      .parentElement?.parentElement as HTMLElement;
    // Production, once the model says there is one; every service until narrowed.
    expect(await within(scope).findByText("Production")).toBeInTheDocument();
    expect(scope).toHaveTextContent("Tous les services");

    await user.click(within(scope).getByRole("button", { name: "Modifier" }));
    await user.click(within(scope).getByRole("combobox", { name: /Environnement/ }));
    const environments = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(environments).toEqual(["Tous les environnements", "Production", "Staging"]);
  });

  it("asks for the context the intention needs, and shows it", async () => {
    const { ApiError } = await import("@/lib/api");
    intentionsApi.create.mockRejectedValueOnce(new ApiError(422, "/intentions", "Nothing."));
    intentionsApi.create.mockResolvedValueOnce(
      created({
        context_id: "c1",
        purpose: "Pourquoi acme/backend est lent depuis hier ?",
        elements: [],
        sources: [],
        intent: null,
      }),
    );
    const user = userEvent.setup();
    show();
    await screen.findByRole("checkbox", { name: "acme/backend" });
    await screen.findByText("Production");

    await user.type(
      screen.getByTestId("intention-input"),
      "Pourquoi acme/backend est lent depuis hier ?",
    );
    // What LEKA understood, first — then launched.
    await user.click(screen.getByTestId("intention-submit"));
    expect(await screen.findByTestId("intention-review")).toBeInTheDocument();
    await user.click(screen.getByTestId("intention-launch"));
    expect(
      await screen.findByText(
        "Votre demande ne nomme rien du modèle et ne contient aucun mot à chercher : précisez-la.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("intention-launch"));
    expect(await screen.findByTestId("intention-step-2")).toBeInTheDocument();
    // Kept: its analysis followed on its page.
    expect(screen.getByTestId("intention-follow")).toHaveAttribute("href", "/intentions/i1");
    expect(intentionsApi.create).toHaveBeenLastCalledWith(
      {
        text: "Pourquoi acme/backend est lent depuis hier ?",
        services: [],
        // Every readable source ticked: no narrowing.
        sources: [],
        limit: 100,
        environment: "production",
        answers: [],
      },
      // With its key: sent again, the same intention (LEKA-443).
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
  });

  it("asks what a request lacks before it is launched, and launches it with the answer", async () => {
    // LEKA-439: an action that does not say where — asked, with the
    // environments LEKA knows, why, and « je ne sais pas »; answered, read
    // again; launched with the answer.
    intentionsApi.brief.mockResolvedValueOnce(
      preview("clarify", [
        {
          kind: "missing_environment",
          slot: "scope",
          blocking: true,
          said: "Several environments.",
          options: ["production", "staging"],
          choices: [],
          free: false,
          answer: null,
        },
      ]),
    );
    intentionsApi.create.mockResolvedValueOnce(
      created({ context_id: "c1", purpose: "x", elements: [], sources: [], intent: null }),
    );
    const user = userEvent.setup();
    show();
    await screen.findByRole("checkbox", { name: "acme/backend" });
    await user.type(screen.getByTestId("intention-input"), "Redémarre acme/backend maintenant");
    await user.click(screen.getByTestId("intention-submit"));

    const question = await screen.findByTestId("brief-question");
    expect(question).toHaveTextContent("dans lequel agir ?");
    expect(within(question).getByTestId("brief-why")).toHaveTextContent(
      "Pourquoi : Une action doit savoir où elle s'applique",
    );
    expect(within(question).getByTestId("brief-unknown")).toHaveTextContent("Je ne sais pas");
    // Blocked until it is answered: nothing launched on a doubt.
    expect(screen.getByTestId("intention-launch")).toBeDisabled();
    expect(screen.getByTestId("brief-decision")).toHaveTextContent("Répondez à la question");

    await user.click(within(question).getByRole("button", { name: "staging" }));
    await waitFor(() =>
      expect(intentionsApi.brief).toHaveBeenLastCalledWith(
        expect.objectContaining({
          answers: [{ question: "missing_environment", value: "staging", unknown: false }],
        }),
      ),
    );
    await waitFor(() => expect(screen.getByTestId("intention-launch")).toBeEnabled());
    await user.click(screen.getByTestId("intention-launch"));
    await waitFor(() =>
      expect(intentionsApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          answers: [{ question: "missing_environment", value: "staging", unknown: false }],
        }),
        expect.any(String),
      ),
    );
  });

  it("asks the same intention again once it is edited", async () => {
    intentionsApi.create.mockResolvedValueOnce(
      created({
        context_id: "c1",
        version: 1,
        purpose: "Pourquoi acme/backend est lent ?",
        elements: [],
        sources: [],
        intent: null,
      }),
    );
    intentionsApi.ask.mockResolvedValueOnce(
      created({
        context_id: "c1",
        version: 2,
        trigger: "reasked",
        purpose: "Qui est responsable de acme/backend ?",
        elements: [],
        sources: [],
        intent: null,
        changes: [],
        delta: { added: 1, removed: 2, changed: 0, unchanged: 4 },
      }),
    );
    const user = userEvent.setup();
    show();
    await screen.findByRole("checkbox", { name: "acme/backend" });

    await user.type(screen.getByTestId("intention-input"), "Pourquoi acme/backend est lent ?");
    await user.click(screen.getByTestId("intention-submit"));
    await user.click(await screen.findByTestId("intention-launch"));
    await user.click(await screen.findByRole("button", { name: "Modifier" }));
    const input = await screen.findByTestId("intention-input");
    await user.clear(input);
    await user.type(input, "Qui est responsable de acme/backend ?");
    await user.click(screen.getByTestId("intention-submit"));
    await user.click(await screen.findByTestId("intention-launch"));

    expect(await screen.findByTestId("intent-asked-again")).toHaveTextContent(
      "Version 2 de ce contexte : votre demande a changé, LEKA l'a relue.",
    );
    expect(intentionsApi.create).toHaveBeenCalledTimes(1);
    expect(intentionsApi.ask).toHaveBeenCalledWith(
      "i1",
      expect.objectContaining({ text: "Qui est responsable de acme/backend ?" }),
    );
  });
});
