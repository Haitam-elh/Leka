"use client";

import { ChevronDown, CircleDot, FileText, type LucideIcon, Network, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { Logo } from "@/components/environment/parts";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { EvidenceRef } from "@/lib/intelligence";

/**
 * The evidence behind a statement, inspectable from where it is used
 * (LEKA-341): each piece says what it is, which tool it was read from and
 * when, and opens on what it holds — its key, its record, the rule — and a
 * way to see it whole. Nothing is asserted that cannot be opened.
 */

const KIND_ICONS: Record<EvidenceRef["kind"], LucideIcon> = {
  record: FileText,
  entity: Network,
  event: CircleDot,
  inference: Sparkles,
};

export function EvidenceList({
  items,
  className,
}: {
  items: readonly EvidenceRef[];
  className?: string;
}) {
  const t = useDictionary();
  if (items.length === 0) {
    return <p className="text-xs text-shell-muted">{t.intelligence.evidence.none}</p>;
  }
  return (
    <ul
      className={cn("divide-y divide-shell-line/60 rounded-lg border border-shell-line", className)}
      aria-label={fill(t.intelligence.evidence.count, { count: items.length })}
      data-testid="evidence"
    >
      {items.map((item) => (
        <EvidenceItem key={item.id} item={item} />
      ))}
    </ul>
  );
}

function EvidenceItem({ item }: { item: EvidenceRef }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intelligence.evidence;
  const [open, setOpen] = useState(false);
  const Icon = KIND_ICONS[item.kind];
  return (
    <li className="px-3 py-2 text-xs" data-testid="evidence-item">
      <div className="flex items-center gap-2">
        {item.source?.kind ? (
          <Logo kind={item.source.kind} className="size-4 shrink-0" />
        ) : (
          <Icon className="size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-brand-navy">{item.label}</span>
          {item.detail ? (
            <span className="block truncate text-shell-muted">{item.detail}</span>
          ) : null}
        </span>
        {item.at ? (
          <time className="shrink-0 text-shell-muted" dateTime={item.at}>
            {timeAgo(t, item.at)}
          </time>
        ) : null}
        <button
          type="button"
          aria-expanded={open}
          aria-label={fill(w.inspect, { label: item.label })}
          onClick={() => setOpen(!open)}
          className="rounded p-0.5 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {open ? (
        <dl
          className="mt-2 grid gap-x-3 gap-y-1 rounded-md bg-shell-canvas p-2 sm:grid-cols-[8rem_minmax(0,1fr)]"
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
          {item.href ? (
            <dd className="sm:col-span-2">
              <Link
                href={item.href}
                className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {w.open}
              </Link>
            </dd>
          ) : null}
        </dl>
      ) : null}
    </li>
  );
}

/** "3 preuves", opening on them: what a statement rests on, one click away. */
export function EvidenceToggle({ items }: { items: readonly EvidenceRef[] }) {
  const t = useDictionary();
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
      >
        {fill(t.intelligence.evidence.count, { count: items.length })}
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open ? <EvidenceList items={items} className="mt-2" /> : null}
    </div>
  );
}
