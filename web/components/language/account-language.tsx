"use client";

import { Languages } from "lucide-react";
import { useCallback, useState } from "react";

import { LanguageDialog } from "@/components/language/language-picker";
import { useUpdateCurrentUser } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { auth } from "@/lib/auth";
import { fill } from "@/lib/i18n/dictionaries";
import { language as languageOf } from "@/lib/i18n/languages";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";
import { wordsFor } from "@/lib/i18n/translate";
import { notify } from "@/lib/notify";

/**
 * A signed-in person's language: chosen here, kept on the account — so it
 * is theirs on every device — and on this one.
 */
export function useChooseLanguage(): (language: string) => Promise<void> {
  const { setLanguage, saved, workspaceLanguage } = useLanguage();
  const updateUser = useUpdateCurrentUser();
  return useCallback(
    async (chosen: string) => {
      setLanguage(chosen);
      // Said in the language just chosen: the page is changing into it.
      const t = wordsFor(chosen, workspaceLanguage).dictionary.language;
      try {
        updateUser(await auth.updateProfile({ language: chosen }));
        saved(chosen);
        notify.success({ title: fill(t.saved, { name: languageOf(chosen)?.native ?? chosen }) });
      } catch {
        notify.error({ title: t.failed });
      }
    },
    [setLanguage, saved, workspaceLanguage, updateUser],
  );
}

/**
 * Once, to someone whose account has no language yet — accounts from before
 * languages, people who joined by invitation: LEKA says which one it found
 * from their browser, and lets them keep it or change it.
 */
export function LanguageNotice() {
  const t = useDictionary().language;
  const { unconfirmed, language } = useLanguage();
  const choose = useChooseLanguage();
  const [open, setOpen] = useState(false);
  if (!unconfirmed) return null;
  const current = languageOf(language);
  return (
    <div
      role="region"
      aria-label={t.title}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-shell-line bg-white px-4 py-2 text-[0.8125rem] text-brand-navy"
      data-testid="language-notice"
    >
      <Languages className="size-4 shrink-0 text-brand-violet" aria-hidden="true" />
      <p className="min-w-0 flex-1">{fill(t.detected, { name: current?.native ?? language })}</p>
      <div className="flex gap-2">
        <Button type="button" size="sm" onClick={() => void choose(language)}>
          {t.keep}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          {t.change}
        </Button>
      </div>
      <LanguageDialog open={open} onOpenChange={setOpen} onChoose={(chosen) => void choose(chosen)} />
    </div>
  );
}
