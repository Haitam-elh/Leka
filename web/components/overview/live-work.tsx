"use client";

import { Bot, Database, type LucideIcon, Sparkles, Wrench } from "lucide-react";
import Link from "next/link";

import { timeAgo } from "@/components/knowledge/time";
import { useWorkingNow } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Working } from "@/lib/twin";

/**
 * « LEKA travaille sur… » (2026-10-29, after Polsia's running log): on the
 * home, under the question, what LEKA is doing right now — an intention
 * analysed, an agent writing a change or drawing mock-ups, a source read, a
 * pull request repaired — each with its step, since when, and the way to
 * follow it. Followed closely while there is some; nothing under way,
 * nothing shown: the home stays light.
 */

const ICONS: Record<Working["kind"], LucideIcon> = {
  intention: Sparkles,
  agent: Bot,
  source: Database,
  repair: Wrench,
};
const SHOWN = 4;

export function LiveWork() {
  const t = useDictionary();
  const w = t.overview.live;
  const { data } = useWorkingNow();
  const work = data ?? [];
  if (!work.length) return null;
  const steps = w.steps as Record<string, string>;
  return (
    <section
      aria-labelledby="live-work-title"
      aria-live="polite"
      className="mt-4 rounded-xl border border-brand-violet/20 bg-brand-violet-soft/40 px-4 py-3"
      data-testid="live-work"
    >
      <h2
        id="live-work-title"
        className="flex items-center gap-2 text-[0.8125rem] font-semibold text-brand-navy"
      >
        <span className="relative flex size-2" aria-hidden="true">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand-violet opacity-60 motion-reduce:animate-none" />
          <span className="relative inline-flex size-2 rounded-full bg-brand-violet" />
        </span>
        {w.title}
      </h2>
      <ul className="mt-2 flex flex-col gap-1.5">
        {work.slice(0, SHOWN).map((item, index) => {
          const Icon = ICONS[item.kind];
          return (
            <li
              key={`${item.kind}-${item.href}-${index}`}
              className="flex min-w-0 items-center gap-2 text-[0.8125rem]"
              data-testid="live-work-item"
              data-kind={item.kind}
            >
              <Icon className="size-3.5 shrink-0 text-brand-violet" aria-hidden="true" />
              <Link
                href={item.href}
                className="min-w-0 truncate font-medium text-brand-navy hover:underline"
              >
                {item.title}
              </Link>
              <span className="shrink-0 text-shell-muted">
                {"· "}
                {steps[item.step] ?? item.step}
                {item.since ? ` · ${timeAgo(t, item.since).toLowerCase()}` : ""}
              </span>
            </li>
          );
        })}
      </ul>
      {work.length > SHOWN ? (
        <p className="mt-1 text-xs text-shell-muted">{fill(w.more, { count: work.length - SHOWN })}</p>
      ) : null}
    </section>
  );
}
