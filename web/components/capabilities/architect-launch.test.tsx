/**
 * The architect on a Confluence space (2026-10-25): « Lancer » and
 * « Arborescence ».
 *
 * What these protect: each space a Confluence source synced, how many pages
 * and how deep; a page and everything under it, or the whole space; the
 * subject and the perimeter filled from the space, changed at will; then an
 * intention asked in the architect's words and the architect started on it
 * — its space, its root page —, the intention's deliverable opened. No
 * Confluence: connect it first. The tree, parent and child, each page a
 * link to Confluence.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const fetched = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
const search = vi.hoisted(() => ({ value: "" }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  apiFetch: fetched,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(search.value),
  usePathname: () => "/architecte",
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { ArchitectLaunch } = await import("@/components/capabilities/architect-launch");
const { SourceTreeSection } = await import("@/components/sources/source-tree");

const CONFLUENCE = { id: "c1", type: "confluence", display_name: "Confluence de l'organisation", status: "active" };
const TREE = {
  source_id: "c1",
  spaces: [
    {
      key: "ARCHI",
      name: "Architecture",
      url: null,
      pages: 4,
      depth: 3,
      nodes: [
        {
          id: "100",
          title: "Accueil",
          url: "https://acme.atlassian.net/wiki/spaces/ARCHI/pages/100",
          children: [
            { id: "101", title: "Applications", url: null, children: [{ id: "102", title: "Billing API", children: [] }] },
            { id: "103", title: "Infrastructure", children: [] },
          ],
        },
      ],
    },
    { key: "OTHER", name: "Autre", url: null, pages: 1, depth: 1, nodes: [{ id: "200", title: "Ailleurs", children: [] }] },
  ],
};

function answers(sources: object[]) {
  fetched.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith("/sources?")) return { data: sources };
    if (path === "/sources/c1/tree") return TREE;
    if (path === "/intentions" && init?.method === "POST") return { intention: { id: "i1" }, context: {} };
    if (path === "/agent-runs" && init?.method === "POST") return { id: "r1" };
    throw new Error(`unexpected ${path}`);
  });
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
  search.value = "";
  answers([CONFLUENCE]);
});

describe("« Lancer » the architect", () => {
  it("its perimeter chosen — a space, a page and what is under it — then asked and started", async () => {
    const user = userEvent.setup();
    show(<ArchitectLaunch />);
    const spaces = await screen.findAllByTestId("architect-space");
    expect(spaces.map((s) => s.dataset.key)).toEqual(["ARCHI", "OTHER"]);
    expect(spaces[0]).toHaveTextContent("4 pages · profondeur 3");
    expect(screen.getByTestId("architect-subject")).toHaveValue("Architecture");
    expect(screen.getByTestId("architect-perimeter")).toHaveValue("Espace Architecture");
    const roots = within(screen.getByTestId("architect-root")).getAllByRole("option");
    expect(roots.map((o) => o.textContent?.replace(/ /g, " ").trim())).toEqual([
      "Tout l'espace",
      "Accueil",
      "└ Applications",
      "└ Billing API",
      "└ Infrastructure",
    ]);
    await user.selectOptions(screen.getByTestId("architect-root"), "101");
    await user.clear(screen.getByTestId("architect-subject"));
    await user.type(screen.getByTestId("architect-subject"), "Facturation");
    await user.click(screen.getByTestId("architect-launch-submit"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/intentions/i1/deliverable?run=r1"));
    const [, asked] = fetched.mock.calls.find(([path, init]) => path === "/intentions" && init?.method === "POST")!;
    expect(JSON.parse(asked.body).text).toBe(
      "/architecte Dossier d'architecture : Facturation, espace ARCHI, page « Applications »",
    );
    const [, started] = fetched.mock.calls.find(([path]) => path === "/agent-runs")!;
    expect(JSON.parse(started.body)).toEqual({
      key: "application-architecture",
      inputs: { parcours: "Facturation", perimetre: "Espace Architecture", espace: "ARCHI", page_racine: "101" },
      intention_id: "i1",
    });
    expect(screen.getByText("Lecture seule : rien n'est écrit dans Confluence.")).toBeInTheDocument();
  });

  it("a space asked by the address, chosen at once", async () => {
    search.value = "source=c1&space=OTHER";
    show(<ArchitectLaunch />);
    await screen.findAllByTestId("architect-space");
    expect(screen.getByRole("radio", { name: /Autre/ })).toBeChecked();
    expect(screen.getByTestId("architect-subject")).toHaveValue("Autre");
  });

  it("no Confluence: connect it first", async () => {
    answers([{ ...CONFLUENCE, id: "g1", type: "github" }]);
    show(<ArchitectLaunch />);
    const none = await screen.findByTestId("architect-no-source");
    expect(within(none).getByRole("link", { name: /Connecter Confluence/ })).toHaveAttribute(
      "href",
      "/sources?connect=confluence",
    );
    expect(screen.queryByTestId("architect-launch-submit")).not.toBeInTheDocument();
  });
});

describe("« Arborescence »", () => {
  it("each space synced, parent and child, each page a link — the space's dossier one click away", async () => {
    show(<SourceTreeSection source={CONFLUENCE as never} />);
    const spaces = await screen.findAllByTestId("tree-space");
    expect(spaces[0]).toHaveTextContent("Architecture (ARCHI)");
    expect(within(spaces[0]).getByTestId("tree-space-counts")).toHaveTextContent("4 pages · profondeur 3");
    const pages = within(spaces[0]).getAllByTestId("tree-page");
    expect(pages.map((p) => p.dataset.depth)).toEqual(["0", "1", "2", "1"]);
    expect(within(spaces[0]).getByRole("link", { name: /Accueil/ })).toHaveAttribute(
      "href",
      "https://acme.atlassian.net/wiki/spaces/ARCHI/pages/100",
    );
    expect(within(spaces[0]).getByTestId("tree-space-document")).toHaveAttribute(
      "href",
      "/architecte?source=c1&space=ARCHI",
    );
  });

  it("a source that is not Confluence has none", () => {
    const { container } = show(<SourceTreeSection source={{ ...CONFLUENCE, type: "github" } as never} />);
    expect(container).toBeEmptyDOMElement();
  });
});
