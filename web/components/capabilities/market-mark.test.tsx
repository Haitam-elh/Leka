/**
 * One mark per agent domain (LEKA-493): every domain its icon and its hue,
 * none a state's; its name always said — the colour never alone.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MARKET_ICON, MARKETS, MarketTile, marketOf, marketText } from "@/components/capabilities/market-mark";

// The states' hues (docs/frontend/design-system.md): never a domain's.
const STATE_HUES = /(state-|violet|green|emerald|amber|orange|red-)/;

describe("an agent's domain mark", () => {
  it("every domain has its icon and a hue of its own, none a state's", () => {
    const hues = MARKETS.map((m) => marketText(m));
    expect(new Set(hues).size).toBe(MARKETS.length);
    for (const market of MARKETS) {
      expect(MARKET_ICON[market]).toBeDefined();
      expect(marketText(market)).not.toMatch(STATE_HUES);
      expect(marketText(market)).toMatch(/-700$/);
    }
  });

  it("an agent's domain: its marketplace's, else its category's", () => {
    expect(marketOf({ market: "frontend", category: "development" })).toBe("frontend");
    expect(marketOf({ market: null, category: "development" })).toBe("architecture");
    expect(marketOf({ category: "infrastructure" })).toBe("devops");
  });

  it("its name said for screen readers and on hover", () => {
    render(<MarketTile market="incident" label="Incidents" />);
    expect(screen.getByText("Incidents")).toHaveClass("sr-only");
    expect(screen.getByTitle("Incidents")).toHaveAttribute("data-market", "incident");
  });
});
