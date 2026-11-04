/**
 * The night review's setting (LEKA-526): an alert each workspace turns on
 * or off, with the alerts' settings.
 *
 * What these protect: its state said, with what it does, when it runs and
 * what turning it off changes; the switch saved on the server, the state
 * shown as the server answered; feedback while it saves and when it fails —
 * the state it had kept; read-only for who may not manage the alerts; a
 * setting that could not be read, said.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { NightReviewSetting as Setting } from "@/lib/twin";

const night = vi.hoisted(() => ({ setting: vi.fn(), set: vi.fn() }));
vi.mock("@/lib/twin", async (original) => {
  const real = await original<typeof import("@/lib/twin")>();
  return {
    ...real,
    monitoring: { ...real.monitoring, nightSetting: night.setting, setNightSetting: night.set },
  };
});

const { NightReviewSetting } = await import("@/components/environment/night-review");

const SETTING: Setting = {
  enabled: true,
  default: true,
  hours_utc: ["21:30", "22:30", "23:30", "00:30", "01:30", "02:30", "03:30", "04:30", "05:30"],
  can_change: true,
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <NightReviewSetting id="night-review" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  night.setting.mockReset();
  night.set.mockReset();
  night.setting.mockResolvedValue(SETTING);
});

describe("the night review's setting (LEKA-526)", () => {
  it("says it is on, what it does, when it runs and what turning it off changes", async () => {
    const { container } = show();
    const setting = await screen.findByTestId("night-review-setting");
    expect(container.querySelector("#night-review")).not.toBeNull();
    expect(screen.getByTestId("night-review-setting-state")).toHaveTextContent("Activée");
    expect(setting).toHaveTextContent("Chaque heure de la nuit, de");
    expect(setting).toHaveTextContent("une notification et un e-mail");
    expect(setting).toHaveTextContent("Les revues passées et leurs constats restent");
    expect(screen.getByTestId("night-review-toggle")).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("night-review-setting-readonly")).not.toBeInTheDocument();
  });

  it("turns it off on the server, and shows the state the server answered", async () => {
    let answer: (value: Setting) => void = () => {};
    night.set.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    show();
    const toggle = await screen.findByTestId("night-review-toggle");
    await userEvent.click(toggle);
    expect(night.set).toHaveBeenCalledWith(false);
    // While it saves: the switch waits.
    await waitFor(() => expect(toggle).toHaveAttribute("aria-disabled", "true"));
    answer({ ...SETTING, enabled: false });
    await waitFor(() =>
      expect(screen.getByTestId("night-review-setting-state")).toHaveTextContent("Désactivée"),
    );
    expect(screen.getByTestId("night-review-setting")).toHaveTextContent(
      "Aucune revue la nuit, aucune notification ni e-mail le matin",
    );
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("says when it could not be saved, and keeps the state it had", async () => {
    night.set.mockRejectedValue(new Error("down"));
    show();
    await userEvent.click(await screen.findByTestId("night-review-toggle"));
    await waitFor(() => expect(night.set).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("night-review-toggle")).toHaveAttribute("aria-checked", "true"),
    );
    expect(screen.getByTestId("night-review-setting-state")).toHaveTextContent("Activée");
  });

  it("is read-only for whoever may not manage the alerts", async () => {
    night.setting.mockResolvedValue({ ...SETTING, enabled: false, can_change: false });
    show();
    expect(await screen.findByTestId("night-review-setting-readonly")).toHaveTextContent(
      "Seule une personne qui gère les sources et les alertes",
    );
    const toggle = screen.getByTestId("night-review-toggle");
    expect(toggle).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(toggle);
    expect(night.set).not.toHaveBeenCalled();
  });

  it("says when the setting could not be read", async () => {
    night.setting.mockRejectedValue(new Error("down"));
    show();
    expect(
      await screen.findByTestId("night-review-setting-failed", {}, { timeout: 5000 }),
    ).toHaveTextContent("n'a pas pu être lu");
  });
});
