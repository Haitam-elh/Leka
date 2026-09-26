/**
 * DependencyList and EventTimeline: nominal, partial, empty, and large.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type Dependency, DependencyList } from "@/components/knowledge/dependency-list";
import {
  EVENT_TYPES,
  EventTimeline,
  type TimelineEvent,
} from "@/components/knowledge/event-timeline";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const dependency = (index: number, overrides: Partial<Dependency> = {}): Dependency => ({
  entity: { id: `svc-${index}`, type: "service", name: `Service ${index}` },
  direction: index % 2 === 0 ? "upstream" : "downstream",
  ...overrides,
});

describe("DependencyList", () => {
  it("shows each dependency with its direction in words, its status and its detail", () => {
    mount(
      <DependencyList
        items={[
          dependency(0, { status: "attention", detail: "Latence +32 %" }),
          dependency(1, { status: "operational", detail: "Aucun impact détecté" }),
        ]}
      />,
    );

    const [upstream, downstream] = screen.getAllByRole("listitem");
    expect(upstream).toHaveTextContent("Service 0");
    expect(upstream).toHaveTextContent("Dépend de · Latence +32 %");
    expect(within(upstream).getByText("Attention")).toBeVisible();
    expect(downstream).toHaveTextContent("Utilisé par · Aucun impact détecté");
  });

  it("works with nothing but the entity and the direction", () => {
    mount(<DependencyList items={[dependency(0)]} />);

    const row = screen.getByRole("listitem");
    expect(row).toHaveTextContent("Service 0");
    expect(row).toHaveTextContent("Dépend de");
  });

  it("says so when there is none", () => {
    mount(<DependencyList items={[]} />);

    expect(screen.getByText("Aucune dépendance connue.")).toBeVisible();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows maxVisible, then the rest on demand — 500 of them", async () => {
    const user = userEvent.setup();
    mount(<DependencyList items={Array.from({ length: 500 }, (_, i) => dependency(i))} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    const more = screen.getByRole("button", { name: "Voir 495 de plus" });
    expect(more).toHaveAttribute("aria-expanded", "false");

    await user.click(more);
    expect(screen.getAllByRole("listitem")).toHaveLength(500);
    expect(screen.getByRole("button", { name: "Voir moins" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("opens a dependency from its name, keyboard included", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    mount(<DependencyList items={[dependency(3)]} onSelect={onSelect} />);

    await user.tab();
    expect(screen.getByRole("button", { name: "Service 3" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("svc-3");
  });
});

const event = (index: number, minutesAgo: number, type = EVENT_TYPES[index % 7]): TimelineEvent => ({
  id: `evt-${index}`,
  type,
  title: `Événement ${index}`,
  at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
});

describe("EventTimeline", () => {
  it("lists the events newest first, whatever order they come in", () => {
    mount(<EventTimeline events={[event(1, 30), event(2, 5), event(3, 60)]} />);

    const titles = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(titles[0]).toContain("Événement 2");
    expect(titles[2]).toContain("Événement 3");
    expect(screen.getByRole("list").tagName).toBe("OL");
  });

  it.each(EVENT_TYPES)("names the %s type in words", (type) => {
    mount(<EventTimeline events={[event(0, 1, type)]} />);

    expect(screen.getByRole("listitem")).toHaveAttribute("data-event-type", type);
  });

  it("puts the moment in a real <time> element", () => {
    const at = "2026-09-25T14:02:00Z";
    mount(<EventTimeline events={[{ id: "d", type: "deployment", title: "v2.8.4", at }]} />);

    expect(screen.getByRole("listitem").querySelector("time")).toHaveAttribute("dateTime", at);
  });

  it("shows the subtitle and the kind, or in compact form only the title — kind kept for screen readers", () => {
    const withSubtitle = { ...event(0, 1, "deployment"), subtitle: "GitHub · Commit a1b3c4d" };
    const { unmount } = mount(<EventTimeline events={[withSubtitle]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("GitHub · Commit a1b3c4d");
    expect(screen.getByRole("listitem")).toHaveTextContent("Déploiement");
    unmount();

    mount(<EventTimeline events={[withSubtitle]} compact />);
    expect(screen.getByRole("listitem")).not.toHaveTextContent("GitHub · Commit a1b3c4d");
    expect(screen.getByText(", Déploiement")).toHaveClass("sr-only");
  });

  it("says so when there is nothing", () => {
    mount(<EventTimeline events={[]} />);

    expect(screen.getByText("Aucun événement pour l'instant.")).toBeVisible();
  });

  it("holds 500 events behind 'Voir tout', and selects one from the keyboard", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const many = Array.from({ length: 500 }, (_, i) => event(i, i));
    mount(<EventTimeline events={many} maxVisible={5} onSelect={onSelect} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Voir tout (500)" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(500);

    screen.getByRole("button", { name: "Événement 0" }).focus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("evt-0");
  });
});
