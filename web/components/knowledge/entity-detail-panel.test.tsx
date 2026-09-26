/**
 * EntityDetailPanel: every section when there is data, none when there is not.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type EntityDetail, EntityDetailPanel } from "@/components/knowledge/entity-detail-panel";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const PAYMENT_API: EntityDetail = {
  id: "svc-payment-api",
  type: "service",
  name: "Payment API",
  description: "Service de traitement des paiements qui gère l'ensemble du flux de transaction.",
  status: "incident",
  version: "v2.8.4",
  environment: "Production",
  owner: { name: "Thomas Martin", role: "Tech Lead · Payments" },
  tags: ["payments"],
  lastUpdated: minutesAgo(5),
  confidence: 0.88,
  source: { kind: "datadog", name: "acme-eu", syncedAt: minutesAgo(5) },
  metrics: [
    {
      id: "p95",
      label: "Latence (p95)",
      value: "520 ms",
      delta: { value: "+68 %", direction: "up", good: false },
      series: [300, 310, 305, 320, 480, 520],
    },
    { id: "rpm", label: "Requêtes / min", value: "1 240" },
  ],
  dependencies: [
    {
      entity: { id: "svc-auth", type: "service", name: "Auth Service" },
      direction: "upstream",
      status: "attention",
      detail: "Impacte la latence",
    },
  ],
  changes: [{ id: "d1", type: "deployment", title: "Déploiement v2.8.4", at: minutesAgo(80) }],
  incidents: [{ id: "i1", type: "incident", title: "Incident INC-2841", at: minutesAgo(75) }],
  sections: [
    {
      title: "Informations générales",
      items: [
        { label: "Environnement", value: "Production" },
        { label: "Infrastructure", value: "EKS · AWS (eu-west-1)" },
      ],
    },
  ],
};

describe("EntityDetailPanel", () => {
  it("shows every section it has data for", () => {
    mount(<EntityDetailPanel entity={PAYMENT_API} mode="full" />);

    const panel = screen.getByRole("article", { name: "Payment API" });
    expect(within(panel).getByRole("heading", { level: 2, name: "Payment API" })).toBeVisible();
    expect(panel).toHaveTextContent("Service · Production");
    // "Incident" is also the incident event's kind: the status badge is the one with a variant.
    expect(panel.querySelector("[data-variant='entity.incident']")).toHaveTextContent("Incident");
    expect(panel).toHaveTextContent("Version v2.8.4");
    expect(panel).toHaveTextContent("Thomas Martin");
    expect(within(panel).getByRole("group", { name: "Provenance" })).toBeVisible();
    for (const title of ["Changements récents", "Incidents récents", "Dépendances (1)", "Informations générales"]) {
      expect(within(panel).getByRole("heading", { level: 3, name: title })).toBeVisible();
    }
  });

  it("says a metric's change in words, and draws its recent values", () => {
    const { container } = mount(<EntityDetailPanel entity={PAYMENT_API} />);

    const metrics = screen.getByRole("region", { name: "Métriques clés" });
    expect(metrics).toHaveTextContent("Latence (p95)520 ms");
    expect(within(metrics).getByText("en hausse de +68 %")).toHaveClass("sr-only");
    expect(container.querySelector("svg[data-points='6']")).toHaveAttribute("aria-hidden", "true");
  });

  it("is a correct panel with nothing but id, type and name", () => {
    mount(<EntityDetailPanel entity={{ id: "db", type: "database", name: "Payment DB" }} />);

    const panel = screen.getByRole("complementary", { name: "Payment DB" });
    expect(panel).toHaveTextContent("Base de données");
    expect(within(panel).queryAllByRole("heading", { level: 3 })).toHaveLength(0);
    expect(within(panel).queryByRole("region")).toBeNull();
    expect(within(panel).queryByRole("group")).toBeNull();
    expect(within(panel).queryByRole("button")).toBeNull();
  });

  it("drops sections whose lists are empty, rather than showing empty boxes", () => {
    mount(
      <EntityDetailPanel
        entity={{ ...PAYMENT_API, changes: [], incidents: [], dependencies: [], sections: [], metrics: [] }}
      />,
    );

    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });

  it("asks LEKA, closes, and opens a dependency — each from the keyboard too", async () => {
    const user = userEvent.setup();
    const onAskLeka = vi.fn();
    const onClose = vi.fn();
    const onSelectEntity = vi.fn();
    mount(
      <EntityDetailPanel
        entity={PAYMENT_API}
        onAskLeka={onAskLeka}
        onClose={onClose}
        onSelectEntity={onSelectEntity}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Demander à LEKA" }));
    expect(onAskLeka).toHaveBeenCalledWith("svc-payment-api");

    screen.getByRole("button", { name: "Fermer le panneau" }).focus();
    await user.keyboard("{Enter}");
    expect(onClose).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Auth Service" }));
    expect(onSelectEntity).toHaveBeenCalledWith("svc-auth");
  });

  it("draws no line for fewer than two values, and a flat one for identical values", () => {
    const { container } = mount(
      <EntityDetailPanel
        entity={{
          ...PAYMENT_API,
          metrics: [
            { id: "a", label: "A", value: "1", series: [1] },
            { id: "b", label: "B", value: "2", series: [5, 5, 5] },
          ],
        }}
      />,
    );

    expect(container.querySelector("svg[data-points='1']")).toBeNull();
    expect(container.querySelector("svg[data-points='3']")).not.toBeNull();
  });
});
