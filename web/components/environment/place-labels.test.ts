/**
 * The relations' names on the map (LEKA-492): never over a card, never over
 * another name; the chosen card's placed first; none free, its name not
 * drawn — the line, always.
 */

import { describe, expect, it } from "vitest";

import { placeLabels } from "@/components/environment/architecture";

const line = (id: string, spots: { x: number; y: number }[], own = false) => ({
  id,
  d: "M 0 0",
  tone: "neutral" as const,
  dashed: false,
  faded: false,
  label: "Appelle",
  x: spots[0].x,
  y: spots[0].y,
  spots,
  own,
});

describe("where a relation's name goes", () => {
  it("off the card it would cover, further along its line", () => {
    const card = { left: 80, top: 80, right: 120, bottom: 120 };
    const [placed] = placeLabels([line("a", [{ x: 100, y: 100 }, { x: 100, y: 200 }])], [card]);
    expect([placed.x, placed.y, placed.label]).toEqual([100, 200, "Appelle"]);
  });

  it("never over another name: the chosen card's first, the other moves", () => {
    const spots = [{ x: 0, y: 0 }, { x: 0, y: 50 }];
    const [other, own] = placeLabels([line("other", spots), line("own", spots, true)], []);
    expect([own.x, own.y]).toEqual([0, 0]);
    expect([other.x, other.y]).toEqual([0, 50]);
  });

  it("no free spot: its name not drawn, its line kept", () => {
    const card = { left: -100, top: -100, right: 100, bottom: 100 };
    const [placed] = placeLabels([line("a", [{ x: 0, y: 0 }])], [card]);
    expect(placed.label).toBeNull();
    expect(placed.d).toBe("M 0 0");
  });
});
