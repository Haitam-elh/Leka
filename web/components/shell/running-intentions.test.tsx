/**
 * The header's intentions in progress (LEKA-475): only what the API keeps
 * active, each said as its journey says it — LEKA at work, or a person to
 * act — every one of them, and each opening its own page.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));
const permissions = vi.hoisted(() => ({ value: ["intention:read"] as string[] }));
const asked = vi.hoisted(() => ({ enabled: null as boolean | null }));
const active = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => null,
}));
vi.mock("@/lib/intentions/queries", () => ({
  useMyActiveIntentions: (enabled: boolean) => {
    asked.enabled = enabled;
    return active;
  },
  useAnalyseAgain: () => ({}),
  useIntentionChange: () => ({}),
}));

const { RunningIntentions } = await import("@/components/shell/running-intentions");

const row = (id: string, state: string, by: string | null, late = false) => ({
  id,
  title: `Intention ${id}`,
  journey: { state, by, late, controls: [] },
});
const page = (rows: unknown[], next: string | null = null) => {
  active.data = { data: rows, next_cursor: next };
};
const show = () => render(<LocaleProvider><RunningIntentions /></LocaleProvider>);

describe("the header's intentions in progress", () => {
  it("says nothing until the API has one, and asks nothing of whoever may not read them", () => {
    active.data = undefined;
    show();
    expect(screen.queryByTestId("running-intentions")).toBeNull();
    page([]);
    show();
    expect(screen.queryByTestId("running-intentions")).toBeNull();

    permissions.value = [];
    show();
    expect(asked.enabled).toBe(false);
    permissions.value = ["intention:read"];
  });

  it("one, LEKA at work: its state and its title, opening its page", () => {
    page([row("a1", "analysing", "leka")]);
    show();
    const link = screen.getByTestId("running-intentions");
    expect(link).toHaveAttribute("href", "/intentions/a1");
    expect(link).toHaveAccessibleName("Analyse en cours — Intention a1");
    expect(link.className).toMatch(/brand-violet/);
    expect(link.querySelector(".animate-spin")).not.toBeNull();
  });

  it("late is said, and not as at work", () => {
    page([row("a1", "ready", "leka", true)]);
    show();
    const link = screen.getByTestId("running-intentions");
    expect(link).toHaveAccessibleName("Prête à analyser · en retard — Intention a1");
    expect(link.className).toMatch(/state-warning/);
    expect(link.querySelector(".animate-spin")).toBeNull();
  });

  it("a failure has its own colour; a decision is to deal with", () => {
    page([row("f1", "analysis_failed", "asker")]);
    show();
    expect(screen.getByTestId("running-intentions").className).toMatch(/state-danger/);

    page([row("d1", "decision_required", "approver")]);
    show();
    const link = screen.getAllByTestId("running-intentions").at(-1)!;
    expect(link).toHaveAccessibleName("Décision requise — Intention d1");
    expect(link.className).toMatch(/state-warning/);
  });

  it("several: counted, the ones to deal with said, every one listed and opened", async () => {
    page([
      row("a1", "analysing", "leka"),
      row("r1", "action_running", "leka"),
      row("d1", "decision_required", "asker"),
    ]);
    show();
    const trigger = screen.getByTestId("running-intentions");
    expect(trigger).toHaveAccessibleName("3 en cours · 1 à traiter");
    await userEvent.click(trigger);
    const items = await screen.findAllByTestId("running-intention");
    expect(items.map((item) => item.dataset.state)).toEqual([
      "analysing",
      "action_running",
      "decision_required",
    ]);
    expect(within(items[2]).getByText("Décision requise")).toBeInTheDocument();
    await userEvent.click(items[2]);
    expect(router.push).toHaveBeenCalledWith("/intentions/d1");
  });

  it("more than a page: never a count it does not have", () => {
    page([row("a1", "analysing", "leka"), row("a2", "analysing", "leka")], "next");
    show();
    expect(screen.getByTestId("running-intentions")).toHaveAccessibleName("2+ en cours");
  });
});
