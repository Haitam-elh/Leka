/**
 * The architecture (LEKA-369): what the company runs, in columns, as
 * Haitam's mockup draws it — and every word of it the API's.
 *
 * What these protect: the figures above — how many of each kind, how they
 * are doing, in shares; each column with its cards, each card's kind and
 * state in words, the API chosen first and its panel saying why its state
 * is deduced; another card chosen, its relations named from its side, a
 * database's tables one click away; every link in words; nothing
 * connected, a screen that says what to connect. And
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
  API_CODE,
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

  it("count services as the home does, the applications said beside (LEKA-469)", () => {
    mount(
      <ArchitectureFigures
        data={{ ...ARCHITECTURE, figures: { ...ARCHITECTURE.figures, services: 4, applications: 1 } }}
      />,
    );
    const services = within(screen.getByTestId("arch-figure-services"));
    expect(services.getByText("4")).toBeInTheDocument();
    expect(services.getByText("+ 1 application")).toBeInTheDocument();
  });

  it("say nothing they do not know", () => {
    mount(<ArchitectureFigures data={undefined} />);

    const services = within(screen.getByTestId("arch-figure-services"));
    expect(services.getByText("-")).toBeInTheDocument();
  });
});

describe("the board", () => {
  it("opens on no card chosen, its panel closed; a click opens that card's (LEKA-473)", async () => {
    const user = userEvent.setup();
    mount(<ArchitectureBoard data={ARCHITECTURE} />);
    expect(screen.queryByTestId("architecture-panel")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button", { pressed: true })).toHaveLength(0);
    const api = screen.getByRole("button", { name: /^Leka API, Backend/ });
    expect(api).toHaveAttribute("aria-pressed", "false");

    await user.click(api);
    expect(api).toHaveAttribute("aria-pressed", "true");
    expect(
      within(screen.getByTestId("architecture-panel")).getByRole("heading", { name: "Leka API" }),
    ).toBeInTheDocument();

    // Closed, it stays closed — and the next card clicked is the one shown.
    await user.click(screen.getByRole("button", { name: "Fermer le détail" }));
    expect(screen.queryByTestId("architecture-panel")).not.toBeInTheDocument();
    expect(api).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: /^PostgreSQL, Base de données/ }));
    expect(within(screen.getByTestId("architecture-panel")).getByRole("heading")).toHaveTextContent(
      "PostgreSQL",
    );
  });

  it("draws each column, each card's kind and state in words, the API's panel once chosen", async () => {
    const user = userEvent.setup();
    mount(<ArchitectureBoard data={ARCHITECTURE} />);

    const column = (name: string) => within(screen.getByTestId(`arch-column-${name}`));
    expect(column("code").getByText("GitHub")).toBeInTheDocument();
    expect(column("code").getByText("1 dépôt")).toBeInTheDocument();
    expect(column("cloud").getByText("AWS (eu-central-1)")).toBeInTheDocument();
    expect(column("services").getByText("Applications & Services")).toBeInTheDocument();
    // A repository by its own name, its owner under it.
    expect(
      column("code").getByRole("button", { name: "Leka, Dépôt de code" }),
    ).toBeInTheDocument();
    expect(
      column("code").getByText("Haitam-elh · 247 commits · 12 pull requests"),
    ).toBeInTheDocument();
    // Its modules under it: the API's code, what it is in, how big.
    const code = column("code").getByRole("button", { name: "Leka/api, Backend" });
    expect(code).toHaveTextContent("Backend · Python · 470 fichiers");
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
    await user.click(api);
    expect(api).toHaveAttribute("aria-pressed", "true");

    const panel = within(screen.getByTestId("architecture-panel"));
    expect(panel.getByRole("heading", { name: "Leka API" })).toBeInTheDocument();
    // Why it is said healthy, in the screen's words: what runs it, its last deployment.
    expect(panel.getByTestId("architecture-health")).toHaveTextContent(
      "Déduit de leka-prod (EC2 · Machine virtuelle) : En bonne santé · dernier déploiement réussi",
    );
    // Its figures (LEKA-459), each only as a source knows it.
    const figures = panel.getByTestId("architecture-figures");
    expect(figures).toHaveTextContent("Disponibiliténon mesurée");
    expect(figures).toHaveTextContent("Dernier déploiementréussi");
    expect(panel.getByTestId("architecture-state")).toHaveTextContent("En bonne santé");
    expect(panel.getByText("Python · FastAPI")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: "Haitam-elh/Leka" })).toBeInTheDocument();
    expect(panel.getByRole("link", { name: "api.leka-core.com" })).toHaveAttribute(
      "href",
      "https://api.leka-core.com",
    );
    // Its code, by its module.
    expect(panel.getByRole("button", { name: "Leka/api" })).toBeInTheDocument();
    expect(panel.getByText("Aucune équipe connue")).toBeInTheDocument();
    expect(panel.getByText("deploy/docker-compose.production.yml:24 — api")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: /Ouvrir la fiche/ })).toHaveAttribute(
      "href",
      `/environment/services/${API}`,
    );
  });

  it("names another card's relations from its side, leads to a database's tables", async () => {
    const user = userEvent.setup();
    mount(<ArchitectureBoard data={ARCHITECTURE} />);

    await user.click(screen.getByRole("button", { name: /^PostgreSQL, Base de données/ }));
    const panel = within(screen.getByTestId("architecture-panel"));
    expect(panel.getByText("36 tables · 2,3 Mo")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: /Voir ses tables/ })).toHaveAttribute(
      "href",
      `/environment/graph?entity=${POSTGRES}`,
    );

    await user.click(panel.getByTestId("architecture-panel-relations"));
    const rows = within(panel.getByTestId("architecture-relations")).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      // Inferred: by which rule, how surely.
      expect.stringMatching(/^Hébergé surdéduit : seule base de ce moteur dans le cloud · 70 %leka/),
      expect.stringMatching(/^Stockage de.*Leka API/),
      expect.stringMatching(/^Stockage de.*Leka Worker/),
    ]);
    // A relation is a way to the other card.
    await user.click(within(rows[0]).getByRole("button"));
    const chosen = within(screen.getByTestId("architecture-panel"));
    expect(chosen.getByRole("heading")).toHaveTextContent("leka");

    // Escape closes it as ✕ does, from inside it (LEKA-438).
    screen.getByRole("button", { name: "Fermer le détail" }).focus();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("architecture-panel")).not.toBeInTheDocument();
  });

  it("says every link in words", () => {
    mount(<ArchitectureBoard data={ARCHITECTURE} />);

    const words = within(screen.getByTestId("architecture-text"));
    expect(words.getByText("Leka Web appelle Leka API")).toBeInTheDocument();
    expect(words.getByText("Leka est le code de Leka API")).toBeInTheDocument();
    expect(words.getByText(/^Leka API est déployé sur leka-prod/)).toHaveTextContent(
      "(déduit par LEKA)",
    );
  });

  it("says what to connect when nothing is known", () => {
    mount(<ArchitectureBoard data={NOTHING} />);

    expect(screen.getByText("Votre architecture n'est pas encore connue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connecter" })).toHaveAttribute("href", "/sources");
    expect(screen.queryByTestId("architecture")).not.toBeInTheDocument();
  });

  it("says a module's parts and a machine's details", async () => {
    const user = userEvent.setup();
    mount(<ArchitectureBoard data={ARCHITECTURE} />);

    await user.click(screen.getByRole("button", { name: "Leka/api, Backend" }));
    const parts = within(screen.getByTestId("architecture-parts"));
    expect(parts.getByText("Parties du code (2)")).toBeInTheDocument();
    expect(parts.getByText("90 fichiers · 31 sous-parties")).toBeInTheDocument();
    expect(parts.getByText("github")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^leka-prod, EC2/ }));
    const facts = within(screen.getByTestId("architecture-facts"));
    expect(facts.getByText("Type d'instance")).toBeInTheDocument();
    expect(facts.getByText("3.78.172.119")).toBeInTheDocument();
    expect(facts.getByText("Oui")).toBeInTheDocument();
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
    // The code's arrow from its module: the repository speaks through it.
    expect(drawn).toContainEqual([API_CODE, API, "source_code", false]);
    expect(drawn.filter(([from]) => from === REPO)).toEqual([]);
    expect(drawn).toContainEqual([POSTGRES, RDS, "hosted_on", false]);
    expect(drawn.filter(([, , , own]) => own)).toEqual([]);
  });

  it("the chosen card's own links over the rest, alike ones together", () => {
    const drawn = ends(arrowsOf(ARCHITECTURE, byId, API, false));

    // To the data, two different things: one arrow to the column.
    expect(drawn).toContainEqual([API, "panel:data", "stores", true]);
    expect(drawn).toContainEqual([API, BOX, "deployed_on", true]);
    expect(drawn).toContainEqual([WEB, API, "calls", true]);
    // Its code is said by the code's own arrows, not across the services.
    expect(drawn.filter(([from, , , own]) => own && (from === API_CODE || from === REPO))).toEqual(
      [],
    );
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
