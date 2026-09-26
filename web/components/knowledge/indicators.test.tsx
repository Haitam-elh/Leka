/**
 * Quality, freshness and provenance: how far to trust a piece of knowledge.
 *
 * The clock is frozen (only Date is faked), so "Il y a 3 h" and the
 * thresholds are asserted exactly rather than approximately.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FreshnessIndicator,
  freshnessOf,
  QualityIndicator,
  qualityLevel,
} from "@/components/knowledge/indicators";
import { ProvenanceBadge } from "@/components/knowledge/provenance-badge";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const NOW = new Date("2026-09-26T12:00:00Z");
const hoursAgo = (hours: number) => new Date(NOW.getTime() - hours * 3_600_000).toISOString();

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("QualityIndicator", () => {
  it.each([
    [0, "low"],
    [49, "low"],
    [50, "medium"],
    [79, "medium"],
    [80, "high"],
    [100, "high"],
  ] as const)("puts %i in the %s band", (score, level) => {
    expect(qualityLevel(score)).toBe(level);
  });

  it("is a meter with its value, and says the level in words", () => {
    mount(<QualityIndicator score={72} />);

    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "72");
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "100");
    expect(meter).toHaveAccessibleName("Qualité des données : 72 sur 100, moyenne");
  });

  it("keeps out-of-range and missing scores inside 0–100", () => {
    mount(
      <>
        <QualityIndicator score={130} label="A" />
        <QualityIndicator score={-5} label="B" />
        <QualityIndicator score={Number.NaN} label="C" />
      </>,
    );

    const [a, b, c] = screen.getAllByRole("meter");
    expect(a).toHaveAttribute("aria-valuenow", "100");
    expect(b).toHaveAttribute("aria-valuenow", "0");
    expect(c).toHaveAttribute("aria-valuenow", "0");
  });
});

describe("FreshnessIndicator", () => {
  it.each([
    [0.5, "fresh"],
    [23.9, "fresh"],
    [24, "aging"],
    [167, "aging"],
    [168, "stale"],
  ] as const)("with the default thresholds, %f h old is %s", (hours, state) => {
    expect(freshnessOf(hoursAgo(hours))).toBe(state);
  });

  it("takes thresholds of its own", () => {
    const tight = { agingAfterHours: 1, staleAfterHours: 2 };

    expect(freshnessOf(hoursAgo(0.5), tight)).toBe("fresh");
    expect(freshnessOf(hoursAgo(1.5), tight)).toBe("aging");
    expect(freshnessOf(hoursAgo(3), tight)).toBe("stale");
  });

  it("says when something was never updated", () => {
    mount(<FreshnessIndicator lastUpdated={null} />);

    expect(screen.getByRole("button")).toHaveAttribute("data-freshness", "never");
    expect(screen.getByText("Jamais mise à jour")).toBeVisible();
  });

  it("shows the state and the time, and the exact date on focus", async () => {
    const user = userEvent.setup();
    mount(<FreshnessIndicator lastUpdated={hoursAgo(3)} />);

    const trigger = screen.getByRole("button");
    expect(trigger).toHaveTextContent("À jour ·Il y a 3 h");
    expect(trigger).toHaveAccessibleName(
      /Fraîcheur : À jour, Il y a 3 h\. Mise à jour le 26 sept\. 2026/,
    );

    await user.tab();
    expect(trigger).toHaveFocus();
    expect(await screen.findByText(/^Mise à jour le 26 sept\. 2026/)).toBeInTheDocument();
  });
});

describe("ProvenanceBadge", () => {
  it("names the source, and says in its accessible name when it synced and how good it is", () => {
    mount(
      <ProvenanceBadge
        source={{ kind: "github", name: "acme/backend", syncedAt: hoursAgo(2) }}
        quality={91}
      />,
    );

    const badge = screen.getByRole("button");
    expect(badge).toHaveTextContent("acme/backend");
    expect(badge).toHaveAccessibleName(/Provenance : GitHub · acme\/backend/);
    expect(badge).toHaveAccessibleName(/Il y a 2 h/);
    expect(badge).toHaveAccessibleName(/Qualité : 91 \/ 100/);
    expect(badge).not.toHaveAttribute("data-stale");
  });

  it("turns into a warning past its threshold, in words as well as colour", () => {
    mount(<ProvenanceBadge source={{ kind: "jira", syncedAt: hoursAgo(30) }} />);

    const badge = screen.getByRole("button");
    expect(badge).toHaveAttribute("data-stale", "true");
    expect(badge).toHaveAccessibleName(/Données anciennes/);
  });

  it("respects a threshold of its own", () => {
    mount(
      <ProvenanceBadge source={{ kind: "datadog", syncedAt: hoursAgo(2) }} staleAfterHours={1} />,
    );

    expect(screen.getByRole("button")).toHaveAttribute("data-stale", "true");
  });

  it("works with nothing but a kind: no name, never synced, no quality", () => {
    mount(<ProvenanceBadge source={{ kind: "aws" }} showLabel={false} />);

    const badge = screen.getByRole("button");
    expect(badge).toHaveAccessibleName(/Amazon Web Services\. Jamais synchronisée/);
    expect(badge).not.toHaveAttribute("data-stale");
  });
});
