/**
 * What the code-change agent proposed, on its intention.
 *
 * What these protect: each file's diff, its lines told apart — added,
 * removed, a hunk; accepting is offered only when its GitHub source allows
 * pull requests, and says how to allow it otherwise; rejecting sends the
 * comment; an applied change links to its pull request.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CodeChange } from "@/lib/code-changes";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import { splitRows } from "@/lib/diff";

const api = vi.hoisted(() => ({ list: vi.fn(), accept: vi.fn(), reject: vi.fn() }));
vi.mock("@/lib/code-changes", async (original) => ({
  ...(await original<typeof import("@/lib/code-changes")>()),
  codeChanges: api,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { CodeChanges, diffLines } = await import("@/components/capabilities/code-changes");

const DIFF =
  "--- a/app/balance.py\n+++ b/app/balance.py\n@@ -1,2 +1,2 @@\n def balance(account):\n-    return account.total\n+    return account.total - account.pending\n";

function change(overrides: Partial<CodeChange> = {}): CodeChange {
  return {
    id: "c1",
    run_id: "r1",
    intention_id: "i1",
    repository: "acme/payments",
    base_branch: "main",
    title: "Déduire les paiements en attente du solde",
    summary: "Le solde ignore les paiements en attente.",
    status: "proposed",
    files: [
      { path: "app/balance.py", status: "modified", additions: 1, deletions: 1, diff: DIFF, why: "le calcul" },
    ],
    pull_requests_allowed: true,
    proposed_by: null,
    decided_by: null,
    decided_at: null,
    note: null,
    branch: null,
    pull_request_number: null,
    pull_request_url: null,
    error: null,
    error_detail: null,
    created_at: "2026-10-10T20:00:00Z",
    ...overrides,
  };
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <CodeChanges intentionId="i1" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("a proposed code change", () => {
  it("tells a diff's lines apart", () => {
    expect(diffLines(DIFF).map((l) => l.kind)).toEqual(["meta", "meta", "hunk", "same", "remove", "add"]);
  });

  it("lays a diff out as two pages, numbered as in each file", () => {
    const rows = splitRows(
      "--- a/x.py\n+++ b/x.py\n@@ -10,3 +10,4 @@ def f():\n a = 1\n-b = 2\n+b = 3\n+c = 4\n d = 5\n",
    );
    expect(rows[0]).toEqual({ kind: "hunk", text: "@@ -10,3 +10,4 @@ def f():" });
    expect(rows.slice(1)).toEqual([
      { kind: "pair", left: { number: 10, text: "a = 1", change: "same" }, right: { number: 10, text: "a = 1", change: "same" } },
      { kind: "pair", left: { number: 11, text: "b = 2", change: "remove" }, right: { number: 11, text: "b = 3", change: "add" } },
      { kind: "pair", left: null, right: { number: 12, text: "c = 4", change: "add" } },
      { kind: "pair", left: { number: 12, text: "d = 5", change: "same" }, right: { number: 13, text: "d = 5", change: "same" } },
    ]);
    // A new file: nothing on the left; a removed line starting with "--" stays a line.
    const created = splitRows("--- /dev/null\n+++ b/n.sql\n@@ -0,0 +1,1 @@\n+-- a comment\n");
    expect(created[1]).toEqual({ kind: "pair", left: null, right: { number: 1, text: "-- a comment", change: "add" } });
  });

  it("shows its diff, and accepts it as a pull request", async () => {
    api.list.mockResolvedValue([change()]);
    api.accept.mockResolvedValue(change({ status: "applied", pull_request_number: 7 }));
    const user = userEvent.setup();
    show();
    const card = await screen.findByTestId("code-change");
    expect(card).toHaveTextContent("acme/payments · branche main · 1 fichier · +1 −1");
    // Before and after, side by side, numbered as in the file, its
    // indentation kept, as code.
    const split = within(card).getByTestId("code-change-split");
    expect(split).toHaveTextContent("Avant");
    expect(split).toHaveTextContent("Après · proposition de LEKA");
    expect(split.querySelector('[data-change="remove"]')?.textContent).toBe("    return account.total");
    expect(split.querySelector('[data-change="add"]')?.textContent).toBe("    return account.total - account.pending");
    // Or as one diff.
    await user.click(within(card).getByTestId("code-change-view-unified"));
    expect(within(card).getByTestId("code-change-diff").querySelector('[data-kind="add"]')?.textContent).toBe(
      "+    return account.total - account.pending",
    );
    await user.type(within(card).getByLabelText("Commentaire (facultatif)"), "OK");
    await user.click(within(card).getByRole("button", { name: "J'accepte d'appliquer ce changement sur GitHub" }));
    await waitFor(() => expect(api.accept).toHaveBeenCalledWith("c1", "OK"));
  });

  it("says how to allow pull requests when its source does not", async () => {
    api.list.mockResolvedValue([change({ pull_requests_allowed: false })]);
    show();
    expect(await screen.findByTestId("code-change-not-allowed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "J'accepte d'appliquer ce changement sur GitHub" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refuser" })).toBeEnabled();
  });

  it("rejects it", async () => {
    api.list.mockResolvedValue([change()]);
    api.reject.mockResolvedValue(change({ status: "rejected" }));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Refuser" }));
    await waitFor(() => expect(api.reject).toHaveBeenCalledWith("c1", undefined));
  });

  it("links an applied change to its pull request", async () => {
    api.list.mockResolvedValue([
      change({ status: "applied", pull_request_number: 7, pull_request_url: "https://github.com/acme/payments/pull/7" }),
    ]);
    show();
    const link = await screen.findByTestId("code-change-pull-request");
    expect(link).toHaveAttribute("href", "https://github.com/acme/payments/pull/7");
    expect(link).toHaveTextContent("Voir la pull request #7 sur GitHub");
    expect(screen.queryByRole("button", { name: "Refuser" })).not.toBeInTheDocument();
  });
});
