/**
 * StatusBadge: every state in the product, one component.
 *
 * What these protect: every variant renders with its own word (colour is
 * never the only signal), the families that share a value stay apart, and
 * the badge is announced only when asked to be.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/knowledge/status-badge";
import { STATUS_VARIANTS, statusLabel, statusLook } from "@/components/knowledge/status";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const fr = DICTIONARIES.fr;

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

describe("StatusBadge", () => {
  it.each(STATUS_VARIANTS)("renders %s with its own word", (variant) => {
    mount(<StatusBadge variant={variant} />);

    const badge = screen.getByText(statusLabel(fr, variant));
    expect(badge).toHaveAttribute("data-variant", variant);
    expect(badge).toHaveAttribute("data-tone", statusLook(variant).tone);
    expect(badge.textContent?.trim()).not.toBe("");
  });

  it("covers every family the ticket names, and the overview's", () => {
    const families = new Set(STATUS_VARIANTS.map((variant) => variant.split(".")[0]));
    expect([...families].sort()).toEqual(
      ["connector", "entity", "health", "priority", "severity", "source", "sync"].sort(),
    );
  });

  it("keeps apart the families that share a word", () => {
    mount(
      <>
        <StatusBadge variant="health.degraded" />
        <StatusBadge variant="connector.degraded" />
        <StatusBadge variant="entity.unknown" />
      </>,
    );

    expect(screen.getAllByText("Dégradé")).toHaveLength(2);
    expect(screen.getByText("Inconnu")).toHaveAttribute("data-variant", "entity.unknown");
  });

  it("takes a word of its own, and keeps the variant's tone", () => {
    mount(<StatusBadge variant="entity.incident" label="INC-2841" />);

    expect(screen.getByText("INC-2841")).toHaveAttribute("data-tone", "danger");
  });

  it("shows a dot instead of the icon when asked, still with its word", () => {
    const { container } = mount(<StatusBadge variant="entity.operational" dot />);

    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("Opérationnel")).toBeVisible();
  });

  it("is announced only when it is live", () => {
    mount(
      <>
        <StatusBadge variant="sync.running" live />
        <StatusBadge variant="sync.idle" />
      </>,
    );

    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Synchronisation…");
  });

  it("hides its icon from screen readers, which read the word", () => {
    const { container } = mount(<StatusBadge variant="severity.critical" />);

    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
