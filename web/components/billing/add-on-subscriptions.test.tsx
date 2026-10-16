/**
 * Vos agents et bundles (LEKA-474): each subscription bought besides the
 * plan, renewed until cancelled — « Annuler l'abonnement » while it renews,
 * then its end said and « Réactiver le renouvellement »; only its own
 * subscription asked; only who may pay sees the buttons.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const owned = vi.hoisted(() => ({ data: undefined as unknown }));
const renewal = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
vi.mock("@/lib/billing-queries", () => ({
  useEntitlements: () => owned,
  useAddOns: () => ({
    data: {
      agents: [
        { key: "security-review", title: "Revue de sécurité" },
        { key: "code-review", title: "Revue de code" },
      ],
      bundles: [{ key: "dev-pack", name: { fr: "Pack Dev", en: "Dev pack" } }],
    },
  }),
  useAddOnRenewal: () => renewal,
}));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => permissions.value }));

const { AddOnSubscriptions } = await import("@/components/billing/add-on-subscriptions");

const bought = (key: string, kind: string, subscription: string, over: Record<string, unknown> = {}) => ({
  key,
  kind,
  origin: "purchase",
  started_at: "2026-10-01T00:00:00Z",
  agents: [key],
  subscription,
  cancel_at_period_end: false,
  current_period_end: "2026-11-10T00:00:00Z",
  ...over,
});
const show = () =>
  render(
    <LocaleProvider>
      <ConfirmProvider>
        <AddOnSubscriptions />
      </ConfirmProvider>
    </LocaleProvider>,
  );

beforeEach(() => {
  renewal.mutate.mockReset();
  permissions.value = ["workspace:read", "workspace:update"];
});

describe("Vos agents et bundles", () => {
  it("nothing bought, or only granted: nothing said", () => {
    owned.data = [{ ...bought("*", "all", ""), origin: "grant", subscription: null }];
    show();
    expect(screen.queryByTestId("billing-add-ons")).toBeNull();
  });

  it("renewing: its next renewal and « Annuler l'abonnement », confirmed, for its own subscription only", async () => {
    owned.data = [
      bought("security-review", "agent", "sub_a"),
      bought("dev-pack", "bundle", "sub_b"),
    ];
    const user = userEvent.setup();
    show();
    const [agent, bundle] = screen.getAllByTestId("billing-add-on");
    expect(agent).toHaveTextContent("Revue de sécurité");
    expect(agent).toHaveTextContent("Renouvellement automatique le 10 novembre 2026");
    expect(bundle).toHaveTextContent("Pack Dev");

    await user.click(within(bundle).getByRole("button", { name: "Annuler l'abonnement" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Annuler l'abonnement de Pack Dev ?");
    expect(dialog).toHaveTextContent("Pack Dev reste disponible jusqu'au 10 novembre 2026");
    expect(dialog).toHaveTextContent("Votre formule et vos autres abonnements ne changent pas");
    await user.click(within(dialog).getByRole("button", { name: "Annuler l'abonnement" }));
    await waitFor(() =>
      expect(renewal.mutate).toHaveBeenCalledWith({ subscription: "sub_b", renew: false }, expect.anything()),
    );
  });

  it("cancelled: its end said and « Réactiver le renouvellement »", async () => {
    owned.data = [bought("security-review", "agent", "sub_a", { cancel_at_period_end: true })];
    const user = userEvent.setup();
    show();
    const row = screen.getByTestId("billing-add-on");
    expect(row).toHaveTextContent("Résiliation programmée : disponible jusqu'au 10 novembre 2026");
    expect(within(row).queryByRole("button", { name: "Annuler l'abonnement" })).toBeNull();
    await user.click(within(row).getByRole("button", { name: "Réactiver le renouvellement" }));
    expect(renewal.mutate).toHaveBeenCalledWith({ subscription: "sub_a", renew: true }, expect.anything());
  });

  it("several agents bought together: one subscription, one line", () => {
    owned.data = [
      bought("security-review", "agent", "sub_c"),
      bought("code-review", "agent", "sub_c"),
    ];
    show();
    const [row] = screen.getAllByTestId("billing-add-on");
    expect(screen.getAllByTestId("billing-add-on")).toHaveLength(1);
    expect(row).toHaveTextContent("Revue de sécurité, Revue de code");
  });

  it("who may not pay reads it, without the buttons", () => {
    permissions.value = ["workspace:read"];
    owned.data = [bought("security-review", "agent", "sub_a")];
    show();
    expect(screen.getByTestId("billing-add-on")).toHaveTextContent("Renouvellement automatique");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
