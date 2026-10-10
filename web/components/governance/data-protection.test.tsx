/**
 * Sécurité & gouvernance › Données (LEKA-405).
 *
 * What these protect: the platform's protections as the API reads them —
 * the database connection's TLS, files encrypted on write, the credentials'
 * keys, a secret overdue said by name; per source what was found, in words
 * and counts, never a value; the policy a manager changes and a reader only
 * reads.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DataProtection as DataProtectionRead } from "@/lib/protection";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ read: vi.fn(), setPolicy: vi.fn() }));
const access = vi.hoisted(() => ({ permissions: [] as string[] }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/protection", async (original) => ({
  ...(await original<typeof import("@/lib/protection")>()),
  protection: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => access.permissions,
  useCurrentUser: () => ({ id: "u-admin" }),
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));

const { DataProtection } = await import("@/components/governance/data-protection");

const SAID: DataProtectionRead = {
  posture: {
    environment: "production",
    database_tls: true,
    database_tls_version: "TLSv1.3",
    object_store: "s3",
    object_store_encryption: "AES256",
    credentials_encryption: "fernet",
    credential_keys: 2,
    session_cookie_secure: true,
    overdue_secrets: ["s3_secret_access_key"],
  },
  policy: { found_payload_days: 7, customised: false },
  sources: [
    {
      source_id: "s-slack",
      name: "Slack Acme",
      kind: "slack",
      records: 120,
      scanned: 118,
      with_secrets: 2,
      secrets: { aws_key: 1, slack_token: 2 },
      personal_data: { email: 40, card: 1 },
    },
  ],
};

function mount() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <DataProtection />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  access.permissions = ["access:read", "policy:manage"];
  api.read.mockResolvedValue(SAID);
  api.setPolicy.mockResolvedValue({ found_payload_days: 3, customised: true });
});

describe("data protection", () => {
  it("says the platform's protections as they stand", async () => {
    mount();
    expect(await screen.findByTestId("protection-transit")).toHaveTextContent("Chiffrée (TLS TLSv1.3)");
    expect(screen.getByTestId("protection-rest")).toHaveTextContent(
      "Amazon S3, chiffrés à l'écriture (AES256)",
    );
    const credentials = screen.getByTestId("protection-credentials");
    expect(credentials).toHaveTextContent("Chiffrés (Fernet) · 2 clé(s) en service");
    expect(credentials).toHaveTextContent("Secrets à renouveler : s3_secret_access_key");
    expect(screen.getByTestId("protection-cookie")).toHaveTextContent("Cookie sécurisé");
  });

  it("says per source what was found, never a value", async () => {
    mount();
    const table = await screen.findByTestId("protection-found");
    const row = within(table).getByRole("row", { name: /Slack Acme/ });
    expect(row).toHaveTextContent("118 / 120");
    expect(row).toHaveTextContent("clé AWS × 1, jeton Slack × 2");
    expect(row).toHaveTextContent("e-mail × 40, carte bancaire × 1");
  });

  it("lets a manager change the policy, a reader only read it", async () => {
    mount();
    const form = await screen.findByTestId("protection-policy");
    const user = userEvent.setup();
    await user.selectOptions(within(form).getByRole("combobox"), "3");
    await user.click(within(form).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(api.setPolicy).toHaveBeenCalledWith(3));
    expect(notices.success).toHaveBeenCalledWith({ title: "Politique enregistrée." });
  });

  it("is read only for whom may not manage policies", async () => {
    access.permissions = ["access:read"];
    mount();
    const form = await screen.findByTestId("protection-policy");
    expect(within(form).getByRole("combobox")).toBeDisabled();
    expect(form).toHaveTextContent("Seuls les administrateurs changent la politique.");
  });
});
