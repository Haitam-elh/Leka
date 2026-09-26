/**
 * EntityCard: one entity, the same way everywhere.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EntityCard } from "@/components/knowledge/entity-card";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { ENTITY_TYPES } from "@/lib/knowledge";

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const FULL = {
  id: "svc-payment-api",
  type: "service" as const,
  name: "Payment API",
  description: "Service de traitement des paiements.",
  status: "incident" as const,
  owner: { name: "Thomas Martin", role: "Tech Lead" },
  tags: ["payments", "python"],
  lastUpdated: new Date(Date.now() - 2 * 3_600_000).toISOString(),
  confidence: 0.92,
  source: { kind: "github" as const, name: "acme/backend" },
};

describe("EntityCard", () => {
  it("shows everything it is given", () => {
    mount(<EntityCard {...FULL} />);

    const card = screen.getByRole("article");
    expect(within(card).getByRole("heading", { name: "Payment API" })).toBeVisible();
    expect(card).toHaveTextContent("Service · Thomas Martin");
    expect(within(card).getByText("Incident")).toHaveAttribute("data-variant", "entity.incident");
    expect(card).toHaveTextContent("Service de traitement des paiements.");
    expect(within(card).getByRole("list", { name: "Étiquettes" })).toHaveTextContent("payments");
    expect(within(card).getByRole("meter")).toHaveAttribute("aria-valuenow", "92");
    expect(within(card).getAllByRole("button")).toHaveLength(2); // freshness + provenance
  });

  it("is a whole card with only id, type and name — and leaves no gaps", () => {
    mount(<EntityCard id="db-1" type="database" name="Payment DB" />);

    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("Payment DB");
    expect(card).toHaveTextContent("Base de données");
    expect(within(card).queryByRole("button")).toBeNull();
    expect(within(card).queryByRole("meter")).toBeNull();
    expect(within(card).queryByRole("list")).toBeNull();
  });

  it.each(ENTITY_TYPES)("has an icon and a word for the %s type", (type) => {
    const { container } = mount(<EntityCard id={type} type={type} name="X" />);

    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("article").textContent).not.toBe("X");
  });

  it("is clicked through its name, from the mouse or the keyboard", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    mount(<EntityCard {...FULL} onClick={onClick} />);

    await user.click(screen.getByRole("button", { name: "Payment API" }));
    expect(onClick).toHaveBeenCalledWith("svc-payment-api");

    screen.getByRole("button", { name: "Payment API" }).focus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("keeps its badges reachable on their own when it is clickable", async () => {
    const user = userEvent.setup();
    mount(<EntityCard {...FULL} onClick={() => {}} />);

    await user.tab();
    expect(screen.getByRole("button", { name: "Payment API" })).toHaveFocus();
    await user.tab();
    expect(document.activeElement).toHaveAttribute("data-freshness");
    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(/Provenance : GitHub/);
  });

  it("says which card is the selected one", () => {
    mount(<EntityCard {...FULL} onClick={() => {}} selected />);

    expect(screen.getByRole("button", { name: "Payment API" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("in compact form shows the icon, the name and a status dot", () => {
    mount(<EntityCard {...FULL} compact />);

    const card = screen.getByRole("article");
    expect(card).toHaveAttribute("data-compact", "true");
    expect(card).toHaveTextContent("Payment API");
    expect(within(card).getByText("Incident")).toBeVisible();
    expect(card).not.toHaveTextContent("Thomas Martin");
    expect(within(card).queryByRole("meter")).toBeNull();
  });

  it("keeps a very long name on one line, whole in its title", () => {
    const name = "a-service-with-a-name-far-too-long-to-fit-on-any-card-in-the-product";
    mount(<EntityCard id="long" type="service" name={name} />);

    expect(screen.getByTitle(name)).toHaveClass("truncate");
  });
});
