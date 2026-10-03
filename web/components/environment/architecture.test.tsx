/**
 * The architecture (LEKA-369): what the company runs, in columns, as
 * Haitam's mockup draws it — and every word of it the API's.
 *
 * What these protect: the figures above — how many of each kind, how they
 * are doing, in shares; each column with its cards, each card's kind and
 * state in words, the API chosen first and its panel saying why its state
 * is deduced; another card chosen, its relations named from its side, a
 * database's tables one click away; every link in words; the widgets under
 * the canvas; nothing connected, a screen that says what to connect. And
 * what the canvas draws: a column's links alike as one arrow, the chosen
 * card's own over them.
 *
 * jsdom has no layout: the arrows are read from what the canvas asks to
 * draw (arrowsOf), the rest from the page.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  API,
  ARCHITECTURE,
  BOX,
  CADDY,
  NOTHING,
  POSTGRES,
  RDS,
  REPO,
  WEB,
  WORKER,
} from "@/components/environment/architecture.test-data";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = { get: vi.fn(), sheet: vi.fn() };

vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: api,
}));

const { ArchitectureBoard, ArchitectureFigures, arrowsOf } = await import(
  "@/components/environment/architecture"
);

function mount(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

const byId = new Map(ARCHITECTURE.cards.map((card) => [card.id, card]));

const toBox = (from: string) => ({
  from_id: from,
  column: "cloud",
  role: "deployed_on",
  roles: ["deployed_on"],
  targets: [BOX],
});
const CADDY_TO_BOX = toBox(CADDY);
const WEB_TO_BOX = toBox(WEB);
const WORKER_TO_BOX = toBox(WORKER);

beforeEach(() => {
  vi.clearAllMocks();
  api.sheet.mockResolvedValue({ events: [] });
});

describe("the figures", () => {
  it("count each kind and say how things are doing, in shares", () => {
    mount(<ArchitectureFigures data={ARCHITECTURE} />);

    const tile = (id: string) => within(screen.getByTestId(`arch-figure-${id}`));
    expect(tile("services").getByText("4")).toBeInTheDocument();
    expect(tile("repositories").getByText("Repositories")).toBeInTheDocument();
    // One provider: its resources by its name.
    expect(tile("cloud").getByText("Ressources AWS")).toBeInTheDocument();
    expect(tile("teams").getByText("0")).toBeInTheDocument();
    const health = within(screen.getByTestId("arch-figure-health"));
    expect(health.getByText("En bonne santé")).toBeInTheDocument();
    expect(health.getByText(/75\s%/)).toBeInTheDocument();
    expect(health.getAllByText(/13\s%/)).toHaveLength(2);
  });

  it("say nothing they do not know", () => {
    mount(<ArchitectureFigures data={undefined} />);

    const services = within(screen.getByTestId("arch-figure-services"));
    expect(services.getByText("—")).toBeInTheDocument();
  });
});

describe("the board", () => {
  it("draws each column, each card's kind and state in words, the API chosen first", () => {
    mount(<ArchitectureBoard data={ARCHITECTURE} events={[]} />);

    const column = (name: string) => within(screen.getByTestId(`arch-column-${name}`));
    expect(column("code").getByText("GitHub")).toBeInTheDocument();
    expect(column("code").getByText("1 dépôt(s)")).toBeInTheDocument();
    expect(column("cloud").getByText("AWS (eu-central-1)")).toBeInTheDocument();
    expect(column("services").getByText("Applications & Services")).toBeInTheDocument();
    // A repository by its own name, its owner under it.
    expect(
      column("code").getByRole("button", { name: "Leka, Dépôt de code" }),
    ).toBeInTheDocument();
    expect(column("code").getByText("Haitam-elh")).toBeInTheDocument();
    expect(
      column("services").getByRole("button", { name: "Leka Worker, Tâches de fond, Incident" }),
    ).toBeInTheDocument();
    expect(
      column("cloud").getByRole("button", {
        name: "leka-prod, EC2 · Machine virtuelle, En bonne santé",
      }),
    ).toBeInTheDocument();
    const api = column("services").getByRole("button", {
      name: "Leka API, Backend, En bonne santé (Déduit)",
    });
    expect(api).toHaveAttribute("aria-pressed", "true");

    const panel = within(screen.getByTestId("architecture-panel"));
    expect(panel.getByRole("heading", { name: "Leka API" })).toBeInTheDocument();
    // Why it is said healthy, in the screen's words: what runs it, its last deployment.
    expect(panel.getByTestId("architecture-health")).toHaveTextContent(
      "Déduit de leka-prod (EC2 · Machine virtuelle) : En bonne santé · dernier déploiement réussi",
    );
    expect(panel.getByText("Disponibilité : non mesurée")).toBeInTheDocument();
    expect(panel.getByText("Python · FastAPI")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: "Haitam-elh/Leka" })).toBeInTheDocument();
    expect(panel.getByRole("link", { name: "https://api.leka-core.com" })).toBeInTheDocument();
    expect(panel.getByText("Aucune équipe connue")).toBeInTheDocument();
    expect(panel.getByText("deploy/docker-compose.production.yml:24 — api")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: /Ouvrir la fiche/ })).toHaveAttribute(
      "href",
      `/environment/services/${API}`,
    );
  });

  it("names another card's relations from its side, leads to a database's tables", async () => {
    const user = userEvent.setup();
    mount(<ArchitectureBoard data={ARCHITECTURE} events={[]} />);

    await user.click(screen.getByRole("button", { name: /^PostgreSQL, Base de données/ }));
    const panel = within(screen.getByTestId("architecture-panel"));
    expect(panel.getByText("36 table(s) · 2,3 Mo")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: /Voir ses tables/ })).toHaveAttribute(
      "href",
      `/environment/graph?entity=${POSTGRES}`,
    );

    await user.click(panel.getByTestId("architecture-panel-relations"));
    const rows = within(panel.getByTestId("architecture-relations")).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/^Stockage de.*Leka API/),
      expect.stringMatching(/^Stockage de.*Leka Worker/),
      expect.stringMatching(/^Hébergé surdéduit par LEKA.*leka/),
    ]);
    // A relation is a way to the other card.
    await user.click(within(rows[2]).getByRole("button"));
    const chosen = within(screen.getByTestId("architecture-panel"));
    expect(chosen.getByRole("heading")).toHaveTextContent("leka");

    await user.click(screen.getByRole("button", { name: "Fermer le détail" }));
    expect(screen.queryByTestId("architecture-panel")).not.toBeInTheDocument();
  });

  it("says every link in words", () => {
    mount(<ArchitectureBoard data={ARCHITECTURE} events={[]} />);

    const words = within(screen.getByTestId("architecture-text"));
    expect(words.getByText("Leka Web appelle Leka API")).toBeInTheDocument();
    expect(words.getByText("Leka est le code de Leka API")).toBeInTheDocument();
    expect(words.getByText(/^Leka API est déployé sur leka-prod/)).toHaveTextContent(
      "(déduit par LEKA)",
    );
  });

  it("puts the widgets under the canvas: states, kinds, what moved, the most relied on", () => {
    mount(
      <ArchitectureBoard
        data={ARCHITECTURE}
        events={[
          {
            key: "e1",
            at: new Date().toISOString(),
            tone: "change",
            pill: "Changement",
            title: "main to production",
            where: "Haitam-elh/Leka",
          },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "4 services" })).toBeInTheDocument();
    const kinds = within(screen.getByTestId("architecture-types"));
    expect(kinds.getByText("Tables")).toBeInTheDocument();
    expect(kinds.getByText("36")).toBeInTheDocument();
    expect(screen.getByText("main to production")).toBeInTheDocument();
    const top = within(screen.getByTestId("architecture-top"));
    expect(top.getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "leka-prod2",
      "PostgreSQL2",
    ]);
  });

  it("says what to connect when nothing is known", () => {
    mount(<ArchitectureBoard data={NOTHING} events={[]} />);

    expect(screen.getByText("Votre architecture n'est pas encore connue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connecter" })).toHaveAttribute("href", "/sources");
    expect(screen.queryByTestId("architecture")).not.toBeInTheDocument();
  });

  it("draws the detailed map's cards without the widgets", () => {
    mount(<ArchitectureBoard data={ARCHITECTURE} detailed />);

    expect(screen.getByTestId("architecture")).toBeInTheDocument();
    expect(screen.queryByTestId("architecture-types")).not.toBeInTheDocument();
  });
});

describe("what the canvas draws", () => {
  const ends = (arrows: ReturnType<typeof arrowsOf>) =>
    arrows.map((arrow) => [
      "card" in arrow.from ? arrow.from.card : `panel:${arrow.from.panel}`,
      "card" in arrow.to ? arrow.to.card : `panel:${arrow.to.panel}`,
      arrow.role,
      arrow.own,
    ]);

  it("at rest, a card's links to a column as one arrow, the column's own links each", () => {
    const drawn = ends(arrowsOf(ARCHITECTURE, byId, null, false));

    // Two stores of the API's: to the column, named by what most of them are.
    expect(drawn).toContainEqual([API, "panel:data", "stores", false]);
    // One machine: to it.
    expect(drawn).toContainEqual([API, BOX, "deployed_on", false]);
    expect(drawn).toContainEqual([REPO, API, "source_code", false]);
    expect(drawn).toContainEqual([POSTGRES, RDS, "hosted_on", false]);
    expect(drawn.filter(([, , , own]) => own)).toEqual([]);
  });

  it("the chosen card's own links over the rest, alike ones together", () => {
    const drawn = ends(arrowsOf(ARCHITECTURE, byId, API, false));

    // To the data, two different things: one arrow to the column.
    expect(drawn).toContainEqual([API, "panel:data", "stores", true]);
    expect(drawn).toContainEqual([API, BOX, "deployed_on", true]);
    expect(drawn).toContainEqual([WEB, API, "calls", true]);
    const own = arrowsOf(ARCHITECTURE, byId, API, false).find(
      (arrow) => "panel" in arrow.to && arrow.own,
    );
    expect(own?.roles).toEqual(["stores", "queue"]);
  });

  it("on the detailed map, every card its own arrows", () => {
    const shared = {
      ...ARCHITECTURE,
      bundles: [CADDY_TO_BOX, WEB_TO_BOX, WORKER_TO_BOX],
    };
    const drawn = ends(arrowsOf(shared, byId, null, true));

    expect(drawn.filter(([, to]) => to === BOX)).toHaveLength(3);
    expect(ends(arrowsOf(shared, byId, null, false))).toContainEqual([
      "panel:services",
      BOX,
      "deployed_on",
      false,
    ]);
  });
});
