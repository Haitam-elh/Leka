/** The alerts a person sets on Mon environnement (LEKA-477): the server
 * checks all of it — what may be watched, the channels, the plan's limit. */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type AlertRules = components["schemas"]["AlertRulesRead"];
export type AlertRule = components["schemas"]["AlertRuleRead"];
export type AlertRuleWrite = components["schemas"]["AlertRuleWrite"];
export type AlertRuleChange = components["schemas"]["AlertRuleChange"];
export type Watchable = components["schemas"]["WatchableRead"];
export type AlertChannel = components["schemas"]["ChannelRead"];

const BASE = "/monitoring/rules";
const one = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export const alertRules = {
  list: () => apiFetch<AlertRules>(BASE),
  create: (body: AlertRuleWrite) =>
    apiFetch<AlertRule>(BASE, { method: "POST", body: JSON.stringify(body) }),
  change: (id: string, body: AlertRuleChange) =>
    apiFetch<AlertRule>(one(id), { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => apiFetch<void>(one(id), { method: "DELETE" }),
  /** Each of its channels tried now; each telling kept. */
  test: (id: string) => apiFetch<AlertRule>(`${one(id)}/test`, { method: "POST" }),
};

/** A channel a rule may use now: integrated, in the plan. */
export function usable(channel: AlertChannel): boolean {
  return channel.status === "operational" || channel.status === "untested" || channel.status === "failing";
}
