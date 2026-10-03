/**
 * The detailed map as a dossier (LEKA-369), after the DSI's architecture
 * prompt: what the company runs in layers, the flows it makes, who answers
 * for what, what to confirm, what it was read from and what is not read.
 *
 * What these protect: its scope said in figures; every card in its layer,
 * every link in words; a flow's steps numbered and named; no name invented
 * — "À confirmer" in orange where no source names a team; each control
 * point in a sentence, an inferred link with its rule and how sure; the
 * sources with when they last read, and the limits — monitoring first when
 * none is connected.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DETAILED, NOTHING } from "@/components/environment/architecture.test-data";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: { get: vi.fn(), sheet: vi.fn().mockResolvedValue({ events: [] }) },
}));

const { ArchitectureDossier } = await import("@/components/environment/architecture-dossier");

function mount(data = DETAILED) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ArchitectureDossier data={data} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

describe("the dossier", () => {
  it("says its scope, and every card in its layer", () => {
    mount();

    expect(screen.getByRole("heading", { name: "Architecture applicative" })).toBeInTheDocument();
    expect(
      screen.getByText(/^Périmètre : 1 dépôt\(s\) · 1 module\(s\) de code · 4 service\(s\)/),
    ).toBeInTheDocument();
    const layer = (name: string) => within(screen.getByTestId(`dossier-layer-${name}`));
    expect(layer("code").getByRole("button", { name: "Leka/api, Backend" })).toBeInTheDocument();
    expect(layer("cloud").getByRole("button", { name: /^leka-prod/ })).toBeInTheDocument();
    expect(layer("external").getByText("OVH (e-mail)")).toBeInTheDocument();
    // Nothing chosen: the layers have the width; a brick chosen, its panel.
    expect(screen.queryByTestId("architecture-panel")).not.toBeInTheDocument();
    const words = within(screen.getByTestId("architecture-text"));
    expect(words.getByText("Leka Web appelle Leka API")).toBeInTheDocument();
  });

  it("opens a brick's panel when it is chosen", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /^Leka API/ }));

    expect(within(screen.getByTestId("architecture-panel")).getByRole("heading")).toHaveTextContent(
      "Leka API",
    );
  });

  it("numbers and names a flow's steps", () => {
    mount();

    const flow = screen.getByTestId("dossier-flow");
    expect(within(flow).getByText("Flux 1 — depuis Leka Caddy")).toBeInTheDocument();
    expect(within(flow).getByText("1. Appelle")).toBeInTheDocument();
    expect(within(flow).getByText("2. Stocke")).toBeInTheDocument();
    expect(within(flow).getByRole("img")).toHaveAccessibleName(
      "Leka Web appelle Leka API ; Leka API stocke ses données dans PostgreSQL ; Leka API met ses tâches en file dans Redis",
    );
  });

  it("invents no name: what no source says is to confirm", () => {
    mount();

    const raci = within(screen.getByTestId("dossier-raci"));
    const api = raci.getByRole("rowheader", { name: "Leka API" }).closest("tr");
    expect(api).toHaveTextContent("Backend");
    expect(api).toHaveTextContent("À confirmer");
    // Modules are the code's: not elements to answer for.
    expect(raci.queryByRole("rowheader", { name: "Leka/api" })).not.toBeInTheDocument();
  });

  it("says each control point in a sentence, the worst first", () => {
    mount();

    const checks = within(screen.getByTestId("dossier-check-list"));
    expect(checks.getByText("En incident (1)")).toBeInTheDocument();
    expect(checks.getByText("Leka Worker est en incident.")).toBeInTheDocument();
    expect(
      checks.getByText("L'état de Leka API est déduit de leka-prod (EC2 · Machine virtuelle)."),
    ).toBeInTheDocument();
    expect(
      checks.getByText(
        "Leka API est déployé sur leka-prod — déduit : même adresse publique (90 %).",
      ),
    ).toBeInTheDocument();
    // What has no team, together.
    expect(checks.getByText("Sans équipe connue (2)")).toBeInTheDocument();
    expect(checks.getByText("Leka API, Leka Web")).toBeInTheDocument();
  });

  it("says what it was read from, and what is not read", () => {
    mount();

    const sources = within(screen.getByTestId("dossier-sources-table"));
    expect(sources.getByRole("rowheader", { name: /GitHub Leka$/ })).toBeInTheDocument();
    expect(sources.getByText("jamais lue")).toBeInTheDocument();
    const limits = within(screen.getByTestId("dossier-limits")).getAllByRole("listitem");
    // No monitoring tool among them: said first.
    expect(limits[0]).toHaveTextContent(/Aucun outil de supervision n'est connecté/);
    const said = limits.map((item) => item.textContent ?? "");
    expect(said.some((limit) => /jamais le code source lui-même/.test(limit))).toBe(true);
  });

  it("says what to connect when nothing is known", () => {
    mount(NOTHING);

    expect(screen.getByText("Votre architecture n'est pas encore connue")).toBeInTheDocument();
    expect(screen.queryByTestId("architecture-dossier")).not.toBeInTheDocument();
  });
});
