/**
 * The demonstration (LEKA-449, LEKA-451): opened in one click, said on
 * every page of it, left for one's own workspace — and offered where a new
 * workspace starts, apart from it inside the demonstration itself.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useContext } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InDemoContext } from "@/components/demo/in-demo";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const api = vi.hoisted(() => ({ openDemo: vi.fn(), enter: vi.fn() }));
vi.mock("@/lib/workspace", () => ({ workspace: api }));
// No plan known: a public one — the demonstration offered (2026-10-25: never under a contract).
vi.mock("@/lib/billing-queries", () => ({ useCredits: () => ({ data: undefined }) }));

const shell = vi.hoisted(() => ({
  current: null as null | { id: string; name: string; slug: string; role: string; demo?: boolean },
  all: [] as { id: string; name: string; slug: string; role: string; demo?: boolean }[],
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => shell.current,
  useWorkspaces: () => shell.all,
}));

const { DemoBanner, ExploreDemoButton } = await import("@/components/demo/demo");

const MINE = { id: "w-1", name: "Acme", slug: "acme", role: "owner" };
const DEMO = { id: "w-demo", name: "Nova Retail (démo)", slug: "nova", role: "owner", demo: true };

function show(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const assign = vi.fn();

beforeEach(() => {
  api.openDemo.mockReset().mockResolvedValue({ workspace: { id: DEMO.id }, created: true });
  api.enter.mockReset().mockResolvedValue({});
  assign.mockReset();
  vi.stubGlobal("location", { ...window.location, assign });
  shell.current = MINE;
  shell.all = [MINE, DEMO];
});

describe("the demonstration", () => {
  it("opens in one click, then the overview drawn again as Nova Retail's", async () => {
    show(<ExploreDemoButton />);
    fireEvent.click(screen.getByRole("button", { name: "Explorer la démo" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/overview"));
    expect(api.openDemo).toHaveBeenCalledWith(false);
  });

  it("says it failed rather than nothing when it cannot open", async () => {
    api.openDemo.mockRejectedValue(new Error("down"));
    show(<ExploreDemoButton />);
    fireEvent.click(screen.getByRole("button", { name: "Explorer la démo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("La démo n'a pas pu s'ouvrir");
    expect(assign).not.toHaveBeenCalled();
  });

  it("is said on every page of it — fictive, reaching nothing — never elsewhere", () => {
    const { unmount } = show(<DemoBanner />);
    expect(screen.queryByTestId("demo-banner")).toBeNull();
    unmount();
    shell.current = DEMO;
    show(<DemoBanner />);
    expect(screen.getByTestId("demo-banner")).toHaveTextContent("données de Nova Retail sont fictives");
    expect(screen.getByTestId("demo-banner")).toHaveTextContent("rien ici n'atteint un vrai outil");
  });

  it("is left for one's own workspace, or to connect one's own tools", async () => {
    shell.current = DEMO;
    show(<DemoBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Quitter la démo" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/overview"));
    expect(api.enter).toHaveBeenCalledWith(MINE.id);
  });

  it("is left to connect one's own tools, in one's own workspace", async () => {
    shell.current = DEMO;
    show(<DemoBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Connecter mes outils" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/welcome"));
  });

  it("starts again from a clean state when asked", async () => {
    shell.current = DEMO;
    show(<DemoBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Recommencer" }));
    await waitFor(() => expect(api.openDemo).toHaveBeenCalledWith(true));
  });

  it("says nothing of itself outside a shell that says it is one", () => {
    let seen: boolean | null = null;
    function Probe() {
      seen = useContext(InDemoContext);
      return null;
    }
    render(<Probe />);
    expect(seen).toBe(false);
  });
});
