/**
 * Time as the knowledge components say it: "Il y a 3 h", and the exact
 * date for a tooltip. The words are the overview's, so the two never
 * disagree about how long ago something was.
 */

import { fill, type Dictionary } from "@/lib/i18n/dictionaries";

const HOUR = 3_600_000;

export function hoursSince(iso: string | Date, now = Date.now()): number {
  return (now - new Date(iso).getTime()) / HOUR;
}

export function timeAgo(t: Dictionary, iso: string | Date, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return t.overview.justNow;
  if (minutes < 60) return fill(t.overview.minutesAgo, { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return fill(t.overview.hoursAgo, { count: hours });
  return fill(t.overview.daysAgo, { count: Math.floor(hours / 24) });
}

/** "25 sept. 2026, 14:02" — the moment itself, in the reader's time zone. */
export function exactDate(locale: string, iso: string | Date): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

/** "14:02" today, "24 sept." before — how the mockups' timelines read. */
export function shortWhen(locale: string, iso: string | Date, now = Date.now()): string {
  const date = new Date(iso);
  const today = new Date(now).toDateString() === date.toDateString();
  return new Intl.DateTimeFormat(
    locale,
    today ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short" },
  ).format(date);
}
