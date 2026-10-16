import { exactDate } from "@/components/knowledge/time";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import type { Notification } from "@/lib/notifications";

/**
 * A notification in its reader's words (LEKA-476): the server keeps what
 * happened and its parts — a title, a name, a plan, a share — never the
 * sentence, said here in the language read.
 */
export function wordsOf(
  t: Dictionary,
  notification: Notification,
  format: string,
): { title: string; body: string } {
  const w = t.notifications;
  const kinds = w.kinds as Record<string, { title: string; body: string }>;
  const said = kinds[notification.kind] ?? w.unknown;
  const params = notification.params as Record<string, unknown>;
  const text = (key: string): string => {
    const value = params[key];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  };
  const roles = w.roles as Record<string, string>;
  const plan = (key: string) => {
    const value = text(key);
    return notification.kind === "workspace.role_changed"
      ? (roles[value] ?? value)
      : value.charAt(0).toUpperCase() + value.slice(1);
  };
  const date = (key: string) => {
    const value = text(key);
    return value && !Number.isNaN(Date.parse(value)) ? exactDate(format, value) : "";
  };
  const values: Record<string, string | number> = {
    title: text("title"),
    agent: text("agent"),
    name: text("name"),
    trouble: (w.troubles as Record<string, string>)[text("trouble")] ?? text("trouble"),
    certainty: (w.certainties as Record<string, string>)[text("certainty")] ?? text("certainty"),
    by: text("by") || w.someone,
    threshold: text("threshold"),
    before: plan("before"),
    after: plan("after"),
    until: date("until") ? fill(w.untilOn, { date: date("until") }) : w.periodEnd,
    since: date("last"),
  };
  return { title: fill(said.title, values), body: said.body ? fill(said.body, values) : "" };
}
