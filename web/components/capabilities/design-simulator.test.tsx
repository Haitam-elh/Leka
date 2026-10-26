/**
 * The designer's simulator: the screen as its code draws it today, beside
 * what it proposes.
 *
 * What these protect: each mock-up is shown in a frame sandboxed with no
 * permission at all — its page as the API gives it, nothing added; side by
 * side by default, today's screen and the recommended proposal, said
 * recommended; another proposal chosen is the one shown, its axis, when to
 * choose it and what it costs said, and why the recommended one only with
 * it; one at a time, today's or the proposal; drawn at a desktop's, a
 * tablet's or a phone's width — a phone first when the proposal is for one;
 * a design that cannot be read says so. A part of a mock-up is corrected on
 * asking — what, and on which mock-up —, said while it is, read again once
 * it is, kept as a history (2026-10-19, Karim). A capture is drawn from the page as
 * an SVG picture: its styles and its body, `body` read as the box that holds
 * them, nothing that runs.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Design } from "@/lib/agent-runs";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ design: vi.fn(), one: vi.fn(), correctDesign: vi.fn() }));

vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: api,
}));

const { DesignSimulator, svgOf, VIEWPORTS } = await import("@/components/capabilities/design-simulator");

const page = (title: string) =>
  `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'"><style>body { margin: 0; } h1 { color: #1e1b4b; }</style></head><body class="home"><h1>${title}</h1></body></html>`;

const DESIGN: Design = {
  screen: "Accueil",
  viewport: "desktop",
  before: { name: "Aujourd'hui", axis: "", when: "", cost: "", page: page("Avant") },
  after: [
    { name: "Calme", axis: "Une seule action principale", when: "Un outil de tous les jours", cost: "Moins dense", page: page("Calme") },
    { name: "Dense", axis: "Tout sous les yeux", when: "Des experts", cost: "Plus chargé", page: page("Dense") },
  ],
  recommended: 0,
  why: "L'écran est vu cent fois par jour : sobre.",
  changes: [{ where: "web/app/page.tsx:12", before: "Trois boutons", after: "Une action", why: "Une action principale" }],
};

function show(design: Partial<Design> = {}) {
  api.design.mockResolvedValue({ ...DESIGN, ...design });
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <DesignSimulator runId="run-1" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function frames(): HTMLIFrameElement[] {
  return screen.getAllByTestId("design-frame").map((f) => f.querySelector("iframe") as HTMLIFrameElement);
}

beforeEach(() => vi.clearAllMocks());

describe("the designer's simulator", () => {
  it("shows today's screen beside the recommended proposal, each sandboxed with no permission", async () => {
    show();
    await screen.findByTestId("design-simulator");
    expect(api.design).toHaveBeenCalledWith("run-1");
    const [before, after] = frames();
    for (const frame of [before, after]) {
      expect(frame.getAttribute("sandbox")).toBe("");
      expect(frame.style.width).toBe(`${VIEWPORTS.desktop.width}px`);
    }
    expect(before.getAttribute("srcdoc")).toBe(page("Avant"));
    expect(after.getAttribute("srcdoc")).toBe(page("Calme"));
    const calm = screen.getAllByTestId("design-proposal")[0];
    expect(calm).toHaveAttribute("aria-pressed", "true");
    expect(within(calm).getByTestId("design-recommended")).toBeInTheDocument();
    expect(screen.getByTestId("design-why")).toHaveTextContent("cent fois par jour");
    expect(screen.getByTestId("design-changes")).toHaveTextContent("web/app/page.tsx:12");
  });

  it("shows another proposal when chosen, with its axis, when and cost — and why only for the recommended", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByTestId("design-simulator");
    await user.click(screen.getAllByTestId("design-proposal")[1]);
    expect(frames()[1].getAttribute("srcdoc")).toBe(page("Dense"));
    const detail = screen.getByTestId("design-proposal-detail");
    expect(detail).toHaveTextContent("Tout sous les yeux");
    expect(detail).toHaveTextContent("Des experts");
    expect(detail).toHaveTextContent("Plus chargé");
    expect(screen.queryByTestId("design-why")).not.toBeInTheDocument();
    expect(screen.queryByTestId("design-changes")).not.toBeInTheDocument();
  });

  it("shows one at a time, today's or the proposal", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByTestId("design-simulator");
    await user.click(screen.getByTestId("design-single"));
    expect(frames()).toHaveLength(1);
    expect(frames()[0].getAttribute("srcdoc")).toBe(page("Calme"));
    await user.click(screen.getByTestId("design-show-before"));
    expect(frames()[0].getAttribute("srcdoc")).toBe(page("Avant"));
  });

  it("draws at a desktop's, a tablet's or a phone's width — a phone first for a phone's proposal", async () => {
    const user = userEvent.setup();
    show({ viewport: "mobile" });
    await screen.findByTestId("design-simulator");
    expect(screen.getAllByTestId("design-frame")[0]).toHaveAttribute("data-viewport", "phone");
    expect(frames()[0].style.width).toBe(`${VIEWPORTS.phone.width}px`);
    await user.click(screen.getByTestId("design-viewport-tablet"));
    expect(frames()[0].style.width).toBe(`${VIEWPORTS.tablet.width}px`);
    expect(screen.getByTestId("design-viewport-tablet")).toHaveAttribute("aria-pressed", "true");
  });

  it("says when the design cannot be read", async () => {
    api.design.mockRejectedValue(new Error("gone"));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <LocaleProvider>
          <DesignSimulator runId="run-1" />
        </LocaleProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("design-error")).toBeInTheDocument();
  });
});

describe("a correction asked of a mock-up", () => {
  it("is asked in words on the proposal shown, said while LEKA draws it, then read again", async () => {
    const run = { id: "run-1", status: "succeeded", drawing: [], correcting: null, corrections: [] };
    api.one.mockResolvedValue(run);
    api.correctDesign.mockResolvedValue({ ...run, correcting: "0" });
    show();
    const box = await screen.findByTestId("design-correction");
    await userEvent.click(within(box).getByRole("button", { name: "Demander une correction" }));
    await userEvent.type(within(box).getByLabelText("Que faut-il corriger ?"), "Le logo n'est pas le bon");
    // On the proposal shown — the recommended one — by default.
    expect(within(box).getByLabelText("Sur la maquette")).toHaveValue("0");
    api.one.mockResolvedValue({ ...run, correcting: "0" });
    await userEvent.click(within(box).getByRole("button", { name: "Corriger cette maquette" }));
    expect(api.correctDesign).toHaveBeenCalledWith("run-1", "0", "Le logo n'est pas le bon");
    expect(await screen.findByTestId("design-correcting")).toHaveTextContent("LEKA corrige « Calme »");
    // Corrected: the mock-ups read again, the correction kept.
    api.one.mockResolvedValue({
      ...run,
      corrections: [{ target: "0", note: "Le logo n'est pas le bon", at: "2026-10-19T21:30:00Z" }],
    });
    await waitFor(() => expect(screen.getByTestId("design-corrections")).toHaveTextContent(
      "Corrigée · Calme : « Le logo n'est pas le bon »",
    ), { timeout: 6000 });
    await waitFor(() => expect(api.design.mock.calls.length).toBeGreaterThan(1));
  }, 10_000);
});

describe("a capture, drawn from the page", () => {
  it("holds its styles and body as a picture, body read as its box, nothing that runs", () => {
    const svg = svgOf(page("Calme"), 390, 844);
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" width="390" height="844">')).toBe(true);
    expect(svg).toContain("<foreignObject");
    expect(svg).toContain(".leka-page { margin: 0; }");
    expect(svg).toContain("h1 { color: #1e1b4b; }");
    expect(svg).toContain('class="leka-page home"');
    expect(svg).toContain("Calme</h1>");
    expect(svg).not.toContain("<script");
    expect(svg).not.toContain("Content-Security-Policy");
  });
});
