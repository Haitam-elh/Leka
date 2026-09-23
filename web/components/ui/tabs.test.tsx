/**
 * The rule under test is not "clicking a tab shows its panel" — Base UI
 * owns that, the same way it already owns the Popover and Menu wrapped
 * elsewhere in this file — but that wrapping it here did not lose the
 * keyboard path or the roles a screen reader needs.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";

function Example() {
  return (
    <Tabs defaultValue="sources">
      <TabsList>
        <TabsTab value="sources">Sources</TabsTab>
        <TabsTab value="history">Historique</TabsTab>
      </TabsList>
      <TabsPanel value="sources">Contenu Sources</TabsPanel>
      <TabsPanel value="history">Contenu Historique</TabsPanel>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("marks the tablist, the tabs and the selected one for assistive technology", () => {
    render(<Example />);

    expect(screen.getByRole("tablist")).toBeInTheDocument();
    const sources = screen.getByRole("tab", { name: "Sources" });
    const history = screen.getByRole("tab", { name: "Historique" });
    expect(sources).toHaveAttribute("aria-selected", "true");
    expect(history).toHaveAttribute("aria-selected", "false");
  });

  it("shows only the selected panel", () => {
    render(<Example />);

    expect(screen.getByText("Contenu Sources")).toBeVisible();
    expect(screen.queryByText("Contenu Historique")).not.toBeInTheDocument();
  });

  it("moves focus with the arrow keys and activates on Enter — manual activation, the WAI-ARIA default for a panel that might be expensive to switch to", async () => {
    const user = userEvent.setup();
    render(<Example />);

    await user.tab(); // into the tablist, onto the selected tab
    expect(screen.getByRole("tab", { name: "Sources" })).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Historique" })).toHaveFocus();
    // Arrowing onto a tab moves FOCUS, not selection — the panel must not
    // have switched yet, or every keystroke while browsing the list would
    // trigger whatever a real panel does to load.
    expect(screen.getByRole("tab", { name: "Historique" })).toHaveAttribute(
      "aria-selected",
      "false"
    );
    expect(screen.getByText("Contenu Sources")).toBeVisible();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("tab", { name: "Historique" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByText("Contenu Historique")).toBeVisible();

    // Loops rather than falling off the end — one more test than "it moved
    // once", because a tablist with only two entries would pass that one
    // by accident even without looping.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Sources" })).toHaveFocus();
  });

  it("keeps a disabled tab out of the tab order and unselectable", async () => {
    const user = userEvent.setup();
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTab value="a">A</TabsTab>
          <TabsTab value="b" disabled>
            B
          </TabsTab>
        </TabsList>
        <TabsPanel value="a">Panel A</TabsPanel>
        <TabsPanel value="b">Panel B</TabsPanel>
      </Tabs>
    );

    await user.tab();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "A" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Panel A")).toBeVisible();
  });
});
