/**
 * Sécurité & gouvernance › Sessions et accès, Usage des agents (2026-10-25).
 *
 * What these protect: one's signed-in devices, each signed out — or all the
 * others at once —, this one never; LEKA's access to a source revoked once
 * confirmed, by who manages sources only; what LEKA keeps, said; each
 * agent's runs counted over a period, never priced; the journal of who ran
 * which agent, on what, how it ended, fifty at a time.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  sessions: vi.fn(),
  signOut: vi.fn(),
  revoke: vi.fn(),
  usage: vi.fn(),
  journal: vi.fn(),
}));
const sourcesApi = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/security", async (original) => ({
  ...(await original<typeof import("@/lib/security")>()),
  security: api,
}));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/governance", useRouter: () => ({ push: vi.fn() }) }));

const { SecurityTab, deviceOf } = await import("@/components/governance/security-tab");
const { AgentUsageTab } = await import("@/components/governance/agent-usage");

const MAC =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const WINDOWS =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";

function session(id: string, agent: string, current = false) {
  return {
    id,
    created_at: "2026-10-20T08:00:00Z",
    last_seen_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    expires_at: "2026-11-20T08:00:00Z",
    user_agent: agent,
    ip_prefix: "203.0.113.0/24",
    is_current: current,
  };
}

function source(id: string, name: string, hint: string | null) {
  return {
    id,
    display_name: name,
    status: "active",
    credentials: hint ? { hint } : null,
  };
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.sessions.mockResolvedValue({
    data: [session("s1", MAC, true), session("s2", WINDOWS), session("s3", WINDOWS)],
  });
  api.signOut.mockResolvedValue(undefined);
  sourcesApi.list.mockResolvedValue({
    data: [source("c1", "Confluence de la démo", "••••a1b2"), source("g1", "GitHub", null)],
  });
});

describe("Sessions et accès", () => {
  it("names a device as people recognise it", () => {
    expect(deviceOf(MAC)).toBe("Safari · macOS");
    expect(deviceOf(WINDOWS)).toBe("Chrome · Windows");
    expect(deviceOf(null)).toBeNull();
  });

  it("signs out another device, or all the others — never this one", async () => {
    show(<SecurityTab canManageSources />);
    const lines = await screen.findAllByTestId("device-session");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("Safari · macOS");
    expect(lines[0]).toHaveTextContent("Cet appareil");
    expect(within(lines[0]).queryByTestId("device-sign-out")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(within(lines[1]).getByTestId("device-sign-out"));
    await waitFor(() => expect(api.signOut).toHaveBeenCalledWith("s2"));
    api.signOut.mockClear();
    await user.click(screen.getByTestId("device-sign-out-others"));
    await waitFor(() => expect(api.signOut).toHaveBeenCalledTimes(2));
    expect(api.signOut.mock.calls.map((c) => c[0])).toEqual(["s2", "s3"]);
  });

  it("revokes a source's access once confirmed, for who manages sources only", async () => {
    api.revoke.mockResolvedValue({});
    const { unmount } = show(<SecurityTab canManageSources />);
    const lines = await screen.findAllByTestId("source-access-line");
    expect(lines[0]).toHaveTextContent("Identifiants enregistrés : ••••a1b2");
    // Nothing stored: nothing to revoke.
    expect(within(lines[1]).queryByTestId("source-revoke")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(within(lines[0]).getByTestId("source-revoke"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Révoquer l'accès à « Confluence de la démo » ?");
    await user.click(within(dialog).getByRole("button", { name: "Révoquer" }));
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith("c1"));
    unmount();

    show(<SecurityTab canManageSources={false} />);
    await screen.findAllByTestId("source-access-line");
    expect(screen.queryByTestId("source-revoke")).not.toBeInTheDocument();
    expect(screen.getByText(/Seuls les administrateurs des sources/)).toBeInTheDocument();
  });

  it("says what LEKA keeps — the model's calls, never their content", async () => {
    show(<SecurityTab canManageSources />);
    const kept = await screen.findByTestId("security-stored");
    expect(kept).toHaveTextContent("chiffrés : jamais affichés, jamais écrits dans les journaux");
    expect(kept).toHaveTextContent("jamais son contenu");
  });
});

describe("Usage des agents", () => {
  it("counts each agent's runs over a period, never a price, and journals them", async () => {
    api.usage.mockImplementation(async (days: number) => [
      { key: "code-review", title: "Revue de code", runs: days === 30 ? 4 : 9, succeeded: 3, failed: 1, last_at: "2026-10-24T10:00:00Z" },
    ]);
    api.journal.mockResolvedValueOnce(
      Array.from({ length: 50 }, (_, i) => ({
        id: `r${i}`,
        key: "code-review",
        title: "Revue de code",
        by: "u1",
        by_name: "Ada Admin",
        sources: i === 0 ? ["Confluence de la démo"] : [],
        scope: i === 0 ? "ARCHI" : null,
        status: i === 0 ? "failed" : "succeeded",
        queued_at: `2026-10-24T${String(10 + (i % 10)).padStart(2, "0")}:00:00Z`,
        finished_at: null,
        intention_id: i === 0 ? "i1" : null,
      })),
    );
    api.journal.mockResolvedValueOnce([]);
    show(<AgentUsageTab />);
    const row = await screen.findByTestId("agent-usage-row");
    expect(row).toHaveTextContent("Revue de code");
    expect(row).toHaveTextContent("4");
    expect(api.usage).toHaveBeenCalledWith(30);
    expect(screen.getByTestId("agent-usage")).not.toHaveTextContent("€");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("agent-usage-days-90"));
    await waitFor(() => expect(api.usage).toHaveBeenCalledWith(90));
    await waitFor(() => expect(screen.getByTestId("agent-usage-row")).toHaveTextContent("9"));

    const lines = await screen.findAllByTestId("agent-journal-row");
    expect(lines).toHaveLength(50);
    expect(lines[0]).toHaveTextContent("Ada Admin");
    expect(lines[0]).toHaveTextContent("ARCHI · Confluence de la démo");
    expect(lines[0]).toHaveTextContent("Échoué");
    expect(within(lines[0]).getByRole("link", { name: "Revue de code" })).toHaveAttribute(
      "href",
      "/intentions/i1/deliverable?run=r0",
    );
    expect(lines[1]).toHaveTextContent("Toutes les sources connectées");
    // Fifty: more on asking, older than the last shown.
    await user.click(screen.getByTestId("agent-journal-more"));
    await waitFor(() => expect(api.journal).toHaveBeenCalledTimes(2));
    expect(api.journal.mock.calls[1][0]).toBe("2026-10-24T19:00:00Z");
  });
});
