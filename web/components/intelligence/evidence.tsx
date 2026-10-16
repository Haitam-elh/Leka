"use client";

import {
  ArrowRight,
  ArrowUpRight,
  ChevronDown,
  CircleDot,
  FileText,
  type LucideIcon,
  Network,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { cn } from "cn";

import { Logo } from "@/components/environment/parts";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { EvidenceRef } from "@/lib/intelligence";

/**
 * The evidence behind a statement, inspectable from where it is used
 * (LEKA-341), as the mockups draw it:
 *
 *     EvidenceList    mockup 04's "Preuves et sources clés" — a line each:
 *                     its tool's logo, what it is, the tool and its kind,
 *                     when, "Voir"; and its details, opened in place — its
 *                     key, its record, the rule
 *     EvidenceStrip   mockup 05's "Éléments qui justifient cette
 *                     recommandation" — the first few side by side, the
 *                     rest one click away
 *     EvidenceButton  mockup 03's "Voir les éléments", on a line
 *
 * Nothing is asserted that cannot be opened.
 */

const KIND_ICONS: Record<EvidenceRef["kind"], LucideIcon> = {
  record: FileText,
  entity: Network,
  event: CircleDot,
  inference: Sparkles,
};

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

/** Its tool's logo, or what kind of evidence it is. */
function Mark({ item, className }: { item: EvidenceRef; className?: string }) {
  const Icon = KIND_ICONS[item.kind];
  return item.source?.kind ? (
    <Logo kind={item.source.kind} className={className} />
  ) : (
    <Icon className={cn("text-shell-nav-active", className)} aria-hidden="true" />
  );
}

/** "OPS board · l'enregistrement de l'incident": where from, what. */
function subline(item: EvidenceRef): string {
  return [item.source?.name ?? null, item.detail ?? null].filter(Boolean).join(" · ");
}

/** "Voir": to the item whole — in its tool, or in LEKA. */
function SeeWhole({ item, className }: { item: EvidenceRef; className?: string }) {
  const t = useDictionary();
  if (!item.href) return null;
  const outside = /^https?:\/\//.test(item.href);
  const look = cn(
    "inline-flex shrink-0 items-center gap-1 rounded-lg border border-shell-line bg-white px-2.5 py-1 text-xs font-medium text-brand-navy hover:bg-shell-canvas",
    FOCUS,
    className,
  );
  // Named by what it opens: "Voir" alone, ten times over, says nothing.
  const name = `${t.intelligence.evidence.open} ${item.label}`;
  const label = (
    <>
      {t.intelligence.evidence.open}
      {outside ? (
        <ArrowUpRight className="size-3.5" aria-hidden="true" />
      ) : (
        <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
      )}
    </>
  );
  return outside ? (
    <a href={item.href} target="_blank" rel="noreferrer" aria-label={name} className={look}>
      {label}
    </a>
  ) : (
    <Link href={item.href} aria-label={name} className={look}>
      {label}
    </Link>
  );
}

export function EvidenceList({
  items,
  max,
  id,
  className,
}: {
  items: readonly EvidenceRef[];
  /** How many to show before "Voir toutes les preuves (N)". */
  max?: number;
  id?: string;
  className?: string;
}) {
  const t = useDictionary();
  const w = t.intelligence.evidence;
  const [all, setAll] = useState(false);
  if (items.length === 0) {
    return (
      <p id={id} className={cn("text-[0.8125rem] text-shell-muted", className)}>
        {w.none}
      </p>
    );
  }
  const shown = all || max === undefined ? items : items.slice(0, max);
  return (
    <div id={id} className={className}>
      <ul
        className="divide-y divide-shell-line/60"
        aria-label={fill(w.count, { count: items.length })}
        data-testid="evidence"
      >
        {shown.map((item) => (
          <EvidenceItem key={item.id} item={item} />
        ))}
      </ul>
      {shown.length < items.length || all ? (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll(!all)}
          className={cn(
            "mt-2 flex items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active hover:underline",
            FOCUS,
          )}
        >
          {all ? w.fewer : fill(w.all, { count: items.length })}
          <ChevronDown className={cn("size-3.5 transition-transform", all && "rotate-180")} />
        </button>
      ) : null}
    </div>
  );
}

function EvidenceItem({ item }: { item: EvidenceRef }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intelligence.evidence;
  const [open, setOpen] = useState(false);
  const details = useId();
  const sub = subline(item);
  return (
    <li className="@container py-2.5 text-[0.8125rem]" data-testid="evidence-item">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-shell-canvas">
          <Mark item={item} className="size-5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-brand-navy">{item.label}</span>
          {sub ? <span className="block truncate text-xs text-shell-muted">{sub}</span> : null}
        </span>
        {item.at ? (
          <time className="hidden shrink-0 text-xs text-shell-muted @md:block" dateTime={item.at}>
            {timeAgo(t, item.at)}
          </time>
        ) : null}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={open ? details : undefined}
          aria-label={fill(w.inspect, { label: item.label })}
          onClick={() => setOpen(!open)}
          className={cn("shrink-0 rounded p-1 text-shell-muted hover:text-brand-navy", FOCUS)}
        >
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </button>
        <SeeWhole item={item} />
      </div>
      {open ? (
        <dl
          id={details}
          className="mt-2 ms-12 grid gap-x-3 gap-y-1 rounded-md bg-shell-canvas p-2 text-xs @md:grid-cols-[8rem_minmax(0,1fr)]"
          data-testid="evidence-detail"
        >
          <dt className="text-shell-muted">{w.kind}</dt>
          <dd>{w.kinds[item.kind]}</dd>
          {item.source ? (
            <>
              <dt className="text-shell-muted">{w.source}</dt>
              <dd>{item.source.name ?? item.source.kind ?? w.unknownSource}</dd>
            </>
          ) : null}
          {item.at ? (
            <>
              <dt className="text-shell-muted">{w.when}</dt>
              <dd>{exactDate(locale, item.at)}</dd>
            </>
          ) : null}
          {(item.facts ?? []).map((fact) => (
            <div key={fact.label} className="contents">
              <dt className="text-shell-muted">{fact.label}</dt>
              <dd className="break-words">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}

/** Mockup 05's "Éléments qui justifient cette recommandation": the first
 * few side by side, then all of them as a list. */
export function EvidenceStrip({
  items,
  title,
  max = 3,
  aside,
}: {
  items: readonly EvidenceRef[];
  title: string;
  max?: number;
  /** Beside the title: how sure. */
  aside?: React.ReactNode;
}) {
  const t = useDictionary();
  const w = t.intelligence.evidence;
  const [all, setAll] = useState(false);
  const list = useId();
  return (
    <div className="rounded-lg border border-shell-line bg-white p-3" data-testid="evidence-strip">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className="flex-1 text-xs font-semibold text-brand-navy">{title}</p>
        {aside}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-shell-muted">{w.none}</p>
      ) : all ? null : (
        <ul className="grid gap-3 sm:grid-cols-3">
          {items.slice(0, max).map((item) => (
            <li key={item.id} className="flex min-w-0 items-start gap-2 text-xs">
              <Mark item={item} className="mt-0.5 size-5 shrink-0" />
              <span className="min-w-0">
                <span className="block truncate font-medium text-brand-navy">{item.label}</span>
                {subline(item) ? (
                  <span className="block truncate text-shell-muted">{subline(item)}</span>
                ) : null}
                {item.at ? (
                  <time className="block text-shell-muted" dateTime={item.at}>
                    {timeAgo(t, item.at)}
                  </time>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      {items.length > 0 ? (
        <button
          type="button"
          aria-expanded={all}
          aria-controls={all ? list : undefined}
          onClick={() => setAll(!all)}
          className={cn(
            "mt-2 inline-flex items-center gap-1 rounded-lg border border-shell-line px-2.5 py-1 text-xs font-medium text-brand-navy hover:bg-shell-canvas",
            FOCUS,
          )}
        >
          {all ? w.fewer : fill(w.all, { count: items.length })}
          <ChevronDown className={cn("size-3.5 transition-transform", all && "rotate-180")} />
        </button>
      ) : null}
      {all ? <EvidenceList id={list} items={items} className="mt-2" /> : null}
    </div>
  );
}

/** Mockup 03's "Voir les éléments (3)": opens a line's evidence. */
export function EvidenceButton({
  count,
  open,
  controls,
  onClick,
}: {
  count: number;
  open: boolean;
  controls: string;
  onClick: () => void;
}) {
  const t = useDictionary();
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-lg border border-shell-line bg-white px-3 py-1.5 text-xs font-medium text-brand-navy hover:bg-shell-canvas",
        FOCUS,
      )}
    >
      {fill(t.intelligence.evidence.see, { count })}
      <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
    </button>
  );
}

/** "Voir les éléments (3)", opening on them under it: what a statement
 * rests on, one click away — where a line has no room of its own. */
export function EvidenceToggle({ items }: { items: readonly EvidenceRef[] }) {
  const [open, setOpen] = useState(false);
  const list = useId();
  if (items.length === 0) return null;
  return (
    <div className="mt-2">
      <EvidenceButton count={items.length} open={open} controls={list} onClick={() => setOpen(!open)} />
      {open ? <EvidenceList id={list} items={items} className="mt-2" /> : null}
    </div>
  );
}
