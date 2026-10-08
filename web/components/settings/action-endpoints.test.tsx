/**
 * Paramètres → Actions autorisées (LEKA-391).
 *
 * What these protect: the systems LEKA may act through are listed — what
 * each accepts, active or not, when last called; an admin authorizes one
 * and is shown its signing secret once, disables it; anyone else reads.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { ActionEndpoint } from "@/lib/actions";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() }));

vi.mock("@/lib/actions", async (original) => ({
  ...(await original<typeof import("@/lib/actions")>()),
  endpoints: api,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));

const { ActionEndpoints } = await import("@/components/settings/action-endpoints");

const OPS: ActionEndpoint = {
  id: "e1",
  name: "Ops runbooks",
  url: "https://ops.acme.example/leka",
  actions: ["restart"],
  environments: ["production"],
  targets: [],
  enabled: true,
  created_by: null,
  created_at: new Date().toISOString(),
  last_called_at: null,
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <ActionEndpoints />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "workspace:update"];
  api.list.mockResolvedValue([OPS]);
  api.create.mockResolvedValue({ endpoint: { ...OPS, id: "e2", name: "CI" }, secret: "lks_secret" });
  api.update.mockResolvedValue({ ...OPS, enabled: false });
});

describe("authorized actions", () => {
  it("lists what each system accepts, and disables one", async () => {
    const user = userEvent.setup();
    show();
    const line = await screen.findByTestId("endpoint");
    expect(line).toHaveTextContent("Ops runbooks");
    expect(line).toHaveTextContent("https://ops.acme.example/leka");
    expect(line).toHaveTextContent("Redémarrer");
    expect(line).toHaveTextContent("production");
    expect(line).toHaveTextContent("Jamais appelé");
    await user.click(within(line).getByTestId("endpoint-toggle"));
    await waitFor(() => expect(api.update).toHaveBeenCalledWith("e1", { enabled: false }));
  });

  it("authorizes a system, its secret shown once", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByTestId("endpoint-add"));
    await user.type(screen.getByTestId("endpoint-name"), "CI");
    const url = screen.getByTestId("endpoint-url");
    await user.clear(url);
    await user.type(url, "https://ci.acme.example/hooks/leka");
    const environments = screen.getByTestId("endpoint-environments");
    await user.clear(environments);
    await user.type(environments, "staging, production");
    await user.click(screen.getByTestId("endpoint-create"));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith({
        name: "CI",
        url: "https://ci.acme.example/hooks/leka",
        actions: ["restart", "rollback"],
        environments: ["staging", "production"],
        targets: [],
      }),
    );
    const secret = await screen.findByTestId("endpoint-secret");
    expect(secret).toHaveTextContent("lks_secret");
    expect(secret).toHaveTextContent("il ne sera plus affiché");
    await user.click(within(secret).getByTestId("endpoint-secret-close"));
    expect(screen.queryByTestId("endpoint-secret")).not.toBeInTheDocument();
  });

  it("lets anyone else read them", async () => {
    permissions.value = ["workspace:read"];
    show();
    await screen.findByTestId("endpoint");
    expect(screen.queryByTestId("endpoint-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("endpoint-toggle")).not.toBeInTheDocument();
    expect(screen.getByTestId("action-endpoints")).toHaveTextContent(
      "Seuls les admins autorisent un système.",
    );
  });
});
