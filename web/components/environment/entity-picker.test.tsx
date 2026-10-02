/**
 * The entity picker (LEKA-369): a search of the company model, as a
 * combobox.
 *
 * What these protect: nothing is asked under two letters, nor before the
 * typing pauses; each hit says its kind and where it is; the keyboard moves
 * through the hits — the active one announced — and Enter picks it; a click
 * picks too; nothing found says so.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { EntityBrief, SearchResults } from "@/lib/knowledge-graph";
import { makeQueryClient } from "@/lib/query";

const graphApi = { search: vi.fn() };

vi.mock("@/lib/knowledge-graph", async (original) => ({
  ...(await original<typeof import("@/lib/knowledge-graph")>()),
  knowledgeGraph: graphApi,
}));

const { EntityPicker } = await import("@/components/environment/entity-picker");

const brief = (id: string, type: EntityBrief["type"], name: string): EntityBrief => ({
  id,
  type,
  key: `${type}:${id}`,
  name,
  lifecycle: "active",
});

const FOUND: SearchResults = {
  query: "pay",
  entities: [
    {
      entity: brief("s1", "service", "Payment API"),
      score: 3.1,
      holder: brief("a1", "application", "Shop"),
      sources: ["pagerduty"],
    },
    { entity: brief("t1", "team", "Payments"), score: 1.1, holder: null, sources: [] },
  ],
  relationships: [],
};

function mount(onPick = vi.fn()) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <EntityPicker label="Centrer sur" placeholder="Rechercher…" onPick={onPick} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
  return onPick;
}

beforeEach(() => {
  vi.clearAllMocks();
  graphApi.search.mockResolvedValue(FOUND);
});

describe("the entity picker", () => {
  it("asks nothing for a single letter", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByRole("combobox", { name: "Centrer sur" }), "p");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(graphApi.search).not.toHaveBeenCalled();
  });

  it("asks once the typing pauses, and says each hit's kind and where it is", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByRole("combobox"), "pay");

    const list = within(await screen.findByRole("listbox", { name: "Centrer sur" }));
    const [api, team] = await list.findAllByRole("option");
    expect(api).toHaveTextContent("Payment API");
    expect(api).toHaveTextContent("Service · Shop");
    expect(team).toHaveTextContent("Équipe");
    // One request for the word, not one a letter.
    expect(graphApi.search).toHaveBeenCalledTimes(1);
    expect(graphApi.search).toHaveBeenCalledWith("pay", { limit: 8 });
  });

  it("moves through the hits from the keyboard, the active one announced, and picks it", async () => {
    const user = userEvent.setup();
    const onPick = mount();
    const input = screen.getByRole("combobox");

    await user.type(input, "pay");
    const [first, second] = await screen.findAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", second.id);
    expect(second).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}{Enter}");

    expect(onPick).toHaveBeenCalledWith(FOUND.entities[1]);
    expect(input).toHaveValue("");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("picks a hit clicked", async () => {
    const user = userEvent.setup();
    const onPick = mount();

    await user.type(screen.getByRole("combobox"), "pay");
    await user.click(await screen.findByRole("option", { name: /Payment API/ }));

    expect(onPick).toHaveBeenCalledWith(FOUND.entities[0]);
  });

  it("says when nothing matches", async () => {
    const user = userEvent.setup();
    graphApi.search.mockResolvedValue({ ...FOUND, entities: [] });
    mount();

    await user.type(screen.getByRole("combobox"), "zzz");

    await waitFor(() =>
      expect(screen.getByRole("listbox")).toHaveTextContent("Aucun élément ne correspond."),
    );
  });
});
