"use client";

import { Languages } from "lucide-react";

import { fill } from "@/lib/i18n/dictionaries";
import { language as languageOf } from "@/lib/i18n/languages";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";
import { percentOf } from "@/lib/i18n/remote";
import { SPINNING } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * While LEKA translates the interface into the language just chosen
 * (2026-10-30): how far it is, in a corner of every page — the screens
 * change as the words arrive, nothing to reload. Gone once it is done.
 */
export function TranslatingNotice() {
  const { translating, language } = useLanguage();
  const t = useDictionary().language;
  if (!translating || translating.status !== "translating") return null;
  const name = languageOf(language)?.native ?? language;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="interface-translating"
      className="fixed bottom-4 left-4 z-50 flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-shell-line bg-white px-3 py-2 text-xs text-brand-navy shadow-md sm:max-w-sm"
    >
      <Languages className={cn("size-3.5 shrink-0 text-brand-violet", SPINNING)} aria-hidden="true" />
      <span>{fill(t.translatingNotice, { name, percent: percentOf(translating) })}</span>
    </div>
  );
}
