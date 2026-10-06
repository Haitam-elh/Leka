/**
 * The sidebar's counts (LEKA-380): beside À valider, how many proposals
 * wait — for who may decide, and only when there are some.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/lib/query";

const summary = vi.hoisted(() => vi.fn());
const permissions = vi.hoisted(() => ({ value: [] as string[] }));

vi.mock("@/lib/enrichment", async (original) => ({
  ...(await original<typeof import("@/lib/enrichment")>()),
  enrichment: { summary },
}));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => permissions.value }));

const { useNavBadges } = await import("@/lib/nav-badges");

function badges() {
  const client = makeQueryClient();
  return renderHook(() => useNavBadges(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
}

const WAITING = { proposed: 3, accepted: 1, rejected: 0, withdrawn: 0, by_policy: 0, families: {} };

beforeEach(() => {
  summary.mockReset().mockResolvedValue(WAITING);
});

describe("the sidebar's counts", () => {
  it("counts the proposals waiting, for who may decide", async () => {
    permissions.value = ["workspace:read", "intention:approve"];
    const { result } = badges();
    await waitFor(() => expect(result.current).toEqual({ approvals: 3 }));
  });

  it("shows none to who may not, and asks nothing", () => {
    permissions.value = ["workspace:read"];
    const { result } = badges();
    expect(result.current).toEqual({});
    expect(summary).not.toHaveBeenCalled();
  });

  it("shows none when nothing waits", async () => {
    permissions.value = ["intention:approve"];
    summary.mockResolvedValue({ ...WAITING, proposed: 0 });
    const { result } = badges();
    await waitFor(() => expect(summary).toHaveBeenCalled());
    expect(result.current).toEqual({});
  });
});
