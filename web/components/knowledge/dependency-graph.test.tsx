/**
 * DependencyGraph: the entities it is given appear, as nodes and in words.
 *
 * jsdom has no layout: React Flow's ResizeObserver and DOMMatrixReadOnly
 * are stubbed, as its own testing guide does. What is asserted is what the
 * component decides — which nodes and edges exist, their colours, their
 * words, what a click does — not pixels.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  DependencyGraph,
  graphEdges,
  layered,
  layeredPositions,
} from "@/components/knowledge/dependency-graph";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { KnowledgeEntity, KnowledgeRelationship } from "@/lib/knowledge";

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  class DOMMatrixStub {
    m22 = 1;
  }
  vi.stubGlobal("DOMMatrixReadOnly", DOMMatrixStub);
});

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const ENTITIES: KnowledgeEntity[] = [
  { id: "users", type: "person", name: "Utilisateurs" },
  { id: "api", type: "service", name: "Payment API", status: "incident" },
  { id: "auth", type: "service", name: "Auth Service", status: "attention" },
  { id: "db", type: "database", name: "Payment DB", status: "operational" },
  { id: "aws", type: "infra_resource", name: "AWS", status: "operational" },
];

const LINKS: KnowledgeRelationship[] = [
  { id: "l1", from: "users", to: "api", type: "depends_on", status: "operational" },
  { id: "l2", from: "api", to: "db", type: "depends_on", status: "incident" },
  { id: "l3", from: "api", to: "auth", type: "depends_on", status: "attention" },
  { id: "l4", from: "db", to: "aws", type: "deployed_to" },
  // Points at an entity that is not on the map: dropped, not drawn to nowhere.
  { id: "l5", from: "api", to: "ghost", type: "depends_on" },
];

describe("DependencyGraph", () => {
  it("draws a node for every entity it is given", () => {
    const { container } = mount(<DependencyGraph entities={ENTITIES} relationships={LINKS} />);

    for (const entity of ENTITIES) {
      expect(container.querySelector(`[data-entity-id="${entity.id}"]`)).not.toBeNull();
    }
  });

  it("writes the whole graph out for screen readers, in words", () => {
    mount(<DependencyGraph entities={ENTITIES} relationships={LINKS} />);

    const text = screen.getByTestId("graph-text");
    expect(text).toHaveClass("sr-only");
    expect(text).toHaveTextContent("Payment API, Service, Incident");
    expect(text).toHaveTextContent("Payment API dépend de Payment DB (Incident)");
    expect(text).toHaveTextContent("Payment DB est déployé sur AWS");
    expect(text).not.toHaveTextContent("ghost");
    expect(
      screen.getByRole("heading", { name: "Graphe des dépendances — 5 entité(s), 4 relation(s)" }),
    ).toBeInTheDocument();
  });

  it("colours each edge by its relationship's status, and names it in words", () => {
    const edges = graphEdges(
      ENTITIES,
      LINKS,
      (type) => DICTIONARIES.fr.knowledge.relationships[type],
    );
    const byId = new Map(edges.map((edge) => [edge.id, edge]));

    expect(byId.get("l2")?.style?.stroke).toBe("var(--state-danger)");
    expect(byId.get("l3")?.style?.stroke).toBe("var(--state-warning)");
    expect(byId.get("l1")?.style?.stroke).toBe("var(--state-success)");
    expect(byId.get("l4")?.style?.stroke).toBe("var(--shell-muted)");
    expect(byId.get("l2")?.ariaLabel).toBe("Payment API dépend de Payment DB");
    expect(byId.has("l5")).toBe(false);
  });

  it("opens a node from its name, and marks the selected one", () => {
    const onNodeClick = vi.fn();
    mount(
      <DependencyGraph
        entities={ENTITIES}
        relationships={LINKS}
        onNodeClick={onNodeClick}
        selectedId="db"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Payment API", hidden: true }));
    expect(onNodeClick).toHaveBeenCalledWith("api");
    expect(screen.getByRole("button", { name: "Payment DB", hidden: true })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("offers zoom, fit and reset as buttons with words", () => {
    mount(<DependencyGraph entities={ENTITIES} relationships={LINKS} />);

    for (const name of [
      "Zoom avant",
      "Zoom arrière",
      "Ajuster à l'écran",
      "Réinitialiser la vue",
    ]) {
      expect(screen.getByRole("button", { name, hidden: true })).toBeInTheDocument();
    }
  });

  it("says so when there is nothing to draw", () => {
    mount(<DependencyGraph entities={[]} relationships={[]} />);

    expect(screen.getByRole("heading", { name: "Aucune entité à afficher." })).toBeVisible();
  });

  it("holds 150 nodes, each with a place of its own", () => {
    const many: KnowledgeEntity[] = Array.from({ length: 150 }, (_, i) => ({
      id: `svc-${i}`,
      type: i % 3 === 0 ? "database" : "service",
      name: `Service ${i}`,
    }));
    const links: KnowledgeRelationship[] = many.slice(1).map((entity, i) => ({
      id: `l-${i}`,
      from: many[i].id,
      to: entity.id,
      type: "depends_on",
    }));

    const positions = layeredPositions(many);
    const spots = new Set(Object.values(positions).map(({ x, y }) => `${x}:${y}`));
    expect(spots.size).toBe(150);
    // Rows wrap at ten: the map stays roughly square rather than a strip.
    const columns = new Set(Object.values(positions).map(({ x }) => x));
    expect(columns.size).toBeLessThanOrEqual(10);

    mount(<DependencyGraph entities={many} relationships={links} />);
    const text = within(screen.getByTestId("graph-text"));
    expect(text.getAllByRole("listitem")).toHaveLength(150 + 149);
  });
});

describe("an edge's ends", () => {
  it("goes down from the bottom, and up to what is above from the top", () => {
    const [down, up] = graphEdges(
      ENTITIES,
      [
        { id: "d", from: "api", to: "db", type: "depends_on" },
        { id: "u", from: "db", to: "api", type: "depends_on" },
      ],
      (type) => type,
      { api: { x: 0, y: 0 }, db: { x: 0, y: 128 } },
    );

    expect([down.sourceHandle, down.targetHandle]).toEqual(["down", "above"]);
    expect([up.sourceHandle, up.targetHandle]).toEqual(["up", "below"]);
  });
});

describe("layered", () => {
  const ids = (rows: { id: string }[][]) => rows.map((row) => row.map((one) => one.id));
  const node = (id: string) => ({ id });

  it("puts what a thing points to under it, so arrows go down, not along a row", () => {
    // sessions → users → workspaces, invitations → workspaces: foreign keys.
    const tables = ["workspaces", "sessions", "invitations", "users"].map(node);
    const keys = [
      { from: "sessions", to: "users" },
      { from: "users", to: "workspaces" },
      { from: "invitations", to: "workspaces" },
    ];

    expect(ids(layered([tables], keys))).toEqual([
      ["sessions", "invitations"],
      ["users"],
      ["workspaces"],
    ]);
  });

  it("keeps each group its own rows, in the groups' order", () => {
    const rows = layered(
      [[node("billing")], [node("orders"), node("invoices")]],
      [
        { from: "billing", to: "orders" },
        { from: "invoices", to: "orders" },
      ],
    );

    expect(ids(rows)).toEqual([["billing"], ["invoices"], ["orders"]]);
  });

  it("cuts a loop where it closes, and places everything once", () => {
    const rows = layered(
      [["a", "b", "c"].map(node)],
      [
        { from: "a", to: "b" },
        { from: "b", to: "c" },
        { from: "c", to: "a" },
        { from: "a", to: "a" },
      ],
    );

    expect(rows.flat().map((one) => one.id).sort()).toEqual(["a", "b", "c"]);
  });

  it("orders a row under what it is tied to above it, so lines cross little", () => {
    const rows = layered(
      [[node("left"), node("right")], [node("under-right"), node("under-left")]],
      [
        { from: "left", to: "under-left" },
        { from: "right", to: "under-right" },
      ],
    );

    expect(ids(rows)).toEqual([
      ["left", "right"],
      ["under-left", "under-right"],
    ]);
  });
});
