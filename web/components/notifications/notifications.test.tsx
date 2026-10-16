/**
 * The notification centre (LEKA-476), on screen.
 *
 * What these protect:
 * - Every kind the server tells has its words, in French and in English —
 *   read from the server's own projector, so a new kind without words
 *   fails here — and each says its parts: a title, a plan, a date.
 * - The bell says how many are unread, in words to whoever cannot see the
 *   badge; opened, the latest, each to where it leads — opened, it is read;
 *   all read at once; nothing yet said so; a failure said.
 * - The centre: by category, the unread only, a page at a time, an empty
 *   centre said so; what one mutes, kept.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Notification } from "@/lib/notifications";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  page: vi.fn(),
  unread: vi.fn(),
  read: vi.fn(),
  unreadAgain: vi.fn(),
  readAll: vi.fn(),
  preferences: vi.fn(),
  mute: vi.fn(),
}));
vi.mock("@/lib/notifications", async (original) => ({
  ...(await original<typeof import("@/lib/notifications")>()),
  notifications: api,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/notifications",
  useSearchParams: () => new URLSearchParams(),
}));

const { wordsOf } = await import("@/components/notifications/words");
const { NotificationBell } = await import("@/components/notifications/bell");
const { NotificationsScreen } = await import("@/components/notifications/notifications-page");

const fr = DICTIONARIES.fr;

function note(kind: string, overrides: Partial<Notification> = {}): Notification {
  return {
    id: `n-${kind}-${Math.random().toString(16).slice(2)}`,
    category: "intention",
    kind,
    severity: "info",
    params: { title: "Pourquoi payment-api est lente ?" },
    link: "/intentions/i-1",
    occurred_at: new Date().toISOString(),
    read: false,
    ...overrides,
  } as Notification;
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.read.mockResolvedValue(undefined);
  api.unreadAgain.mockResolvedValue(undefined);
  api.readAll.mockResolvedValue({ marked: 2 });
  api.preferences.mockResolvedValue({ muted: [] });
  api.mute.mockImplementation((muted: string[]) => Promise.resolve({ muted }));
});

describe("the words of every kind", () => {
  // The kinds the server tells, read from its projector.
  const projector = readFileSync(
    join(__dirname, "../../../api/leka/notifications/projector.py"),
    "utf8",
  );
  const told = [
    ...new Set(
      [...projector.matchAll(/"((?:intention|agent|alert|source|billing|capacity|workspace)\.[a-z_]+)"/g)].map(
        (m) => m[1],
      ),
    ),
  ];

  it("every kind the server tells has its words, in French and in English", () => {
    expect(told.length).toBeGreaterThan(20);
    for (const tag of ["fr", "en"]) {
      const kinds = DICTIONARIES[tag].notifications.kinds as Record<string, { title: string }>;
      expect(told.filter((kind) => !kinds[kind]), tag).toEqual([]);
    }
  });

  it("says each its parts — a title, a plan, a role, a date", () => {
    expect(wordsOf(fr, note("intention.decision_required"), "fr-FR")).toEqual({
      title: "Décision requise",
      body: "« Pourquoi payment-api est lente ? » attend une décision.",
    });
    expect(
      wordsOf(fr, note("billing.plan_changed", { params: { before: "free", after: "growth" } }), "fr-FR").body,
    ).toBe("Votre formule passe de Free à Growth.");
    expect(
      wordsOf(fr, note("workspace.role_changed", { params: { before: "member", after: "admin" } }), "fr-FR").body,
    ).toBe("Votre rôle passe de membre à administrateur.");
    expect(
      wordsOf(fr, note("billing.cancellation_scheduled", { params: {} }), "fr-FR").body,
    ).toBe("L'abonnement prendra fin à la fin de la période.");
    expect(
      wordsOf(fr, note("billing.cancellation_scheduled", { params: { until: "2026-11-30T00:00:00Z" } }), "fr-FR")
        .body,
    ).toMatch(/^L'abonnement prendra fin le 30 nov\. 2026/);
    expect(
      wordsOf(fr, note("alert.triggered", { params: { name: "payment-api", trouble: "unavailable", certainty: "confirmed" } }), "fr-FR"),
    ).toEqual({ title: "Alerte : payment-api", body: "payment-api : indisponible (confirmé)." });
    // A kind not known yet: still said, never a blank row.
    expect(wordsOf(fr, note("something.new"), "fr-FR").title).toBe("Notification");
  });
});

describe("the bell", () => {
  it("says how many are unread; opened, the latest, each to where it leads — opened, read", async () => {
    const user = userEvent.setup();
    api.unread.mockResolvedValue({ unread: 3 });
    api.page.mockResolvedValue({
      data: [note("intention.decision_required"), note("capacity.threshold", { category: "billing", params: { threshold: 80 }, link: "/billing", read: true })],
      next_cursor: null,
      unread: 3,
    });
    show(<NotificationBell />);
    const bell = await screen.findByRole("button", { name: "Notifications, 3 non lues" });
    expect(screen.getByTestId("notifications-count")).toHaveTextContent("3");
    // Nothing listed before it is opened.
    expect(api.page).not.toHaveBeenCalled();

    await user.click(bell);
    const panel = await screen.findByTestId("notifications-panel");
    const rows = await within(panel).findAllByTestId("notification");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Décision requise");
    expect(rows[0]).toHaveAttribute("data-read", "false");
    expect(within(panel).getByTestId("notifications-see-all")).toHaveAttribute("href", "/notifications");

    await user.click(within(rows[0]).getByTestId("notification-open"));
    expect(api.read).toHaveBeenCalledWith(rows[0].closest("li") ? expect.any(String) : "");
  });

  it("all read at once; nothing yet, said so", async () => {
    const user = userEvent.setup();
    api.unread.mockResolvedValue({ unread: 2 });
    api.page.mockResolvedValue({ data: [], next_cursor: null, unread: 2 });
    show(<NotificationBell />);
    await user.click(await screen.findByRole("button", { name: "Notifications, 2 non lues" }));
    expect(await screen.findByTestId("notifications-empty")).toHaveTextContent("Aucune notification pour l'instant.");
    await user.click(screen.getByTestId("notifications-read-all"));
    await waitFor(() => expect(api.readAll).toHaveBeenCalledWith(null));
  });

  it("nothing unread: no badge, a plain name", async () => {
    api.unread.mockResolvedValue({ unread: 0 });
    show(<NotificationBell />);
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByTestId("notifications-count")).toBeNull();
  });
});

describe("the centre", () => {
  it("by category, the unread only, a page at a time", async () => {
    const user = userEvent.setup();
    api.unread.mockResolvedValue({ unread: 1 });
    api.page.mockImplementation((filters: { category?: string | null }, cursor: string | null) =>
      Promise.resolve(
        cursor
          ? { data: [note("intention.created", { id: "n-older" })], next_cursor: null, unread: 1 }
          : {
              data: [note(filters.category === "billing" ? "billing.renewed" : "intention.analysis_completed", { id: "n-first" })],
              next_cursor: "c-1",
              unread: 1,
            },
      ),
    );
    show(<NotificationsScreen />);
    expect(await screen.findAllByTestId("notification")).toHaveLength(1);
    await user.click(screen.getByTestId("notifications-more"));
    await waitFor(() => expect(screen.getAllByTestId("notification")).toHaveLength(2));
    expect(api.page).toHaveBeenLastCalledWith({ category: null, unread: false }, "c-1", 20);

    await user.click(screen.getByRole("button", { name: "Abonnement et consommation" }));
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith({ category: "billing", unread: false }, null, 20),
    );
    expect(screen.getByRole("button", { name: "Abonnement et consommation" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("switch", { name: "Non lues" }));
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith({ category: "billing", unread: true }, null, 20),
    );
  });

  it("an empty centre says so, and what will be told here", async () => {
    api.unread.mockResolvedValue({ unread: 0 });
    api.page.mockResolvedValue({ data: [], next_cursor: null, unread: 0 });
    show(<NotificationsScreen />);
    const empty = await screen.findByTestId("notifications-empty");
    expect(empty).toHaveTextContent("Aucune notification pour l'instant.");
    expect(empty).toHaveTextContent("Vous serez prévenu ici");
    expect(screen.getByTestId("notifications-read-all")).toBeDisabled();
  });

  it("a category muted is kept — in the application only, said so", async () => {
    const user = userEvent.setup();
    api.unread.mockResolvedValue({ unread: 0 });
    api.page.mockResolvedValue({ data: [], next_cursor: null, unread: 0 });
    show(<NotificationsScreen />);
    const preferences = await screen.findByTestId("notification-preferences");
    expect(preferences).toHaveTextContent("Les e-mails des alertes de surveillance se règlent avec les alertes");
    const billing = within(preferences).getByRole("switch", { name: "Abonnement et consommation" });
    await waitFor(() => expect(billing).toBeEnabled());
    await user.click(billing);
    await waitFor(() => expect(api.mute).toHaveBeenCalledWith(["billing"]));
  });

  it("a failure said, and tried again", { timeout: 20_000 }, async () => {
    const user = userEvent.setup();
    api.unread.mockResolvedValue({ unread: 0 });
    api.page.mockRejectedValue(new Error("down"));
    show(<NotificationsScreen />);
    // Said once the query's own retries are spent.
    const retry = await screen.findByRole("button", { name: fr.states.retry }, { timeout: 15_000 });
    api.page.mockResolvedValue({ data: [], next_cursor: null, unread: 0 });
    await user.click(retry);
    expect(await screen.findByTestId("notifications-empty")).toBeInTheDocument();
  });
});
