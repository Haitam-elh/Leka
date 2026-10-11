"use client";

import { Languages } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { IconTile } from "@/components/environment/parts";
import { useChooseLanguage } from "@/components/language/account-language";
import { LanguageDialog } from "@/components/language/language-picker";
import { useCurrentUser, usePermissions, useUpdateCurrentUser } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { auth } from "@/lib/auth";
import { fill } from "@/lib/i18n/dictionaries";
import { language as languageOf, REGIONS, shown } from "@/lib/i18n/languages";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { workspace as workspaceApi } from "@/lib/workspace";

/**
 * Langue et région (docs/languages.md): the person's language — what LEKA
 * speaks and answers them in, on every device — and their region, which
 * writes dates, numbers and amounts and never chooses the language. Then
 * the workspace's language, an admin's to change: what LEKA writes for
 * everyone in it, and where an untranslated language falls back.
 */

function regionNamer(locale: string): (code: string) => string {
  try {
    const names = new Intl.DisplayNames([locale], { type: "region" });
    return (code) => names.of(code) ?? code;
  } catch {
    return (code) => code;
  }
}

export function LanguageSettings() {
  const t = useDictionary().language;
  const user = useCurrentUser();
  const updateUser = useUpdateCurrentUser();
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const {
    language,
    locale,
    format,
    region,
    workspaceLanguage,
    setRegion,
    setWorkspaceLanguage,
  } = useLanguage();
  const choose = useChooseLanguage();
  const [mine, setMine] = useState(false);
  const [theirs, setTheirs] = useState(false);
  const regionId = useId();

  const named = useMemo(() => regionNamer(locale), [locale]);
  const regions = useMemo(() => {
    const collator = new Intl.Collator(locale);
    return [...REGIONS].sort((a, b) => collator.compare(named(a), named(b)));
  }, [locale, named]);
  const example = new Intl.DateTimeFormat(format, { dateStyle: "long" }).format(new Date());
  const amount = new Intl.NumberFormat(format, { style: "currency", currency: "EUR" }).format(1234.5);

  const current = languageOf(language);
  const shared = languageOf(workspaceLanguage);
  const meanwhile = languageOf(shown("app", language, workspaceLanguage));

  async function saveRegion(next: string | null) {
    setRegion(next);
    try {
      updateUser(await auth.updateProfile({ region: next }));
    } catch {
      notify.error({ title: t.failed });
    }
  }

  async function saveWorkspace(next: string) {
    const before = workspaceLanguage;
    setWorkspaceLanguage(next);
    try {
      await workspaceApi.configure({ default_language: next });
      notify.success({ title: fill(t.workspaceSaved, { name: languageOf(next)?.native ?? next }) });
    } catch {
      setWorkspaceLanguage(before);
      notify.error({ title: t.failed });
    }
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="language-settings">
      <div className="mb-3 flex items-center gap-3">
        <IconTile icon={Languages} tone="violet" />
        <div>
          <h2 className="font-semibold text-brand-navy">{t.settingsTitle}</h2>
          <p className="text-[0.8125rem] text-shell-muted">{t.settingsDescription}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <p className="text-xs font-semibold text-shell-muted">{t.current}</p>
          <div className="flex flex-wrap items-center gap-2">
            <span lang={current?.tag} dir={current?.dir} className="font-semibold text-brand-navy" data-testid="language-current">
              {current?.native ?? language}
            </span>
            <Button type="button" size="sm" variant="outline" onClick={() => setMine(true)}>
              {t.change}
            </Button>
          </div>
          {current && !current.ui.app ? (
            <p className="text-xs text-shell-muted">
              {fill(t.fallback, { shown: meanwhile?.native ?? "English" })} ·{" "}
              {fill(current.ai === "limited" ? t.aiLimited : t.answers, { name: current.native })}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={regionId} className="text-xs font-semibold text-shell-muted">
            {t.region}
          </label>
          <select
            id={regionId}
            value={region ?? user?.region ?? ""}
            onChange={(event) => void saveRegion(event.target.value || null)}
            className="h-9 rounded-lg border border-shell-line bg-white px-2 text-sm"
            data-testid="region"
          >
            <option value="">{t.regionBrowser}</option>
            {regions.map((code) => (
              <option key={code} value={code}>
                {named(code)}
              </option>
            ))}
          </select>
          <p className="text-xs text-shell-muted">
            {t.regionHint} {fill(t.regionExample, { example: `${example} · ${amount}` })}
          </p>
        </div>

        <div className="flex flex-col gap-1 md:col-span-2" data-testid="workspace-language">
          <p className="text-xs font-semibold text-shell-muted">{t.workspaceTitle}</p>
          <div className="flex flex-wrap items-center gap-2">
            <span lang={shared?.tag} dir={shared?.dir} className="font-semibold text-brand-navy">
              {shared?.native ?? "—"}
            </span>
            {admin ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setTheirs(true)}>
                {t.change}
              </Button>
            ) : null}
          </div>
          <p className="text-xs text-shell-muted">
            {t.workspaceDescription} {admin ? null : t.workspaceReadOnly}
          </p>
        </div>
      </div>

      <LanguageDialog open={mine} onOpenChange={setMine} onChoose={(chosen) => void choose(chosen)} />
      <LanguageDialog
        open={theirs}
        onOpenChange={setTheirs}
        onChoose={(chosen) => void saveWorkspace(chosen)}
        value={workspaceLanguage ?? undefined}
      />
    </section>
  );
}
