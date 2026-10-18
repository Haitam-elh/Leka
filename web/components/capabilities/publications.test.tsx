/**
 * What LEKA proposes to send out of a deliverable: tickets for Jira, pages
 * for Confluence (2026-10-18).
 *
 * What these protect:
 * - Asking: without a connected source, said how to connect one; with one,
 *   its project or space chosen from those it reads — or typed when it
 *   reads them all — and said when its admin has not allowed sending yet.
 * - Proposed: every ticket chosen by default, those drafted after the card
 *   was drawn too; left out one by one, or all; sent with the ones chosen
 *   only; never offered to send when the source does not allow it, said
 *   how to allow it, with a link to the source; refused, said why. A
 *   member drafts; only who may approve sends or rejects, said so.
 * - Sent: each with its link — the issue's key, the page — or why not; the
 *   ones left out said not sent.
 * - Drafting is said; a draft that failed says why.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Publication } from "@/lib/publications";
import { makeQueryClient } from "@/lib/query";
import type { Source } from "@/lib/sources";

const ADMIN = ["intention:read", "intention:create", "intention:approve"];
const shell = vi.hoisted(() => ({ permissions: [] as string[] }));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => shell.permissions }));
const api = vi.hoisted(() => ({ forRun: vi.fn(), ask: vi.fn(), accept: vi.fn(), reject: vi.fn() }));
vi.mock("@/lib/publications", async (original) => ({
  ...(await original<typeof import("@/lib/publications")>()),
  publications: api,
}));
const listed = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: listed,
}));
const notified = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("@/lib/notify", () => ({ notify: notified }));

const { RunPublications } = await import("@/components/capabilities/publications");

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: "s-jira",
    type: "jira",
    display_name: "Jira Acme",
    status: "active",
    config: { site: "acme", projects: ["PAY", "OPS"], issues: false },
    capabilities: [],
    source_metadata: {},
    health_status: "healthy",
    last_health_check_at: null,
    last_error: null,
    sync_status: "idle",
    last_sync_at: null,
    credentials: null,
    created_by: null,
    created_at: "2026-10-18T09:00:00Z",
    updated_at: "2026-10-18T09:00:00Z",
    ...overrides,
  } as Source;
}

function publication(overrides: Partial<Publication> = {}): Publication {
  return {
    id: "p1",
    run_id: "r1",
    intention_id: "i1",
    kind: "issues",
    source_id: "s-jira",
    target: "PAY",
    title: "Les correctifs de la revue",
    summary: "Deux points à corriger avant la mise en production.",
    status: "proposed",
    items: [
      {
        id: "a",
        title: "Déduire les paiements en attente du solde",
        body: "## Contexte\n\nLe solde ignore les paiements en attente.",
        kind: "bug",
        priority: "high",
        labels: ["payments"],
        key: null,
        url: null,
        error: null,
      },
      {
        id: "b",
        title: "Tester le solde avec un paiement en attente",
        body: "- [ ] un test",
        kind: "task",
        priority: "medium",
        labels: [],
        key: null,
        url: null,
        error: null,
      },
    ],
    allowed: true,
    proposed_by: null,
    decided_by: null,
    decided_at: null,
    note: null,
    error: null,
    error_detail: null,
    created_at: "2026-10-18T09:00:00Z",
    ...overrides,
  };
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <RunPublications runId="r1" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  shell.permissions = ADMIN;
  api.forRun.mockResolvedValue([]);
  listed.list.mockResolvedValue({ data: [] });
});

describe("asking LEKA for tickets or pages", () => {
  it("says how to connect a source when there is none", async () => {
    listed.list.mockResolvedValue({ data: [source({ status: "error" })] });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Proposer des tickets Jira" }));
    const none = await screen.findByTestId("publication-no-source");
    expect(none).toHaveTextContent("Aucune source Jira connectée");
    expect(within(none).getByRole("link", { name: "Connecter une source" })).toHaveAttribute("href", "/sources");
  });

  it("drafts for a project the source reads, and says sending waits for its admin", async () => {
    listed.list.mockResolvedValue({ data: [source()] });
    api.ask.mockResolvedValue(publication({ status: "drafting", items: [], title: "" }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Proposer des tickets Jira" }));
    const form = await screen.findByTestId("publication-form");
    const project = within(form).getByTestId("publication-target");
    expect(project).toHaveValue("PAY");
    await userEvent.selectOptions(project, "OPS");
    expect(within(form).getByTestId("publication-form-not-allowed")).toHaveTextContent("Créer les tickets acceptés");
    await userEvent.click(within(form).getByRole("button", { name: "Rédiger les tickets" }));
    await waitFor(() =>
      expect(api.ask).toHaveBeenCalledWith("r1", { kind: "issues", source_id: "s-jira", target: "OPS" }),
    );
    await waitFor(() => expect(screen.queryByTestId("publication-form")).toBeNull());
  });

  it("takes a space typed when the source reads them all", async () => {
    listed.list.mockResolvedValue({
      data: [source({ id: "s-conf", type: "confluence", config: { site: "acme", spaces: null, pages: true } })],
    });
    api.ask.mockResolvedValue(publication({ kind: "pages", status: "drafting", items: [] }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Documenter sur Confluence" }));
    const form = await screen.findByTestId("publication-form");
    expect(within(form).queryByTestId("publication-form-not-allowed")).toBeNull();
    await userEvent.type(within(form).getByTestId("publication-target"), "ARCH");
    await userEvent.click(within(form).getByRole("button", { name: "Rédiger les pages" }));
    await waitFor(() =>
      expect(api.ask).toHaveBeenCalledWith("r1", { kind: "pages", source_id: "s-conf", target: "ARCH" }),
    );
  });

  it("says why it was refused", async () => {
    listed.list.mockResolvedValue({ data: [source()] });
    api.ask.mockRejectedValue(
      new ApiError(422, "/agent-runs/r1/publications", "refused", "validation_failed", { target: "out_of_scope" }),
    );
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Proposer des tickets Jira" }));
    await userEvent.click(await screen.findByRole("button", { name: "Rédiger les tickets" }));
    await waitFor(() =>
      expect(notified.error).toHaveBeenCalledWith({ title: "Ce projet ou cet espace n'est pas lu par la source." }),
    );
    expect(screen.getByTestId("publication-form")).toBeVisible();
  });
});

describe("a proposal", () => {
  it("is drafting, then said why it failed", async () => {
    api.forRun.mockResolvedValue([
      publication({ id: "p1", status: "drafting", items: [], title: "" }),
      publication({ id: "p2", status: "failed", items: [], title: "", error: "no_model" }),
    ]);
    show();
    const [drafting, failed] = await screen.findAllByTestId("publication");
    expect(within(drafting).getByRole("status")).toHaveTextContent("LEKA rédige les tickets");
    expect(within(failed).getByTestId("publication-failed")).toHaveTextContent(
      "Aucun modèle de langage n'est disponible",
    );
  });

  it("sends the tickets chosen, every one by default", async () => {
    api.forRun.mockResolvedValue([publication()]);
    api.accept.mockResolvedValue(
      publication({
        status: "applied",
        items: publication().items.map((item) =>
          item.id === "a" ? { ...item, key: "PAY-24", url: "https://acme.atlassian.net/browse/PAY-24" } : item,
        ),
      }),
    );
    show();
    const card = await screen.findByTestId("publication");
    expect(within(card).getByText("Tickets Jira · projet PAY")).toBeVisible();
    const boxes = within(card).getAllByRole("checkbox");
    expect(boxes.map((box) => (box as HTMLInputElement).checked)).toEqual([true, true]);
    expect(within(card).getByText("2 sur 2 choisis")).toBeVisible();
    expect(within(card).getByText("Bug")).toBeVisible();
    expect(within(card).getByText("Haute")).toBeVisible();

    await userEvent.click(within(card).getByRole("checkbox", { name: "Tester le solde avec un paiement en attente" }));
    expect(within(card).getByText("1 sur 2 choisi")).toBeVisible();
    await userEvent.click(within(card).getByRole("button", { name: "Ajouter à Jira (1)" }));
    await waitFor(() => expect(api.accept).toHaveBeenCalledWith("p1", ["a"], undefined));
    expect(notified.success).toHaveBeenCalledWith({ title: "1 ticket ajouté à Jira" });
  });

  it("chooses none, then all again", async () => {
    api.forRun.mockResolvedValue([publication()]);
    show();
    const card = await screen.findByTestId("publication");
    await userEvent.click(within(card).getByRole("button", { name: "Ne rien choisir" }));
    expect(within(card).getByRole("button", { name: "Ajouter à Jira (0)" })).toBeDisabled();
    await userEvent.click(within(card).getByRole("button", { name: "Tout choisir" }));
    expect(within(card).getByRole("button", { name: "Ajouter à Jira (2)" })).toBeEnabled();
  });

  it("is not sent where the source does not allow it, said how to allow it", async () => {
    api.forRun.mockResolvedValue([publication({ allowed: false })]);
    show();
    const card = await screen.findByTestId("publication");
    expect(within(card).getByRole("button", { name: "Ajouter à Jira (2)" })).toBeDisabled();
    const why = within(card).getByTestId("publication-not-allowed");
    expect(why).toHaveTextContent("Créer les tickets acceptés");
    expect(within(why).getByRole("link", { name: "Ouvrir la source" })).toHaveAttribute("href", "/sources/s-jira");
  });

  it("refused whole by Jira, stays to send again, said why", async () => {
    api.forRun.mockResolvedValue([publication({ error: "not_allowed", error_detail: "403" })]);
    show();
    const card = await screen.findByTestId("publication");
    expect(within(card).getByTestId("publication-error")).toHaveTextContent("Le compte de la source ne peut pas créer ici");
    expect(within(card).getByRole("button", { name: "Ajouter à Jira (2)" })).toBeEnabled();
  });

  it("is sent or rejected only by who may approve, said so", async () => {
    shell.permissions = ["intention:read", "intention:create"];
    api.forRun.mockResolvedValue([publication()]);
    show();
    const card = await screen.findByTestId("publication");
    expect(within(card).getByTestId("publication-approvers")).toHaveTextContent("Un admin de l'espace de travail");
    expect(within(card).getByRole("button", { name: "Ajouter à Jira (2)" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Refuser" })).toBeDisabled();
  });

  it("is rejected on asking", async () => {
    api.forRun.mockResolvedValue([publication()]);
    api.reject.mockResolvedValue(publication({ status: "rejected" }));
    show();
    await userEvent.click(within(await screen.findByTestId("publication")).getByRole("button", { name: "Refuser" }));
    await waitFor(() => expect(api.reject).toHaveBeenCalledWith("p1", undefined));
    expect(notified.success).toHaveBeenCalledWith({ title: "Proposition refusée" });
  });
});

describe("what was sent", () => {
  it("links each ticket or page, says why one was not, and the ones left out", async () => {
    api.forRun.mockResolvedValue([
      publication({
        id: "p1",
        status: "partly",
        items: [
          { ...publication().items[0], key: "PAY-24", url: "https://acme.atlassian.net/browse/PAY-24" },
          { ...publication().items[1], error: "invalid" },
        ],
      }),
      publication({
        id: "p2",
        kind: "pages",
        target: "ARCH",
        status: "applied",
        items: [
          {
            id: "c",
            title: "Architecture des paiements",
            body: "# Paiements",
            labels: [],
            key: "98765",
            url: "https://acme.atlassian.net/wiki/spaces/ARCH/pages/98765",
          },
          { id: "d", title: "Exploitation", body: "# Exploiter", labels: [] },
        ],
      }),
    ]);
    show();
    const [tickets, pages] = await screen.findAllByTestId("publication");
    expect(within(tickets).getByRole("link", { name: "PAY-24 dans Jira" })).toHaveAttribute(
      "href",
      "https://acme.atlassian.net/browse/PAY-24",
    );
    expect(within(tickets).getByTestId("publication-item-error")).toHaveTextContent("Atlassian a refusé le contenu.");
    expect(within(tickets).getByTestId("publication-sent")).toHaveTextContent("1 sur 2 tickets créés dans Jira.");
    expect(within(tickets).queryByRole("checkbox")).toBeNull();
    expect(within(pages).getByText("Pages Confluence · espace ARCH")).toBeVisible();
    expect(within(pages).getByRole("link", { name: "Ouvrir la page" })).toHaveAttribute(
      "href",
      "https://acme.atlassian.net/wiki/spaces/ARCH/pages/98765",
    );
    expect(within(pages).getByText("Non envoyé")).toBeVisible();
  });
});
