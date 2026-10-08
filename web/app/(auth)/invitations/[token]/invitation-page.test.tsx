/**
 * Accepting an invitation: signed out, the way to sign in or register and
 * back here; signed in, the seat taken and its workspace entered; a dead
 * invitation said so.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const me = vi.hoisted(() => vi.fn());
const accept = vi.hoisted(() => vi.fn());
const enter = vi.hoisted(() => vi.fn());
const token = vi.hoisted(() => ({ value: "tok-1" }));

vi.mock("next/navigation", () => ({ useParams: () => ({ token: token.value }) }));
vi.mock("@/lib/auth", () => ({ auth: { me } }));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: { accept },
}));
vi.mock("@/lib/workspace", () => ({ workspace: { enter } }));

const { default: InvitationPage } = await import("./page");

function show() {
  return render(
    <LocaleProvider>
      <InvitationPage />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("shows the way in, and back, to who is signed out", async () => {
  token.value = "tok-out";
  me.mockRejectedValue(new ApiError(401, "/auth/me", "Not signed in.", "not_authenticated"));
  show();
  expect(await screen.findByTestId("invitation-login")).toHaveAttribute(
    "href",
    "/login?next=%2Finvitations%2Ftok-out",
  );
  expect(accept).not.toHaveBeenCalled();
});

it("takes the seat and enters its workspace", async () => {
  token.value = "tok-in";
  me.mockResolvedValue({ user: { id: "u" } });
  accept.mockResolvedValue({ id: "m", workspace_id: "w-1" });
  show();
  expect(await screen.findByTestId("invitation-open")).toHaveAttribute("href", "/overview");
  expect(accept).toHaveBeenCalledWith("tok-in");
  await waitFor(() => expect(enter).toHaveBeenCalledWith("w-1"));
});

it("says a dead invitation", async () => {
  token.value = "tok-dead";
  me.mockResolvedValue({ user: { id: "u" } });
  accept.mockRejectedValue(new ApiError(403, "/invitations", "Not valid.", "permission_denied"));
  show();
  expect(await screen.findByText(/Cette invitation ne fonctionne plus/)).toBeInTheDocument();
});
