/**
 * Every state the product shows, in one table: tone, icon, and where its
 * words are. StatusBadge draws from here, and so does everything else that
 * colours by state — an entity card, a graph edge — so "Attention" is the
 * same orange with the same icon on every screen (LEKA-340).
 *
 * A variant is `family.value`. The families overlap — "degraded" is a
 * health and a connector state, "unknown" an entity and a health one — and
 * the prefix is what keeps them apart.
 *
 * TONE IS NEVER THE ONLY SIGNAL. Each state has its own icon and its own
 * word; the colour repeats them for whoever can see it.
 */

import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CirclePause,
  CircleX,
  EyeOff,
  Info,
  LoaderCircle,
  type LucideIcon,
  OctagonAlert,
  Power,
  SignalHigh,
  SignalLow,
  SignalMedium,
  TriangleAlert,
} from "lucide-react";

import type { Dictionary } from "@/lib/i18n/dictionaries";

export type Tone = "success" | "warning" | "danger" | "info" | "accent" | "neutral";

/** Token classes per tone — no component writes a colour of its own. */
export const TONES: Record<Tone, { badge: string; dot: string; stroke: string }> = {
  success: {
    badge: "bg-state-success-soft text-state-success",
    dot: "bg-state-success",
    stroke: "var(--state-success)",
  },
  warning: {
    badge: "bg-state-warning-soft text-state-warning",
    dot: "bg-state-warning",
    stroke: "var(--state-warning)",
  },
  danger: {
    badge: "bg-state-danger-soft text-state-danger",
    dot: "bg-state-danger",
    stroke: "var(--state-danger)",
  },
  info: {
    badge: "bg-state-info-soft text-state-info",
    dot: "bg-state-info",
    stroke: "var(--state-info)",
  },
  accent: {
    badge: "bg-brand-violet-soft text-shell-nav-active",
    dot: "bg-shell-nav-active",
    stroke: "var(--shell-nav-active)",
  },
  neutral: {
    badge: "bg-shell-canvas text-shell-muted",
    dot: "bg-shell-muted",
    stroke: "var(--shell-muted)",
  },
};

type Look = readonly [Tone, LucideIcon];

const FAMILIES = {
  /** The legend of mockup 10. */
  entity: {
    operational: ["success", CircleCheck],
    attention: ["warning", CircleAlert],
    incident: ["danger", OctagonAlert],
    unmonitored: ["neutral", EyeOff],
    unknown: ["neutral", CircleHelp],
  },
  /** HealthStatus, leka/connectors. */
  health: {
    healthy: ["success", CircleCheck],
    degraded: ["warning", CircleAlert],
    unhealthy: ["danger", CircleX],
    unknown: ["neutral", CircleHelp],
  },
  /** SourceStatus — a connector's lifecycle. */
  connector: {
    draft: ["accent", CircleDashed],
    tested: ["info", CircleCheck],
    active: ["success", Power],
    degraded: ["warning", CircleAlert],
    error: ["danger", CircleX],
    disabled: ["neutral", CirclePause],
  },
  /** SyncStatus. */
  sync: {
    never: ["neutral", CircleDashed],
    idle: ["success", CircleCheck],
    running: ["info", LoaderCircle],
    failed: ["danger", CircleX],
  },
  severity: {
    critical: ["danger", OctagonAlert],
    major: ["danger", TriangleAlert],
    minor: ["warning", CircleAlert],
    info: ["info", Info],
  },
  priority: {
    high: ["danger", SignalHigh],
    medium: ["warning", SignalMedium],
    low: ["info", SignalLow],
  },
  /** A source at a glance, as the overview shows it (lib/sources.ts sourceTone). */
  source: {
    synced: ["success", CircleCheck],
    attention: ["warning", CircleAlert],
    error: ["danger", CircleX],
    setup: ["accent", CircleDashed],
    off: ["neutral", CirclePause],
  },
} as const satisfies Record<string, Record<string, Look>>;

type Families = typeof FAMILIES;
export type StatusFamily = keyof Families;
export type StatusVariant = {
  [F in StatusFamily]: `${F}.${Extract<keyof Families[F], string>}`;
}[StatusFamily];

function split(variant: StatusVariant): [StatusFamily, string] {
  const dot = variant.indexOf(".");
  return [variant.slice(0, dot) as StatusFamily, variant.slice(dot + 1)];
}

export function statusLook(variant: StatusVariant): { tone: Tone; icon: LucideIcon } {
  const [family, value] = split(variant);
  const [tone, icon] = (FAMILIES[family] as Record<string, Look>)[value];
  return { tone, icon };
}

export function statusLabel(t: Dictionary, variant: StatusVariant): string {
  const [family, value] = split(variant);
  return (t.knowledge.status[family] as Record<string, string>)[value];
}

/** Every variant, for the demo page and for tests that must cover them all. */
export const STATUS_VARIANTS: readonly StatusVariant[] = (
  Object.entries(FAMILIES) as [StatusFamily, Record<string, Look>][]
).flatMap(([family, values]) =>
  Object.keys(values).map((value) => `${family}.${value}` as StatusVariant),
);
