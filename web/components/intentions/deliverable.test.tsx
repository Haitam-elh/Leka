/**
 * What an agent delivered (2026-10-14: « l'agent a terminé, mais où est son
 * livrable ? »).
 *
 * What these protect:
 * - Every agent's report is drawn as a page: headings, lists, tables, code,
 *   emphasis, links. What it wrote as HTML is shown as written, never run;
 *   only http(s) links open.
 * - A diff's lines are numbered as the review numbers them.
 * - The code review's deliverable is the repository as it read it:
 *   - its pull requests, the one reviewed marked with its comment count;
 *   - the pull request's files and diff, each comment under its line, red
 *     for what is wrong and green for what to do better or what is right,
 *     with the code it proposes;
 *   - a comment on a whole file above its diff;
 *   - the comments dropped, counted;
 *   - its report one tab away.
 * - An agent still at work: said, no deliverable yet.
 * - Every deliverable offers to send it out: tickets for Jira, pages for
 *   Confluence (their flow: publications.test.tsx).
 * - A review offers its fix: the code-change agent asked from it, on its
 *   repository, for the intention — and its deliverable opened; a report
 *   that reviewed no code does not.
 * - The agent block on the intention leads to its deliverable.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Markdown } from "@/components/ui/markdown";
import type { AgentRun, AgentRunDetail } from "@/lib/agent-runs";
import { diffRows } from "@/lib/diff";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { sampleJourney } from "@/lib/intentions/journey-sample";
import { makeQueryClient } from "@/lib/query";

const search = vi.hoisted(() => ({ value: new URLSearchParams() }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useSearchParams: () => search.value,
  useRouter: () => ({ push }),
}));
const runs = vi.hoisted(() => ({ forIntention: vi.fn(), one: vi.fn(), start: vi.fn(), rewriteChange: vi.fn() }));
vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: runs,
}));

const changes = vi.hoisted(() => ({ list: vi.fn(), forRun: vi.fn(), accept: vi.fn(), reject: vi.fn() }));
vi.mock("@/lib/code-changes", async (original) => ({
  ...(await original<typeof import("@/lib/code-changes")>()),
  codeChanges: changes,
}));

const shell = vi.hoisted(() => ({ permissions: ["intention:read", "intention:create", "intention:approve"] as string[] }));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => shell.permissions }));
const sent = vi.hoisted(() => ({ forRun: vi.fn(), ask: vi.fn(), accept: vi.fn(), reject: vi.fn() }));
vi.mock("@/lib/publications", async (original) => ({
  ...(await original<typeof import("@/lib/publications")>()),
  publications: sent,
}));

const { DeliverableView } = await import("@/components/intentions/deliverable");
const { AgentWork } = await import("@/components/intentions/agent-work");

const PATCH = [
  "@@ -10,4 +10,5 @@ def balance(account):",
  "     total = account.total",
  "-    return total",
  "+    pending = account.pending",
  "+    return total - pending",
  "     # done",
].join("\n");

function run(more: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r1",
    key: "code-review",
    title: "Revue de code",
    version: "1.3.0",
    status: "succeeded",
    inputs: { changement: "la dernière PR de acme/payments" },
    requested_by: null,
    mine: true,
    intention_id: "i1",
    context_id: null,
    context_version: null,
    format: "markdown",
    pending: [],
    deliverables: [],
    error: null,
    reasons: [],
    provider: null,
    model: null,
    model_version: null,
    tool_calls: 2,
    queued_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    ...more,
  };
}

const PULL = {
  number: 7,
  title: "Déduire les paiements en attente",
  state: "closed",
  merged: true,
  draft: false,
  author: "nora",
  url: "https://github.com/acme/payments/pull/7",
  created_at: null,
  updated_at: null,
  merged_at: null,
};

function detail(more: Partial<AgentRunDetail> = {}): AgentRunDetail {
  return {
    ...run(),
    output: "# Revue\n\nLe solde change.",
    report: "# Revue\n\nLe solde change.\n\n- **Avis** : prudence\n- Voir [la PR](https://github.com/acme/payments/pull/7)",
    review: {
      repository: "acme/payments",
      number: 7,
      verdict: "prudence",
      pull: {
        ...PULL,
        body: "",
        base: "main",
        head: "fix/balance",
        additions: 2,
        deletions: 1,
        changed_files: 1,
        files: [
          { path: "app/balance.py", status: "modified", additions: 2, deletions: 1, patch: PATCH, truncated: false },
        ],
      },
      pulls: [PULL, { ...PULL, number: 6, title: "Autre", merged: false, state: "open" }],
      comments: [
        {
          path: "app/balance.py",
          line: 12,
          side: "new",
          kind: "issue",
          severity: "eleve",
          title: "Pending peut être nul",
          comment: "account.pending vaut None pour un compte neuf.",
          suggestion: "pending = account.pending or 0",
        },
        {
          path: "app/balance.py",
          line: 13,
          side: "new",
          kind: "good",
          severity: null,
          title: "Clair",
          comment: "Le retour dit ce qu'il calcule.",
          suggestion: null,
        },
        {
          path: "app/balance.py",
          line: null,
          side: "new",
          kind: "suggestion",
          severity: null,
          title: "Un test",
          comment: "Ajouter un cas sans paiement en attente.",
          suggestion: null,
        },
      ],
      dropped: 1,
    },
    events: [],
    usage: { calls: 3, tokens_in: 1000, tokens_out: 300, cost_usd: null },
    ...more,
  };
}

const INTENTION = {
  id: "i1",
  status: "completed",
  journey: sampleJourney("completed"),
} as unknown as IntentionDetail;

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  search.value = new URLSearchParams();
  changes.forRun.mockResolvedValue([]);
  sent.forRun.mockResolvedValue([]);
});

describe("an agent's report", () => {
  it("is drawn as a page, never as HTML", () => {
    render(
      <Markdown
        source={[
          "# Titre",
          "Un **gras**, un *italique*, du `code` et [un lien](https://leka-core.com).",
          "",
          "- un",
          "  - sous-point",
          "- deux",
          "",
          "| Sévérité | Constat |",
          "| --- | --- |",
          "| élevé | **nul** |",
          "",
          "```python",
          "x = 1",
          "```",
          "<script>alert(1)</script> [piège](javascript:alert(1))",
        ].join("\n")}
      />,
    );
    const page = screen.getByTestId("markdown");
    expect(within(page).getByRole("heading", { name: "Titre" })).toBeInTheDocument();
    expect(page.querySelector("strong")).toHaveTextContent("gras");
    expect(page.querySelector("em")).toHaveTextContent("italique");
    expect(within(page).getByRole("link", { name: "un lien" })).toHaveAttribute("href", "https://leka-core.com");
    expect(within(page).getByRole("table")).toHaveTextContent("élevé");
    expect(page.querySelector("pre")).toHaveTextContent("x = 1");
    expect(page.querySelectorAll("li")).toHaveLength(3);
    // Written, never run.
    expect(page.querySelector("script")).toBeNull();
    expect(page).toHaveTextContent("<script>alert(1)</script>");
    expect(within(page).queryByRole("link", { name: "piège" })).toBeNull();
  });
});

describe("a diff's lines", () => {
  it("are numbered as the review numbers them", () => {
    const rows = diffRows(PATCH);
    expect(rows.map((r) => [r.kind, r.old, r.new])).toEqual([
      ["hunk", null, null],
      ["same", 10, 10],
      ["remove", 11, null],
      ["add", null, 11],
      ["add", null, 12],
      ["same", 12, 13],
    ]);
  });
});

describe("the code review's deliverable", () => {
  it("is the repository as it read it, its comments on their lines", async () => {
    runs.forIntention.mockResolvedValue([run()]);
    runs.one.mockResolvedValue(detail());
    show(<DeliverableView intention={INTENTION} />);

    const review = await screen.findByTestId("code-review");
    // Its pull requests: the one reviewed marked, with its comments.
    const pulls = within(review).getAllByTestId("code-review-pull");
    expect(pulls.map((p) => p.dataset.number)).toEqual(["7", "6"]);
    expect(pulls[0]).toHaveAttribute("aria-current", "true");
    expect(pulls[0]).toHaveTextContent("Relue par LEKA · 3 commentaires");
    expect(pulls[1]).toHaveTextContent("Non relue");
    expect(within(review).getByTestId("code-review-verdict")).toHaveTextContent("Prudence");
    expect(within(review).getByTestId("code-review-counts")).toHaveTextContent(
      "1 problème · 1 amélioration proposée · 1 point fort",
    );
    expect(review).toHaveTextContent("1 commentaire écarté");

    // Each under its line: red for what is wrong, green for the rest.
    const [file] = within(review).getAllByTestId("code-review-file");
    const comments = within(file).getAllByTestId("code-review-comment");
    expect(comments.map((c) => [c.dataset.kind, c.dataset.line])).toEqual([
      ["suggestion", undefined],
      ["issue", "12"],
      ["good", "13"],
    ]);
    expect(comments[1]).toHaveTextContent("Problème · élevé");
    expect(comments[1]).toHaveTextContent("pending = account.pending or 0");
    expect(comments[1].className).toContain("bg-state-danger-soft");
    expect(comments[2].className).toContain("bg-state-success-soft");
    expect(comments[0]).toHaveTextContent("sur tout le fichier");
    // The issue sits right under line 12 of the new file.
    const line = within(file).getByText("return total - pending").closest("tr");
    expect(line?.dataset.new).toBe("12");
    expect(line?.nextElementSibling).toHaveTextContent("Pending peut être nul");

    // Its report, one tab away.
    await userEvent.setup().click(screen.getByTestId("deliverable-tab-report"));
    expect(screen.getByTestId("deliverable-report")).toHaveTextContent("Le solde change.");
  });

  it("says an agent at work, no deliverable yet", async () => {
    runs.forIntention.mockResolvedValue([run({ status: "running", finished_at: null })]);
    show(<DeliverableView intention={INTENTION} />);
    expect(await screen.findByTestId("deliverable-waiting")).toHaveTextContent(
      "Revue de code travaille : son livrable s'affichera ici dès qu'il aura terminé.",
    );
    expect(runs.one).not.toHaveBeenCalled();
  });

  it("says why its change is missing, and writes it again on asking", async () => {
    // 2026-10-18: the change not written, the analysis alone was shown.
    runs.forIntention.mockResolvedValue([run({ key: "code-change", title: "Modification de code" })]);
    runs.one.mockResolvedValue(
      detail({ key: "code-change", title: "Modification de code", review: null, draw_failed: "edits_not_applied" }),
    );
    runs.rewriteChange.mockResolvedValue(run({ key: "code-change" }));
    show(<DeliverableView intention={INTENTION} />);
    const missing = await screen.findByTestId("deliverable-change-missing");
    expect(missing).toHaveTextContent("LEKA n'a pas pu écrire le changement");
    expect(missing).toHaveTextContent("le texte à remplacer n'a pas été retrouvé dans le fichier");
    await userEvent.click(within(missing).getByRole("button", { name: "Réessayer d'écrire le changement" }));
    expect(runs.rewriteChange).toHaveBeenCalledWith("r1");
  });

  it("says its change is being written", async () => {
    runs.forIntention.mockResolvedValue([run({ key: "code-change", title: "Modification de code" })]);
    runs.one.mockResolvedValue(
      detail({ key: "code-change", title: "Modification de code", review: null, drawing: ["change"] }),
    );
    show(<DeliverableView intention={INTENTION} />);
    expect(await screen.findByTestId("deliverable-change-writing")).toHaveTextContent("LEKA écrit le changement");
    // Not the deck's « being drawn ».
    expect(screen.queryByTestId("deliverable-drawing")).toBeNull();
  });

  it("is the change it proposed first, before and after side by side, when it proposed one", async () => {
    runs.forIntention.mockResolvedValue([run({ key: "code-change", title: "Modification de code" })]);
    runs.one.mockResolvedValue(detail({ key: "code-change", title: "Modification de code", review: null }));
    changes.forRun.mockResolvedValue([
      {
        id: "c1",
        run_id: "r1",
        intention_id: "i1",
        repository: "acme/payments",
        base_branch: "main",
        title: "Déduire les paiements en attente",
        summary: "Le solde ignorait les paiements en attente.",
        status: "proposed",
        files: [
          {
            path: "app/balance.py",
            status: "modified",
            additions: 2,
            deletions: 1,
            why: "Le calcul du solde",
            diff: `--- a/app/balance.py\n+++ b/app/balance.py\n${PATCH}\n`,
          },
        ],
        pull_requests_allowed: true,
        error: null,
        error_detail: null,
        note: null,
        pull_request_url: null,
        pull_request_number: null,
        created_at: new Date().toISOString(),
        decided_at: null,
      },
    ]);
    show(<DeliverableView intention={INTENTION} />);
    const split = await screen.findByTestId("code-change-split");
    expect(changes.forRun).toHaveBeenCalledWith("r1");
    expect(screen.getByTestId("deliverable-tab-change")).toHaveAttribute("aria-selected", "true");
    expect(split.querySelector('[data-change="remove"]')?.textContent).toBe("    return total");
    expect(screen.getByRole("button", { name: "J'accepte d'appliquer ce changement sur GitHub" })).toBeEnabled();
    // Its report, one tab away.
    await userEvent.setup().click(screen.getByTestId("deliverable-tab-report"));
    expect(screen.getByTestId("deliverable-report")).toHaveTextContent("Le solde change.");
  });

  it("is any agent's report when it read no code", async () => {
    runs.forIntention.mockResolvedValue([run({ key: "security-review", title: "Revue de sécurité" })]);
    runs.one.mockResolvedValue(detail({ key: "security-review", title: "Revue de sécurité", review: null }));
    show(<DeliverableView intention={INTENTION} />);
    expect(await screen.findByTestId("deliverable-report")).toHaveTextContent("Le solde change.");
    expect(screen.queryByTestId("code-review")).toBeNull();
    // Sent out of it, when a person asks: tickets for Jira, pages for Confluence.
    const out = screen.getByTestId("publications");
    expect(within(out).getByRole("button", { name: "Proposer des tickets Jira" })).toBeVisible();
    expect(within(out).getByRole("button", { name: "Documenter sur Confluence" })).toBeVisible();
    expect(sent.forRun).toHaveBeenCalledWith("r1");
  });
});

describe("a review's fix", () => {
  it("asks the code-change agent from the review, on its repository, and opens its deliverable", async () => {
    runs.forIntention.mockResolvedValue([run()]);
    runs.one.mockResolvedValue(detail());
    runs.start.mockResolvedValue(run({ id: "r2", key: "code-change", status: "queued" }));
    show(<DeliverableView intention={INTENTION} />);
    await userEvent.click(await screen.findByRole("button", { name: "Proposer la correction" }));
    const form = screen.getByRole("form", { name: "Corriger ce que la revue a trouvé" });
    expect(within(form).getByLabelText("Dépôt GitHub")).toHaveValue("acme/payments");
    await userEvent.click(within(form).getByRole("button", { name: "Lancer la correction" }));
    await vi.waitFor(() => expect(runs.start).toHaveBeenCalledTimes(1));
    const [asked] = runs.start.mock.calls[0];
    expect(asked).toMatchObject({ key: "code-change", intention_id: "i1", inputs: { depot: "acme/payments" } });
    expect(asked.inputs.demande).toContain("Corrige les constats bloquants et importants");
    expect(asked.inputs.demande).toContain("Le solde change.");
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/intentions/i1/deliverable?run=r2"));
  });

  it("is not offered for a report that reviewed no code", async () => {
    runs.forIntention.mockResolvedValue([run({ key: "security-review", title: "Revue de sécurité" })]);
    runs.one.mockResolvedValue(detail({ key: "security-review", title: "Revue de sécurité", review: null }));
    show(<DeliverableView intention={INTENTION} />);
    await screen.findByTestId("deliverable-report");
    expect(screen.queryByRole("button", { name: "Proposer la correction" })).toBeNull();
  });
});

describe("the agent block of an intention", () => {
  it("leads to what it delivered", async () => {
    runs.forIntention.mockResolvedValue([run()]);
    show(<AgentWork intentionId="i1" />);
    expect(await screen.findByTestId("agent-work-open")).toHaveAttribute(
      "href",
      "/intentions/i1/deliverable?run=r1",
    );
    expect(screen.getByTestId("agent-work-open")).toHaveTextContent("Ouvrir la revue sur le code");
  });
});
