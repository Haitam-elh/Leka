/**
 * Step 1 of "Nouvelle intention" (LEKA-341): what it offers to read and
 * where to look is the workspace's own.
 *
 * What these protect: the sources listed are the ones the workspace has
 * connected and can read — a broken one is not offered — each with its
 * tool and what kind of thing it holds, each box named by its source, all
 * ticked once they arrive; none connected says so and leads to connecting
 * one; the environments and the services are those the company model
 * knows, "Tous les environnements" first and production chosen when there
 * is one. Nothing invented.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
}));

const sourcesApi = { list: vi.fn() };
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));

const environmentApi = { get: vi.fn(), sheet: vi.fn() };
vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: environmentApi,
}));

const { IntentionForm } = await import("@/components/intentions/intention-form");

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <IntentionForm />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function node(id: string, name: string, type = "service") {
  return { id, type, layer: "services", name, status: null, entity_id: id, key: null };
}

beforeEach(() => {
  vi.clearAllMocks();
  sourcesApi.list.mockResolvedValue({
    data: [
      { id: "s1", type: "github", display_name: "acme/backend", status: "active" },
      { id: "s2", type: "jira", display_name: "OPS board", status: "degraded" },
      { id: "s3", type: "slack", display_name: "#incidents", status: "error" },
    ],
    next_cursor: null,
  });
  environmentApi.get.mockResolvedValue({
    environments: ["production", "staging"],
    nodes: [
      node("e1", "payment-api"),
      node("e2", "auth-service"),
      node("e3", "postgres-prod", "database"),
    ],
  });
});

describe("the new intention's context and scope", () => {
  it("offers the sources the workspace can read, each said, all ticked once they arrive", async () => {
    show();

    const backend = await screen.findByText("acme/backend");
    const list = backend.closest('[role="group"]') as HTMLElement;
    expect(list).toHaveTextContent("GitHub · Développement");
    expect(list).toHaveTextContent("OPS board");
    // Broken: nothing to read from it.
    expect(list).not.toHaveTextContent("#incidents");
    // Each box named by its own source, not by the panel: GitHub is not Jira.
    expect(within(list).getAllByRole("checkbox")).toHaveLength(2);
    expect(await screen.findByRole("checkbox", { name: "acme/backend" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "OPS board" })).toBeChecked();
  });

  it("says when none is connected, and leads to connecting one", async () => {
    sourcesApi.list.mockResolvedValue({ data: [], next_cursor: null });
    show();

    const empty = await screen.findByTestId("intention-no-sources");
    expect(empty).toHaveTextContent("Aucune source connectée");
    expect(within(empty).getByRole("link", { name: "Connecter une source" })).toHaveAttribute(
      "href",
      "/sources",
    );
  });

  it("scopes to the environments and services the company model knows", async () => {
    const user = userEvent.setup();
    show();

    const scope = screen.getByRole("heading", { name: "Périmètre de l'analyse" })
      .parentElement?.parentElement as HTMLElement;
    // Production, once the model says there is one; every service until narrowed.
    expect(await within(scope).findByText("Production")).toBeInTheDocument();
    expect(scope).toHaveTextContent("Tous les services");

    await user.click(within(scope).getByRole("button", { name: "Modifier" }));
    await user.click(within(scope).getByRole("combobox", { name: /Environnement/ }));
    const environments = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(environments).toEqual(["Tous les environnements", "Production", "Staging"]);
  });
});
