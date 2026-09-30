"use client";

import {
  ArrowRight,
  Bell,
  CircleAlert,
  CircleOff,
  Cloud,
  Database,
  FileText,
  FolderGit2,
  GitCommitHorizontal,
  GitPullRequest,
  Info,
  type LucideIcon,
  OctagonAlert,
  Rocket,
  Server,
  Tag,
  Ticket,
  TriangleAlert,
  User,
  Users,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { shortWhen } from "@/components/knowledge/time";
import { SourceLogo } from "@/components/sources/source-logo";
import { routes } from "@/config/routes";
import {
  type AttentionPoint,
  type EntityRef,
  type EnvironmentEvent,
  typeSegment,
} from "@/lib/environment";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { SourceKind } from "@/lib/sources";

/**
 * What the "Mon environnement" screens (mockups 10 and 11) are made of:
 * their cards, their icon tiles, the lines of an event and of a point of
 * attention. Everything arrives by props.
 */

export const TILE_TONES = {
  success: "bg-state-success-soft text-state-success",
  warning: "bg-state-warning-soft text-state-warning",
  danger: "bg-state-danger-soft text-state-danger",
  info: "bg-state-info-soft text-state-info",
  violet: "bg-brand-violet-soft text-shell-nav-active",
  neutral: "bg-shell-canvas text-shell-muted",
} as const;

export type TileTone = keyof typeof TILE_TONES;

export function IconTile({
  icon: Icon,
  tone,
  className,
}: {
  icon: LucideIcon;
  tone: TileTone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg",
        TILE_TONES[tone],
        className,
      )}
    >
      <Icon className="size-5" aria-hidden="true" />
    </span>
  );
}

export function Card({
  title,
  icon,
  action,
  className,
  children,
  labelledBy,
}: {
  title: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
  labelledBy?: string;
}) {
  return (
    <section
      aria-labelledby={labelledBy}
      className={cn("rounded-xl border border-shell-line bg-white p-4", className)}
    >
      <div className="mb-3 flex items-center gap-3">
        {icon}
        <h2
          id={labelledBy}
          className="flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy"
        >
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function CardLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="flex shrink-0 items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
    >
      {children}
      <ArrowRight className="size-3.5" aria-hidden="true" />
    </Link>
  );
}

/** A thing's icon, by its type. */
export const TYPE_ICONS: Record<string, LucideIcon> = {
  service: Server,
  repository: FolderGit2,
  database: Database,
  infra_resource: Cloud,
  provider: Cloud,
  incident: TriangleAlert,
  issue: Ticket,
  pull_request: GitPullRequest,
  commit: GitCommitHorizontal,
  document: FileText,
  project: Tag,
  team: Users,
  person: User,
  release: Rocket,
  deployment: Rocket,
  branch: GitCommitHorizontal,
};

export function typeIcon(type: string): LucideIcon {
  return TYPE_ICONS[type] ?? Info;
}

/** An entity's own page. */
export function entityHref(entity: Pick<EntityRef, "id" | "type">): string {
  return routes.entity(typeSegment(entity.type), entity.id);
}

export function typeLabel(t: ReturnType<typeof useDictionary>, type: string): string {
  return (t.environment.types as Record<string, string>)[type] ?? type;
}

// ── events ───────────────────────────────────────────────────────────────────

const EVENT_TONES: Record<string, { dot: string; pill: string }> = {
  incident: { dot: "bg-state-danger", pill: TILE_TONES.danger },
  resolved: { dot: "bg-state-success", pill: TILE_TONES.success },
  attention: { dot: "bg-state-warning", pill: TILE_TONES.warning },
  change: { dot: "bg-state-info", pill: TILE_TONES.info },
  information: { dot: "bg-shell-nav-active", pill: TILE_TONES.violet },
};

/**
 * What moved, newest first: when, what, where, and what it is now — as the
 * mockups' "Événements récents" and "Derniers événements".
 */
export function EventList({
  events,
  empty,
  withSource = false,
}: {
  events: readonly EnvironmentEvent[];
  empty: string;
  withSource?: boolean;
}) {
  const t = useDictionary();
  const { locale } = useLocale();
  if (events.length === 0) {
    return <p className="py-4 text-center text-[0.8125rem] text-shell-muted">{empty}</p>;
  }
  return (
    <ul className="divide-y divide-shell-line/60">
      {events.map((event) => {
        const tone = EVENT_TONES[event.kind] ?? EVENT_TONES.information;
        const kind = (t.environment.events.kinds as Record<string, string>)[event.kind];
        const source = event.source_kinds[0] as SourceKind | undefined;
        return (
          <li
            key={event.entity.id}
            className="flex items-center gap-3 py-2 text-[0.8125rem]"
            data-testid="event-row"
          >
            <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", tone.dot)} />
            <span className="w-14 shrink-0 whitespace-nowrap text-shell-muted tabular-nums">
              {shortWhen(locale, event.at)}
            </span>
            {withSource && source ? (
              <SourceLogo kind={source} className="size-5 shrink-0" />
            ) : null}
            <span className="min-w-0 flex-1">
              <Link
                href={entityHref(event.entity)}
                className="block truncate font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {event.entity.name}
              </Link>
              {withSource ? (
                <span className="block truncate text-xs text-shell-muted">
                  {typeLabel(t, event.entity.type)}
                </span>
              ) : null}
            </span>
            {event.where && !withSource ? (
              <span className="hidden max-w-24 shrink-0 truncate text-right text-xs text-shell-nav-active sm:block">
                {event.where.name}
              </span>
            ) : null}
            <span
              className={cn(
                "w-20 shrink-0 rounded-md px-1.5 py-0.5 text-center text-[0.6875rem] font-medium",
                tone.pill,
              )}
            >
              {kind}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ── points of attention ────────────────────────────────────────────────────

const ATTENTION_LOOK: Record<string, { icon: LucideIcon; tone: TileTone }> = {
  open_incident: { icon: OctagonAlert, tone: "danger" },
  failed_resources: { icon: CircleAlert, tone: "danger" },
  stopped_resources: { icon: CircleOff, tone: "warning" },
  stale_work: { icon: Bell, tone: "warning" },
  unmonitored_services: { icon: Info, tone: "info" },
  dormant_repositories: { icon: FolderGit2, tone: "info" },
};

const LEVEL_TONES: Record<string, TileTone> = { high: "danger", medium: "warning", info: "info" };

/** What needs attention, each with what it is, how much, and how serious. */
export function AttentionList({
  points,
  empty,
}: {
  points: readonly AttentionPoint[];
  empty: string;
}) {
  const t = useDictionary();
  const w = t.environment.attention;
  if (points.length === 0) {
    return <p className="py-4 text-center text-[0.8125rem] text-shell-muted">{empty}</p>;
  }
  return (
    <ul className="space-y-3">
      {points.map((point, index) => {
        const look = ATTENTION_LOOK[point.kind] ?? { icon: Info, tone: "info" as const };
        const details = w.details as Record<string, string>;
        const detail =
          point.kind === "open_incident"
            ? point.detail
              ? fill(w.details.open_incident, { detail: point.detail })
              : w.details.open_incident_none
            : fill(details[point.kind] ?? "", { count: point.count });
        const title = point.entity?.name ?? (w.kinds as Record<string, string>)[point.kind];
        return (
          <li
            key={`${point.kind}-${point.entity?.id ?? index}`}
            className="flex items-start gap-3"
            data-testid="attention-row"
          >
            <IconTile icon={look.icon} tone={look.tone} className="size-9" />
            <div className="min-w-0 flex-1">
              {point.entity ? (
                <Link
                  href={entityHref(point.entity)}
                  className="block truncate text-[0.8125rem] font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  {title}
                </Link>
              ) : (
                <p className="truncate text-[0.8125rem] font-medium text-brand-navy">{title}</p>
              )}
              <p className="text-xs text-shell-muted">{detail}</p>
            </div>
            <span
              className={cn(
                "shrink-0 rounded-md px-2 py-0.5 text-[0.6875rem] font-medium",
                TILE_TONES[LEVEL_TONES[point.level] ?? "info"],
              )}
            >
              {(w.levels as Record<string, string>)[point.level] ?? point.level}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
