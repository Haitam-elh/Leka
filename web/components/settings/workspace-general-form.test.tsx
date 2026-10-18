/**
 * Paramètres → Votre espace (LEKA-502): what the workspace holds is what the
 * form shows; saved, exactly what was chosen is sent, and the form then says
 * what the server kept — the header renamed too; a refusal said on its
 * field, the typed value still there, never « enregistré »; the identifier
 * shown, never editable; a member reads and changes nothing.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { WorkspaceRead } from "@/lib/workspace";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const api = vi.hoisted(() => ({ current: vi.fn(), configure: vi.fn() }));
const rename = vi.hoisted(() => vi.fn());
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/workspace", () => ({ workspace: api }));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useRenameWorkspace: () => rename,
}));

const { WorkspaceGeneralForm } = await import("@/components/settings/workspace-general-form");

const SAVED: WorkspaceRead = {
  id: "w1",
  name: "Acme Corp",
  slug: "acme",
  status: "active",
  settings: { timezone: "Europe/London", default_environment: "staging", default_period: { preset: "30d" } },
  default_language: "fr",
  created_at: "2026-10-01T00:00:00Z",
  demo: false,
};

const show = () =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <WorkspaceGeneralForm />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );

beforeEach(() => {
  permissions.value = ["workspace:read", "workspace:update"];
  api.current.mockReset().mockResolvedValue({ workspace: SAVED, role: "admin", permissions: [] });
  api.configure.mockReset();
  rename.mockReset();
  notices.success.mockReset();
});

describe("Votre espace", () => {
  it("shows what the workspace holds, saves what was chosen, then what the server kept", async () => {
    api.configure.mockResolvedValue({ ...SAVED, name: "Acme Corporation" });
    const user = userEvent.setup();
    show();

    const name = await screen.findByLabelText("Nom de l'espace");
    expect(name).toHaveValue("Acme Corp");
    expect(screen.getByTestId("settings-slug")).toHaveTextContent("acme");
    expect(screen.queryByLabelText("Identifiant")).toBeNull();

    await user.clear(name);
    await user.type(name, "Acme Corporation");
    await user.click(screen.getByTestId("settings-save"));

    await waitFor(() =>
      expect(api.configure).toHaveBeenCalledWith({
        name: "Acme Corporation",
        settings: {
          timezone: "Europe/London",
          default_environment: "staging",
          default_period: { preset: "30d", from: null, to: null },
        },
      }),
    );
    expect(rename).toHaveBeenCalledWith("Acme Corporation");
    expect(notices.success).toHaveBeenCalled();
    // Nothing left to save: the form holds what was kept.
    await waitFor(() => expect(screen.getByTestId("settings-save")).toBeDisabled());
  });

  it("a refusal said on its field, the typed name still there, never « enregistré »", async () => {
    api.configure.mockRejectedValue(
      new ApiError(422, "/workspaces/current", "refused", "validation_failed", { name: "Nom refusé." }),
    );
    const user = userEvent.setup();
    show();

    const name = await screen.findByLabelText("Nom de l'espace");
    await user.clear(name);
    await user.type(name, "Acme 2");
    await user.click(screen.getByTestId("settings-save"));

    expect(await screen.findAllByText("Nom refusé.")).not.toHaveLength(0);
    expect(name).toHaveValue("Acme 2");
    expect(notices.success).not.toHaveBeenCalled();
    expect(rename).not.toHaveBeenCalled();
  });

  it("a member reads, changes nothing", async () => {
    permissions.value = ["workspace:read"];
    show();

    expect(await screen.findByLabelText("Nom de l'espace")).toBeDisabled();
    expect(screen.queryByTestId("settings-save")).toBeNull();
    expect(screen.getByTestId("settings-admin-only")).toBeInTheDocument();
  });
});
