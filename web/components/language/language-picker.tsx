"use client";

import { Check, Globe, Search } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fill } from "@/lib/i18n/dictionaries";
import { answers, type Language, language as languageOf, LANGUAGES, shown } from "@/lib/i18n/languages";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";

/**
 * Choosing a language among the catalogue's 140 (docs/languages.md).
 *
 * Searched by a language's own name — what someone looking for their
 * language types — by its English name, its name in the interface's
 * language, or its tag; accents and case set aside. Those the interface is
 * translated into come first. Each says, honestly, what choosing it gives:
 * the interface translated, or not yet and in which language meanwhile —
 * and that LEKA answers in it all the same.
 */

function namer(locale: string): (tag: string) => string | undefined {
  try {
    const names = new Intl.DisplayNames([locale], { type: "language" });
    return (tag) => {
      try {
        return names.of(tag);
      } catch {
        return undefined;
      }
    };
  } catch {
    return () => undefined;
  }
}

export function LanguagePicker({
  value,
  onChoose,
  workspace,
}: {
  value: string;
  onChoose: (language: string) => void;
  /** The workspace's language: where an untranslated language falls back. */
  workspace?: string | null;
}) {
  const t = useDictionary().language;
  const { locale } = useLanguage();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const list = useRef<HTMLUListElement>(null);
  const named = useMemo(() => namer(locale), [locale]);

  const found = useMemo(
    () => LANGUAGES.filter((one) => answers(one, query, named(one.tag))),
    [query, named],
  );
  const translated = found.filter((one) => one.ui.app);
  const others = found.filter((one) => !one.ui.app);
  const ordered = [...translated, ...others];
  const current = Math.min(active, Math.max(ordered.length - 1, 0));

  function status(one: Language): string {
    if (one.ui.app === "reviewed") return t.reviewed;
    if (one.ui.app === "translated") return t.translated;
    // What the screens fall back to: the next language of its chain that is
    // translated, for a partial translation the one after it.
    const after = one.ui.app === "partial" ? shown("app", null, workspace) : shown("app", one.tag, workspace);
    const meanwhile = languageOf(after);
    const fallback = fill(one.ui.app === "partial" ? t.partial : t.fallback, {
      shown: meanwhile?.native ?? "English",
    });
    const ai = fill(one.ai === "limited" ? t.aiLimited : t.answers, { name: one.native });
    return `${fallback} · ${ai}`;
  }

  function move(to: number) {
    const next = (to + ordered.length) % Math.max(ordered.length, 1);
    setActive(next);
    // By hand, not scrollIntoView: that scrolls every ancestor too, the
    // page behind the dialog included.
    const box = list.current;
    const row = box?.querySelector<HTMLElement>(`[data-index="${next}"]`);
    if (box && row) {
      if (row.offsetTop < box.scrollTop) box.scrollTop = row.offsetTop;
      else if (row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) {
        box.scrollTop = row.offsetTop + row.offsetHeight - box.clientHeight;
      }
    }
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") move(current + 1);
    else if (event.key === "ArrowUp") move(current - 1);
    else if (event.key === "Home") move(0);
    else if (event.key === "End") move(ordered.length - 1);
    else if (event.key === "Enter" && ordered[current]) onChoose(ordered[current].tag);
    else return;
    event.preventDefault();
  }

  function option(one: Language, index: number) {
    const chosen = one.tag === value;
    const inInterface = named(one.tag);
    return (
      <li
        key={one.tag}
        id={`${listId}-${one.tag}`}
        role="option"
        aria-selected={chosen}
        data-index={index}
        data-tag={one.tag}
        data-active={index === current || undefined}
        onClick={() => onChoose(one.tag)}
        onMouseMove={() => setActive(index)}
        className="flex cursor-pointer items-start gap-3 rounded-lg px-3 py-2 data-[active]:bg-shell-canvas"
      >
        <span className="mt-0.5 size-4 shrink-0 text-brand-violet" aria-hidden="true">
          {chosen ? <Check className="size-4" /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            {/* In its own language and direction: a screen reader says it
                in the right voice, an Arabic name reads right to left. */}
            <span lang={one.tag} dir={one.dir} className="font-semibold text-brand-navy">
              {one.native}
            </span>
            <span className="text-xs text-shell-muted">
              {inInterface && inInterface !== one.english && inInterface !== one.native
                ? `${inInterface} · ${one.english}`
                : one.english}
            </span>
          </span>
          <span className="block text-xs text-shell-muted" data-testid="language-status">
            {status(one)}
          </span>
        </span>
      </li>
    );
  }

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="relative">
        <Search
          className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-shell-muted"
          aria-hidden="true"
        />
        <input
          type="search"
          role="combobox"
          aria-label={t.search}
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={ordered[current] ? `${listId}-${ordered[current].tag}` : undefined}
          aria-autocomplete="list"
          placeholder={t.search}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          dir="auto"
          autoComplete="off"
          spellCheck={false}
          className="h-10 w-full rounded-lg border border-shell-line bg-white ps-9 pe-3 text-sm outline-none focus-visible:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/30"
          data-testid="language-search"
        />
      </div>
      {ordered.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-shell-muted" role="status">
          {fill(t.none, { query })}
        </p>
      ) : (
        <ul
          ref={list}
          id={listId}
          role="listbox"
          aria-label={t.dialogTitle}
          className="relative max-h-[min(60vh,28rem)] overflow-y-auto overscroll-contain"
          data-testid="language-list"
        >
          {translated.length ? (
            <li role="presentation">
              <p className="px-3 pb-1 pt-2 text-[0.6875rem] font-semibold tracking-wide text-shell-muted uppercase">
                {t.groupTranslated}
              </p>
              <ul role="group" aria-label={t.groupTranslated}>
                {translated.map((one, i) => option(one, i))}
              </ul>
            </li>
          ) : null}
          {others.length ? (
            <li role="presentation">
              <p className="px-3 pb-1 pt-2 text-[0.6875rem] font-semibold tracking-wide text-shell-muted uppercase">
                {t.groupOthers}
              </p>
              <ul role="group" aria-label={t.groupOthers}>
                {others.map((one, i) => option(one, translated.length + i))}
              </ul>
            </li>
          ) : null}
        </ul>
      )}
    </div>
  );
}

/** The picker, in a dialog. */
export function LanguageDialog({
  open,
  onOpenChange,
  onChoose,
  value,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (language: string) => void;
  /** The language shown as chosen: the person's, unless said. */
  value?: string;
}) {
  const t = useDictionary().language;
  const { language, workspaceLanguage } = useLanguage();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="language-dialog">
        <DialogHeader>
          <DialogTitle>{t.dialogTitle}</DialogTitle>
          <DialogDescription>{fill(t.dialogDescription, { count: LANGUAGES.length })}</DialogDescription>
        </DialogHeader>
        <LanguagePicker
          value={value ?? language}
          workspace={workspaceLanguage}
          onChoose={(chosen) => {
            onOpenChange(false);
            onChoose(chosen);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

/** A button that says the current language and opens the picker — before
 * signing in, where the choice stays on the device until an account takes
 * it. */
export function LanguageButton({ className }: { className?: string }) {
  const t = useDictionary().language;
  const { language, setLanguage } = useLanguage();
  const [open, setOpen] = useState(false);
  const current = languageOf(language);
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className={className}
        onClick={() => setOpen(true)}
        aria-label={fill(t.open, { name: current?.native ?? language })}
        data-testid="language-button"
      >
        <Globe className="size-4" aria-hidden="true" />
        <span lang={current?.tag} dir={current?.dir}>
          {current?.native ?? language}
        </span>
      </Button>
      <LanguageDialog open={open} onOpenChange={setOpen} onChoose={setLanguage} />
    </>
  );
}
