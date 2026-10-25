/**
 * « Contrat » (2026-10-25): what « Facturation » is under an Enterprise
 * contract.
 *
 * What these protect: its type and since when, the organisation, its
 * members — one click from Équipe —, its dedicated contact, what it
 * includes, its dedicated agents named; never a price, never credits. Its
 * logo: its name by default; given by its admin — a PNG, JPEG or WebP image,
 * 512 KB at most, refused before anything is sent otherwise —, removed; read
 * only by a member.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const fetched = vi.hoisted(() => vi.fn());
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  apiFetch: fetched,
}));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => permissions.value }));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("next/navigation", () => ({ usePathname: () => "/billing", useRouter: () => ({ push: vi.fn() }) }));

const { ContractScreen } = await import("@/components/billing/contract-page");

const CONTRACT = {
  type: "enterprise",
  organisation: "Globex",
  since: "2026-10-25",
  members: 3,
  contact: { name: "Ada Lovelace", email: "ada@leka.example" },
};

function answers(logo: object | null) {
  fetched.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/billing/contract") return CONTRACT;
    if (path === "/billing/add-ons") return { plan: "enterprise", agents: [], bundles: [], dedicated: ["application-architecture"] };
    if (path === "/workspaces/current" && !init?.method) {
      return { workspace: { id: "w1", name: "Globex", settings: logo ? { logo } : {} }, role: "admin", permissions: [] };
    }
    if (path === "/workspaces/current/logo") return init?.method === "DELETE" ? undefined : { settings: {} };
    throw new Error(`unexpected ${path}`);
  });
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ContractScreen />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "workspace:update"];
  answers(null);
});

describe("Contrat", () => {
  it("says the contract — never a price, never credits", async () => {
    show();
    const page = await screen.findByTestId("contract");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Contrat");
    expect(screen.getByTestId("contract-type")).toHaveTextContent("Entreprise");
    expect(screen.getByTestId("contract-type")).toHaveTextContent("Depuis le 25 octobre 2026");
    expect(screen.getByTestId("contract-organisation")).toHaveTextContent("Globex");
    expect(screen.getByTestId("contract-members")).toHaveTextContent("3");
    expect(screen.getByTestId("contract-members")).toHaveAttribute("href", "/team");
    expect(screen.getByTestId("contract-contact")).toHaveTextContent("Ada Lovelace");
    expect(screen.getByTestId("contract-contact")).toHaveTextContent("ada@leka.example");
    await waitFor(() =>
      expect(screen.getByTestId("contract-includes")).toHaveTextContent("Vos agents dédiés : Architecte applicatif"),
    );
    expect(page).not.toHaveTextContent("€");
    expect(page).not.toHaveTextContent(/crédit/i);
  });

  it("its logo: its name by default, given by its admin — checked before anything is sent", async () => {
    const user = userEvent.setup({ applyAccept: false });
    show();
    expect(await screen.findByTestId("contract-logo-text")).toHaveTextContent("Globex");
    const input = screen.getByTestId("contract-logo-input") as HTMLInputElement;
    // What it cannot keep: said, nothing sent.
    await user.upload(input, new File(["<svg/>"], "logo.svg", { type: "image/svg+xml" }));
    expect(notices.error).toHaveBeenCalledWith({ title: "Format non pris en charge : PNG, JPEG ou WebP." });
    await user.upload(input, new File([new Uint8Array(512 * 1024 + 1)], "big.png", { type: "image/png" }));
    expect(notices.error).toHaveBeenCalledWith({ title: "Image trop lourde : 512 Ko au plus." });
    expect(fetched).not.toHaveBeenCalledWith("/workspaces/current/logo", expect.anything());
    // A PNG: sent as it is.
    const png = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "logo.png", { type: "image/png" });
    await user.upload(input, png);
    await waitFor(() =>
      expect(fetched).toHaveBeenCalledWith("/workspaces/current/logo", {
        method: "PUT",
        body: png,
        headers: { "Content-Type": "image/png" },
      }),
    );
    expect(notices.success).toHaveBeenCalledWith({ title: "Logo enregistré" });
  });

  it("a logo given: shown, removed in one click — read only by a member", async () => {
    answers({ key: "w1/branding/logo.png", type: "image/png", updated_at: "2026-10-25T10:00:00Z" });
    const user = userEvent.setup();
    const { unmount } = show();
    const image = await screen.findByTestId("contract-logo-image");
    expect(image).toHaveAttribute("alt", "Logo de Globex");
    expect(image.getAttribute("src")).toContain("/workspaces/current/logo?v=2026-10-25T10%3A00%3A00Z");
    await user.click(screen.getByTestId("contract-logo-remove"));
    await waitFor(() => expect(fetched).toHaveBeenCalledWith("/workspaces/current/logo", { method: "DELETE" }));
    unmount();

    permissions.value = ["workspace:read"];
    show();
    await screen.findByTestId("contract-logo-image");
    expect(screen.queryByTestId("contract-logo-give")).not.toBeInTheDocument();
    expect(screen.queryByTestId("contract-logo-remove")).not.toBeInTheDocument();
    expect(screen.getByTestId("contract-logo")).toHaveTextContent("Seul un administrateur");
  });
});
