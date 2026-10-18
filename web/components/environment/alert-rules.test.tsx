/**
 * The alerts a person sets on Mon environnement (LEKA-477): only who manages
 * the sources sets one; on a thing whose state is read, from its panel; its
 * troubles, the channels each said where it stands — never « opérationnel »
 * before a delivery went, the others « Bientôt disponible » —, the plan's
 * limit said with the plan above; the server's refusals in words; each rule
 * its last telling, a failure said.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["source:read", "source:manage"] }));
const rules = vi.hoisted(() => ({ data: undefined as unknown }));
const mutations = vi.hoisted(() => ({
  create: { mutate: vi.fn(), isPending: false },
  change: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
  test: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: "u-nora" }),
}));
vi.mock("@/lib/environment-queries", () => ({
  useAlertRules: () => rules,
  useAlertRuleChange: () => mutations,
  useMonitoring: () => ({ data: { entitlement: { plan: "starter" } } }),
}));
const hooks = vi.hoisted(() => ({ connect: vi.fn(), test: vi.fn(), disconnect: vi.fn() }));
vi.mock("@/lib/alert-rules", async (original) => ({
  ...(await original<typeof import("@/lib/alert-rules")>()),
  alertChannels: hooks,
}));
vi.mock("@/lib/team-queries", () => ({
  useTeamMembers: () => ({
    data: [
      { user_id: "u-nora", email: "nora@acme.example", first_name: "Nora", last_name: "Diallo" },
      { user_id: "u-sam", email: "sam@acme.example", first_name: null, last_name: null },
    ],
  }),
}));

const { AlertOnThing, AlertRuleProvider, AlertRulesCard, CreateAlertButton } = await import(
  "@/components/environment/alert-rules"
);

const PAYMENT = "e-payment";
const channels = (email = "untested") => [
  { key: "in_app", status: "operational" },
  { key: "email", status: email },
  { key: "sms", status: "unavailable" },
  { key: "whatsapp", status: "unavailable" },
  { key: "slack", status: "not_connected", hint: null, error: null },
  { key: "teams", status: "not_connected", hint: null, error: null },
  { key: "discord", status: "operational", hint: "discord.com/…3xyz", error: null },
];
const read = (over: Record<string, unknown> = {}) => ({
  limit: 20,
  used: 0,
  upgrade: null,
  channels: channels(),
  watchable: [
    {
      subject_type: "entity",
      subject_id: PAYMENT,
      name: "payment-api",
      kind: "service",
      conditions: ["unavailable", "degraded"],
      state: "operational",
      fresh: true,
      observed_at: "2026-10-16T22:00:00Z",
    },
  ],
  rules: [],
  ...over,
});
const show = (node: React.ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <AlertRuleProvider>{node}</AlertRuleProvider>
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );

beforeEach(() => {
  permissions.value = ["source:read", "source:manage"];
  rules.data = read();
  for (const each of Object.values(mutations)) each.mutate.mockReset();
});

describe("setting an alert", () => {
  it("only who manages the sources is offered it", () => {
    permissions.value = ["source:read"];
    show(
      <>
        <CreateAlertButton />
        <AlertOnThing entityId={PAYMENT} />
      </>,
    );
    expect(screen.queryByTestId("alert-create")).toBeNull();
    expect(screen.queryByTestId("alert-create-on")).toBeNull();
  });

  it("from a thing's panel: its troubles, in LEKA first, the channels each said where it stands", async () => {
    const user = userEvent.setup();
    show(<AlertOnThing entityId={PAYMENT} />);
    await user.click(screen.getByTestId("alert-create-on"));
    const dialog = await screen.findByTestId("alert-dialog");
    // On it: named after it until named otherwise.
    expect(within(dialog).getByLabelText("Nom")).toHaveAttribute("placeholder", "payment-api");
    expect(within(dialog).getByTestId("alert-condition-unavailable")).toHaveAttribute("data-checked");
    expect(within(dialog).getByTestId("alert-condition-degraded")).toHaveAttribute("data-checked");
    expect(within(dialog).getByTestId("alert-channel-email")).toHaveTextContent(/E-mail\s*· Pas encore testé/);
    expect(within(dialog).getByTestId("alert-channel-sms")).toHaveTextContent(/SMS\s*· Non disponible/);
    expect(within(within(dialog).getByTestId("alert-channel-sms")).getByRole("checkbox")).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    // By e-mail too: to whom — who sets it, by default.
    await user.click(within(within(dialog).getByTestId("alert-channel-email")).getByRole("checkbox"));
    expect(within(dialog).getByText("sam@acme.example")).toBeInTheDocument();
    await user.click(within(dialog).getByTestId("alert-save"));
    expect(mutations.create.mutate).toHaveBeenCalledWith(
      {
        name: "payment-api",
        subject_type: "entity",
        subject_id: PAYMENT,
        conditions: ["unavailable", "degraded"],
        severity: "medium",
        confirm_minutes: 0,
        repeat_hours: null,
        channels: ["in_app", "email"],
        recipients: ["u-nora"],
        enabled: true,
      },
      expect.anything(),
    );
  });

  it("a thing whose state no source reads: nothing offered on it", () => {
    show(<AlertOnThing entityId="e-auth" />);
    expect(screen.queryByTestId("alert-create-on")).toBeNull();
  });

  it("at the plan's limit: said, with the plan that allows more — never saved", async () => {
    rules.data = read({ limit: 5, used: 5, upgrade: "growth" });
    const user = userEvent.setup();
    show(<CreateAlertButton />);
    await user.click(screen.getByTestId("alert-create"));
    const limit = await screen.findByTestId("alert-limit");
    expect(limit).toHaveTextContent("Votre plan Starter permet 5 règles actives.");
    expect(limit).toHaveTextContent("Le plan Growth en permet davantage.");
    expect(screen.getByTestId("alert-save")).toBeDisabled();
  });

  it("the server's refusal said in words", async () => {
    mutations.create.mutate.mockImplementation((_body, { onError }) =>
      onError(new ApiError(422, "/monitoring/rules", "refused", "validation_failed", { rule: "not_watched" })),
    );
    const user = userEvent.setup();
    show(<AlertOnThing entityId={PAYMENT} />);
    await user.click(screen.getByTestId("alert-create-on"));
    await user.click(await screen.findByTestId("alert-save"));
    expect(await screen.findByTestId("alert-error")).toHaveTextContent(
      "Cet élément n'a pas d'état lu par une source.",
    );
  });
});

describe("the rules", () => {
  const rule = (over: Record<string, unknown> = {}) => ({
    id: "r1",
    name: "API de paiement en panne",
    subject_type: "entity",
    subject_id: PAYMENT,
    subject_name: "payment-api",
    conditions: ["unavailable"],
    severity: "high",
    confirm_minutes: 0,
    repeat_hours: null,
    channels: ["in_app", "email"],
    recipients: ["u-nora"],
    enabled: true,
    created_at: "2026-10-16T22:00:00Z",
    deliveries: [],
    ...over,
  });

  it("each on what, how, its last telling — a failure said; turned off", async () => {
    rules.data = read({
      used: 1,
      rules: [
        rule({
          deliveries: [
            {
              id: "d1",
              alert_id: "a1",
              channel: "email",
              recipient: "nora@acme.example",
              round: 0,
              status: "failed",
              error: "ConnectionError: smtp down",
              at: new Date().toISOString(),
            },
          ],
        }),
      ],
    });
    const user = userEvent.setup();
    show(<AlertRulesCard />);
    expect(screen.getByTestId("alert-rules-quota")).toHaveTextContent("1 / 20 règles actives");
    const row = screen.getByTestId("alert-rule");
    expect(row).toHaveTextContent("payment-api · Indisponible · Dans LEKA, E-mail");
    expect(within(row).getByTestId("alert-rule-last")).toHaveTextContent(
      "Échec d'envoi : E-mail · ",
    );
    expect(within(row).getByTestId("alert-rule-last")).toHaveTextContent("ConnectionError: smtp down");
    await user.click(within(row).getByTestId("alert-rule-toggle"));
    await waitFor(() =>
      expect(mutations.change.mutate).toHaveBeenCalledWith(
        { id: "r1", body: { enabled: false } },
        expect.anything(),
      ),
    );
  });

  it("Slack, Teams, Discord connected by their webhook — its hint only, tried, never SMS (LEKA-496)", async () => {
    hooks.connect.mockResolvedValue({ key: "slack", status: "untested", hint: "hooks.slack.com/…ijkl", error: null });
    hooks.test.mockResolvedValue({ key: "discord", status: "operational", hint: "discord.com/…3xyz", error: null });
    const user = userEvent.setup();
    show(<AlertRulesCard />);
    const rows = Object.fromEntries(
      screen.getAllByTestId("alert-channel-row").map((row) => [row.dataset.channel, row]),
    );
    expect(Object.keys(rows)).toEqual(["slack", "teams", "discord"]);
    expect(rows.slack).toHaveTextContent("À connecter");
    expect(within(rows.discord).getByTestId("alert-channel-hint")).toHaveTextContent("Connecté : discord.com/…3xyz");
    expect(screen.getByTestId("alert-channels")).toHaveTextContent("SMS et WhatsApp demandent un compte");

    const url = "https://hooks.slack.com/services/T/B/abcdefghijkl";
    await user.type(within(rows.slack).getByTestId("alert-channel-url"), url);
    await user.click(within(rows.slack).getByTestId("alert-channel-connect"));
    await waitFor(() => expect(hooks.connect).toHaveBeenCalledWith("slack", url));

    await user.click(within(rows.discord).getByTestId("alert-channel-test"));
    await waitFor(() => expect(hooks.test).toHaveBeenCalledWith("discord"));
    // A member reads them, never connects one.
    permissions.value = ["source:read"];
  });

  it("none yet: what a rule is for", () => {
    show(<AlertRulesCard />);
    expect(screen.getByText(/Aucune règle pour l'instant/)).toBeInTheDocument();
  });
});
