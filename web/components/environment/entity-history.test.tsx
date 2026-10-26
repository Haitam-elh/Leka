/**
 * A thing's Historique (LEKA-383): its course, as the model recorded it.
 *
 * What these protect: every version, the latest first, with each field it
 * changed — from what, to what — and its first said as the first LEKA
 * knew; its relationships that came and went, as sentences leading to
 * each end; what it was at a moment — its attributes and its ties then, a
 * warning where the history does not reach, and nothing invented before
 * it was known; who may approve restores a version, with a reason, and
 * undoes a restore; nobody else sees either; a history that cannot be
 * read says so.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EntityAt, EntityHistory } from "@/lib/evolution";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  history: vi.fn(),
  at: vi.fn(),
  restore: vi.fn(),
  undo: vi.fn(),
  rebuild: vi.fn(),
  snapshots: vi.fn(),
}));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:approve"] }));
const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

vi.mock("@/lib/evolution", async (original) => ({
  ...(await original<typeof import("@/lib/evolution")>()),
  evolution: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: ME, email: "nora@acme.example" }),
}));
vi.mock("@/lib/notify", () => ({ notify }));

const { EntityHistory: History } = await import("@/components/environment/entity-history");

const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const USERS = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const OPERATION = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const brief = (id: string, name: string) => ({
  id,
  type: "service" as const,
  key: `svc-${name}`,
  name,
  lifecycle: "active" as const,
});

function version(number: number, change: string, fields: [string, unknown, unknown][]) {
  return {
    id: crypto.randomUUID(),
    entity_id: PAYMENT,
    entity: brief(PAYMENT, "payment-api"),
    name: "payment-api",
    version: number,
    change,
    fields: fields.map(([field, before, after]) => ({ field, before, after })),
    recorded_at: `2026-09-${String(10 + number * 5).padStart(2, "0")}T12:00:00Z`,
    run_id: null,
  };
}

const HISTORY = {
  entity: brief(PAYMENT, "payment-api"),
  versions: [
    version(3, "changed", [["attributes.version", "2.8.3", "2.8.4"]]),
    version(2, "changed", [
      ["attributes.version", "2.8.2", "2.8.3"],
      ["attributes.team", null, "payments"],
    ]),
    version(1, "created", []),
  ],
  relationships: [
    {
      id: crypto.randomUUID(),
      type: "depends_on",
      change: "added",
      from_entity: brief(PAYMENT, "payment-api"),
      to_entity: brief(USERS, "user-service"),
      before: null,
      after: { origin: "stated" },
      recorded_at: "2026-09-27T12:00:00Z",
      run_id: null,
    },
  ],
  operations: [
    {
      id: OPERATION,
      kind: "restore",
      status: "applied",
      entity_id: PAYMENT,
      entity_name: "payment-api",
      entity: null,
      version: 2,
      detail: { attributes: { version: { before: "2.8.4", after: "2.8.3" } } },
      reason: "Rollback",
      requested_by: ME,
      created_at: "2026-10-06T12:00:00Z",
      finished_at: "2026-10-06T12:00:00Z",
      run_id: null,
      undone_by: null,
      undone_at: null,
    },
  ],
  horizon: null,
} as unknown as EntityHistory;

const AT = {
  entity: brief(PAYMENT, "payment-api"),
  moment: "2026-09-20T12:00:00Z",
  existed: true,
  version: null,
  content: { name: "payment-api", attributes: { version: "2.8.2", sla: "99.95" }, lifecycle: "active" },
  relationships: [
    {
      type: "depends_on",
      direction: "outgoing",
      other: brief(USERS, "auth-service"),
      origin: "stated",
      confidence: 1,
    },
  ],
  complete: false,
} as unknown as EntityAt;

function mount() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <History entityId={PAYMENT} name="payment-api" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:approve"];
  api.history.mockResolvedValue(HISTORY);
  api.at.mockResolvedValue(AT);
  api.restore.mockResolvedValue(HISTORY.operations[0]);
  api.undo.mockResolvedValue({ ...HISTORY.operations[0], status: "undone" });
});

describe("Historique", () => {
  it("shows each version against the one before, the latest first", async () => {
    mount();
    const latest = await screen.findByTestId("history-version-3");
    expect(latest).toHaveTextContent("Version 3");
    expect(latest).toHaveTextContent("Actuelle");
    expect(latest).toHaveTextContent("version2.8.3 → 2.8.4");
    const second = screen.getByTestId("history-version-2");
    expect(second).toHaveTextContent("team- → payments");
    expect(screen.getByTestId("history-version-1")).toHaveTextContent(
      "Première version connue de LEKA",
    );
    // The current version is not restored.
    expect(within(latest).queryByRole("button", { name: "Restaurer" })).not.toBeInTheDocument();
  });

  it("says the relationships that came and went", async () => {
    mount();
    const ties = await screen.findByTestId("history-relationships");
    expect(ties).toHaveTextContent("payment-api dépend de user-service");
    expect(within(ties).getByRole("link", { name: "user-service" })).toHaveAttribute(
      "href",
      `/environment/services/${USERS}`,
    );
  });

  it("shows what it was at a moment, and where the history stops", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(
      within(await screen.findByTestId("history-version-2")).getByRole("button", {
        name: "Voir à cette date",
      }),
    );
    const at = await screen.findByTestId("history-at");
    await waitFor(() => expect(at).toHaveTextContent("version2.8.2"));
    expect(at).toHaveTextContent("payment-api dépend de auth-service");
    expect(at).toHaveTextContent("L'historique des relations ne remonte pas jusque-là");
    expect(api.at).toHaveBeenCalledWith(PAYMENT, "2026-09-20T12:00:00Z");
  });

  it("says nothing of a thing not yet known then", async () => {
    api.at.mockResolvedValueOnce({ ...AT, existed: false, content: null, relationships: [] });
    const user = userEvent.setup();
    mount();
    await user.click(
      within(await screen.findByTestId("history-version-1")).getByRole("button", {
        name: "Voir à cette date",
      }),
    );
    expect(
      await screen.findByText("payment-api n'était pas encore connu de LEKA à cette date."),
    ).toBeInTheDocument();
  });

  it("lets who may approve restore a version, with a reason, and undo it", async () => {
    const user = userEvent.setup();
    mount();
    const second = await screen.findByTestId("history-version-2");
    await user.click(within(second).getByRole("button", { name: "Restaurer" }));
    await user.type(within(second).getByLabelText("Pourquoi (facultatif)"), "Bad release");
    await user.click(within(second).getByRole("button", { name: "Restaurer cette version" }));
    await waitFor(() =>
      expect(api.restore).toHaveBeenCalledWith(PAYMENT, { version: 2, reason: "Bad release" }),
    );
    expect(notify.success).toHaveBeenCalled();

    const applied = screen.getByTestId("history-operation-applied");
    expect(applied).toHaveTextContent("Restauration de la version 2");
    expect(applied).toHaveTextContent("par vous");
    expect(applied).toHaveTextContent("version 2.8.4 → 2.8.3");
    await user.click(within(applied).getByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(api.undo).toHaveBeenCalledWith(OPERATION, { reason: null }));
  });

  it("shows neither to who may not approve", async () => {
    permissions.value = ["workspace:read"];
    mount();
    await screen.findByTestId("history-version-2");
    expect(screen.queryByRole("button", { name: "Restaurer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
  });

  it("says when the history cannot be read", async () => {
    api.history.mockRejectedValue(new Error("down"));
    mount();
    expect(await screen.findByRole("alert", {}, { timeout: 4000 })).toBeInTheDocument();
  });
});
