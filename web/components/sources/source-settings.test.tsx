/**
 * A source's scope and mapping on its page (LEKA-351).
 *
 * What these protect: a member reads the settings and cannot change them;
 * a line the editor cannot read is named and nothing is sent; "check" shows
 * what the API finds without saving; "save" sends what the lines say, says
 * which version was made and that a full pass follows; a refusal shows each
 * error the API named.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { CatalogEntry, Source } from "@/lib/sources";

const settingsApi = { get: vi.fn(), versions: vi.fn(), check: vi.fn(), save: vi.fn() };
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
let permissions = ["source:read", "source:manage"];

vi.mock("@/lib/source-settings", async (original) => ({
  ...(await original<typeof import("@/lib/source-settings")>()),
  sourceSettings: settingsApi,
}));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: { catalog: vi.fn().mockResolvedValue([{ key: "github" } as CatalogEntry]) },
}));
vi.mock("@/lib/notify", () => ({ notify }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions,
}));

const { SourceSettingsSection } = await import("@/components/sources/source-settings");

const SOURCE = {
  id: "s1",
  type: "github",
  display_name: "Acme GitHub",
  capabilities: ["repositories", "issues"],
} as unknown as Source;

function renderSection() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <SourceSettingsSection source={SOURCE} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

async function openEditor() {
  renderSection();
  await userEvent.click(await screen.findByRole("button", { name: "Modifier le périmètre" }));
  return screen.getByRole("dialog");
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["source:read", "source:manage"];
  settingsApi.get.mockResolvedValue({ version: 0, settings: {} });
  settingsApi.versions.mockResolvedValue({ data: [] });
});

describe("the scope and mapping section", () => {
  it("shows a member the settings, and no way to change them", async () => {
    permissions = ["source:read"];
    settingsApi.get.mockResolvedValue({
      version: 2,
      settings: {
        scope: { include: ["acme/*"], exclude: ["acme/legacy-*"] },
        mapping: { services: [{ match: "acme/pay*", service: "billing" }] },
      },
    });

    renderSection();

    expect(await screen.findByText("acme/legacy-*")).toBeInTheDocument();
    expect(screen.getByText("acme/pay* → billing")).toBeInTheDocument();
    expect(screen.getByText("Version 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Modifier le périmètre" })).not.toBeInTheDocument();
  });

  it("says a source never set keeps everything", async () => {
    renderSection();

    expect(await screen.findByText(/Jamais réglés/)).toBeInTheDocument();
  });

  it("names a line it cannot read, and sends nothing", async () => {
    const dialog = await openEditor();

    await userEvent.type(within(dialog).getByLabelText("Services"), "acme/api");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent("Services : ligne 1 illisible");
    expect(settingsApi.save).not.toHaveBeenCalled();
  });

  it("checks without saving, and shows what the API found", async () => {
    settingsApi.check.mockResolvedValue({
      findings: [
        {
          level: "warning",
          path: "scope.include[0]",
          message: "'acme/apii' matches nothing these credentials can see",
        },
      ],
    });
    const dialog = await openEditor();

    await userEvent.type(within(dialog).getByLabelText("Inclure"), "acme/apii");
    await userEvent.click(within(dialog).getByRole("button", { name: "Vérifier" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent("matches nothing");
    expect(settingsApi.check).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({
        scope: { include: ["acme/apii"], exclude: [] },
      }),
    );
    expect(settingsApi.save).not.toHaveBeenCalled();
  });

  it("saves what the lines say, and says a full pass follows", async () => {
    settingsApi.save.mockResolvedValue({
      version: 3,
      changed: ["scope", "mapping"],
      findings: [],
      full_sync_queued: true,
    });
    const dialog = await openEditor();

    await userEvent.type(within(dialog).getByLabelText("Exclure"), "acme/legacy-*");
    await userEvent.type(within(dialog).getByLabelText("Services"), "acme/pay* → billing");
    await userEvent.selectOptions(within(dialog).getByLabelText("issues"), "incident");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

    const [, sent] = settingsApi.save.mock.calls[0];
    expect(sent.scope).toEqual({ include: [], exclude: ["acme/legacy-*"] });
    expect(sent.mapping.services).toEqual([{ match: "acme/pay*", service: "billing" }]);
    expect(sent.mapping.entity_types).toEqual({ issues: "incident" });
    expect(notify.success).toHaveBeenCalledWith({
      title: "Version 3 enregistrée",
      description: expect.stringContaining("passe complète"),
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows each error the API named when it refuses", async () => {
    settingsApi.save.mockRejectedValue(
      new ApiError(
        422,
        "/sources/s1/settings",
        "These settings have errors in them.",
        "validation_failed",
        {
          scope: "'acme/*' is both included and excluded",
        },
      ),
    );
    const dialog = await openEditor();

    await userEvent.type(within(dialog).getByLabelText("Inclure"), "acme/*");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "both included and excluded",
    );
    expect(notify.error).toHaveBeenCalledWith({ title: "Ces réglages ont des erreurs" });
  });

  it("says the retention kept, and LEKA's policy when there is none (LEKA-348)", async () => {
    permissions = ["source:read"];
    settingsApi.get.mockResolvedValue({
      version: 1,
      settings: { scope: {}, mapping: {} },
      retention_policy_days: 30,
    });

    renderSection();

    expect(await screen.findByText("Politique de LEKA : 30 jours")).toBeInTheDocument();
  });

  it("sends a retention of its own, and refuses one it cannot read", async () => {
    settingsApi.get.mockResolvedValue({ version: 0, settings: {}, retention_policy_days: 30 });
    settingsApi.save.mockResolvedValue({
      version: 1,
      changed: ["retention"],
      findings: [],
      full_sync_queued: false,
    });
    const dialog = await openEditor();
    const field = within(dialog).getByLabelText("Rétention (jours)");

    await userEvent.type(field, "two weeks");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(await within(dialog).findByText("Rétention (jours) : ligne 1 illisible")).toBeVisible();
    expect(settingsApi.save).not.toHaveBeenCalled();

    await userEvent.clear(field);
    await userEvent.type(field, "14");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    const [, sent] = settingsApi.save.mock.calls[0];
    expect(sent.retention).toEqual({ days: 14 });
  });
});
