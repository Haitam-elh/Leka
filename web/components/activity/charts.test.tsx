/**
 * The activity chart (LEKA-469): its axis leaves room for its longest
 * tick — 4 117 events put « 8000 » on it, which a fixed margin cut.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StackedBars } from "@/components/activity/charts";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const day = (counts: Partial<Record<"information" | "action" | "alert" | "incident", number>>) => ({
  day: "2026-10-16",
  counts: { information: 0, action: 0, alert: 0, incident: 0, ...counts },
});

describe("StackedBars", () => {
  it("starts the plot after its widest tick, so « 8000 » is not cut", () => {
    render(
      <LocaleProvider>
        <StackedBars data={[day({ information: 4117 })]} />
      </LocaleProvider>,
    );
    const chart = screen.getByTestId("activity-bars");
    expect(chart).toHaveTextContent("8000");
    // Four digits at ~7 units each, right-aligned 8 units before the plot.
    const gridline = chart.querySelector("line") as SVGLineElement;
    expect(Number(gridline.getAttribute("x1"))).toBeGreaterThanOrEqual(8 + 4 * 7);
  });
});
