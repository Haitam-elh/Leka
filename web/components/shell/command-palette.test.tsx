/**
 * The palette: find and go, entirely from the keyboard.
 *
 * The rule under test is not only that search works — it finds the company
 * model's things since LEKA-369 — but that the palette never becomes a
 * second, worse place to ask LEKA a question. Typing one offers to create
 * an intention; it never answers.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { SearchProvider } from "@/lib/search";

const push = vi.hoisted(() => vi.fn());
const OWNER = vi.hoisted(() => [
  "workspace:read", "workspace:update", "member:read", "member:invite",
  "source:read", "intention:read", "intention:create", "intention:approve",
]);
const MEMBER = vi.hoisted(() => [
  "workspace:read", "member:read", "source:read", "intention:read", "intention:create",
]);
const permissions = vi.hoisted(() => ({ value: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/overview",
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  auth: {
    me: vi.fn().mockResolvedValue({
      user: { id: "u1", email: "nora@acme.example", email_verified_at: null, last_login_at: null },
      workspaces: [{ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }],
      active_workspace_id: "w1",
    }),
    logout: vi.fn(),
  },
}));

vi.mock("@/lib/workspace", () => ({
  workspace: {
    current: vi.fn(async () => ({
      workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
      role: "owner",
      permissions: permissions.value,
    })),
  },
}));

const { CommandPalette, useCommandShortcut } = await import(
  "@/components/shell/command-palette"
);
const { ShellProvider } = await import("@/components/shell/shell-provider");

const fr = DICTIONARIES.fr;

async function openPalette(search?: SearchProvider) {
  const user = userEvent.setup();
  render(
    <LocaleProvider>
      <ShellProvider>
        <CommandPalette open onOpenChange={vi.fn()} search={search} />
      </ShellProvider>
    </LocaleProvider>,
  );
  // The palette lists what this person may open, which arrives from the API.
  await screen.findByTestId("palette-sources");
  return user;
}

beforeEach(() => {
  push.mockClear();
  permissions.value = OWNER;
});

describe("what the palette offers", () => {
  it("puts creating an intention first, before anywhere to go", async () => {
    await openPalette();

    const options = screen.getAllByRole("option");

    expect(options[0]).toHaveTextContent(fr.palette.createIntention);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("offers the pages this person may open, and no others", async () => {
    permissions.value = MEMBER;
    await openPalette();

    expect(screen.getByTestId("palette-sources")).toBeVisible();
    // A member may never open billing; offering it would be a link that refuses.
    expect(screen.queryByTestId("palette-billing")).not.toBeInTheDocument();
  });

  it("filters as you type", async () => {
    const user = await openPalette();

    await user.type(screen.getByTestId("palette-input"), "sourc");

    expect(screen.getByTestId("palette-sources")).toBeVisible();
    expect(screen.queryByTestId("palette-activity")).not.toBeInTheDocument();
  });

  it("names a page with its pillar, so typing the pillar lists its pages", async () => {
    const user = await openPalette();

    await user.type(screen.getByTestId("palette-input"), "environnement");

    const applications = screen.getByTestId("palette-environment-applications");
    expect(applications).toHaveTextContent("Mon environnement › Applications");
    await user.click(applications);
    expect(push).toHaveBeenCalledWith("/environment?tab=applications");
    expect(screen.queryByTestId("palette-sources")).not.toBeInTheDocument();
  });

  it("offers creating an intention once, as the action", async () => {
    await openPalette();

    expect(screen.queryByTestId("palette-intention-new")).not.toBeInTheDocument();
  });

  it("carries what was typed into the intention it offers to create", async () => {
    const user = await openPalette();

    await user.type(screen.getByTestId("palette-input"), "pourquoi l'API est lente ?");

    const action = screen.getByTestId("palette-create-intention");
    expect(action).toHaveTextContent("pourquoi l'API est lente ?");
  });

  it("says it does not answer questions, rather than answering badly", async () => {
    const user = await openPalette();

    await user.type(screen.getByTestId("palette-input"), "pourquoi le paiement est lent ?");

    const empty = screen.getByTestId("palette-no-results");
    expect(within(empty).getByText(fr.palette.noResults)).toBeVisible();
    expect(within(empty).getByText(fr.palette.searchHint)).toBeVisible();
  });
});

describe("what the company model knows", () => {
  const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

  it("lists what the search finds, each to its page — once the typing pauses", async () => {
    const search = vi.fn<SearchProvider>().mockResolvedValue([
      {
        id: PAYMENT,
        label: "Payment API — Shop",
        kind: "Service",
        href: `/environment/services/${PAYMENT}`,
      },
    ]);
    const user = await openPalette(search);

    await user.type(screen.getByTestId("palette-input"), "payment");

    const found = await screen.findByTestId(`palette-${PAYMENT}`);
    expect(found).toHaveTextContent("Payment API — Shop · Service");
    // One search for the word, not one a letter.
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith("payment");
    await user.click(found);
    expect(push).toHaveBeenCalledWith(`/environment/services/${PAYMENT}`);
  });

  it("still offers the intention first when something is found", async () => {
    const search = vi.fn<SearchProvider>().mockResolvedValue([
      { id: PAYMENT, label: "Payment API", kind: "Service", href: "/x" },
    ]);
    const user = await openPalette(search);

    await user.type(screen.getByTestId("palette-input"), "payment");

    await waitFor(() =>
      expect(screen.getAllByRole("option").at(-1)).toHaveTextContent("Payment API"),
    );
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("payment");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });
});

describe("the keyboard", () => {
  it("moves through the list and opens what is highlighted", async () => {
    const user = await openPalette();

    await user.keyboard("{ArrowDown}{Enter}");

    // The second item is the first place to go: the overview.
    expect(push).toHaveBeenCalledWith("/overview");
  });

  it("creates an intention with the typed text on Enter", async () => {
    const user = await openPalette();

    await user.type(screen.getByTestId("palette-input"), "migrer vers AWS");
    await user.keyboard("{Enter}");

    expect(push).toHaveBeenCalledWith("/intentions/new?q=migrer%20vers%20AWS");
  });
});

describe("the shortcut", () => {
  function Harness() {
    const open = vi.fn();
    openSpy = open;
    useCommandShortcut(open);
    return <input data-testid="somewhere-to-type" />;
  }
  let openSpy = vi.fn();

  it("opens the palette from anywhere", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.keyboard("{Meta>}k{/Meta}");

    expect(openSpy).toHaveBeenCalledOnce();
  });

  it("stays out of the way while someone is typing", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByTestId("somewhere-to-type"));
    await user.keyboard("{Control>}k{/Control}");

    // Stealing this keystroke would interrupt whoever is writing an
    // intention, which is the one thing the product asks people to do.
    expect(openSpy).not.toHaveBeenCalled();
  });
});
