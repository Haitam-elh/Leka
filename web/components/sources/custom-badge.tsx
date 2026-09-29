"use client";

import { Wrench } from "lucide-react";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * "Sur mesure": a source connected by a custom connector — described by
 * the customer's team — not by one LEKA ships (LEKA-426). The same words
 * wherever a source is named, so the two are never confused.
 */
export function CustomBadge() {
  const t = useDictionary();
  return (
    <span
      title={t.sources.custom.badgeHelp}
      className="inline-flex items-center gap-1 rounded-md border border-brand-violet/40 bg-brand-violet-soft px-2 py-0.5 text-xs text-shell-nav-active"
    >
      <Wrench className="size-3" aria-hidden="true" />
      {t.sources.custom.badge}
    </span>
  );
}
