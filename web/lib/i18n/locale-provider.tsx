"use client";

/**
 * Which language the interface speaks, and how a component asks for a word.
 *
 * Three things, kept apart (docs/languages.md):
 *
 *   language  what the person chose, or what was found for them
 *             (lib/i18n/resolve.ts): any of the catalogue's 140 — what
 *             LEKA answers them in
 *   locale    what the screens speak: the language, or the first of its
 *             chain the interface is translated into (lib/i18n/translate.ts)
 *   format    what writes dates, numbers and amounts: the screens' language
 *             in the person's region
 *
 * The server reads the first signals — the device's cookie, the browser's
 * Accept-Language, a CDN's country — so the first paint is already in the
 * right language (app/layout.tsx). The browser then adds what only it
 * knows: a choice made in this tab, its storage. Signed in, the account's
 * language comes in through adopt(), from the shell.
 *
 * A language without a dictionary is translated by LEKA the first time
 * someone chooses it (lib/i18n/remote.ts): its words are read as they
 * arrive, the screens switch without a reload, and `translating` says how
 * far it is.
 *
 * The choice lives in the account and on the device, not in the URL:
 * locale-prefixed routes (/en/…) would move every link, every redirect
 * and the session cookie's path, and nothing needs them — the site's
 * crawlable pages carry ?lang= (public/i18n.js).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { type Dictionary, type Locale, setPluralLocale } from "@/lib/i18n/dictionaries";
import { type Direction, direction, formatLocale, isListed, regionOf } from "@/lib/i18n/languages";
import { isPseudo } from "@/lib/i18n/pseudo";
import {
  applyInterface,
  keepInterface,
  keptInterface,
  readInterface,
  type RemoteInterface,
  type RemoteProgress,
  translatedByLeka,
} from "@/lib/i18n/remote";
import {
  browserSignals,
  qaFromAddress,
  remember,
  resolve,
  type Source,
  settled,
} from "@/lib/i18n/resolve";
import { wordsFor } from "@/lib/i18n/translate";
import { LIVE_SLOW } from "@/lib/live";

export interface Initial {
  language: string;
  source: Source;
  /** The region of the browser's first language, as the server heard it. */
  region?: string | null;
  /** The country a CDN said the request came from — a hint. */
  country?: string | null;
}

/** What an account says, as /auth/me answers it. */
export interface AccountLanguage {
  language?: string | null;
  region?: string | null;
}

interface LocaleValue {
  language: string;
  source: Source;
  locale: Locale;
  region: string | null;
  format: string;
  dir: Direction;
  workspaceLanguage: string | null;
  dictionary: Dictionary;
  missing: string[];
  /** A language LEKA translates itself: how far its translation is. None
   * for a language with its own dictionary. */
  translating: RemoteProgress | null;
  /** Signed in, and the account has no language yet: LEKA shows one it
   * found, and asks once whether to keep it. */
  unconfirmed: boolean;
  /** A person's own choice: kept on this device, and marked for the account. */
  setLanguage: (language: string) => void;
  setRegion: (region: string | null) => void;
  /** The workspace's language changed. */
  setWorkspaceLanguage: (language: string | null) => void;
  /** The account and its workspace, once known. Answers the language to save
   * to the account, if one should be: a choice made before signing in. */
  adopt: (account: AccountLanguage | null, workspace?: string | null) => string | null;
  /** The account now holds this language. */
  saved: (language: string) => void;
}

const LocaleContext = createContext<LocaleValue | null>(null);

const DEFAULT_INITIAL: Initial = { language: "en", source: "default" };

// While LEKA translates: how far, looked at this often; its words read
// again at most this often (they weigh more).
const LOOK_EVERY = 4_000;
const WORDS_EVERY = 12_000;

function progressOf(found: RemoteInterface): RemoteProgress {
  return { tag: found.tag, status: found.status, done: found.done, total: found.total, model: found.model };
}

function browserRegion(): string | null {
  if (typeof navigator === "undefined") return null;
  return regionOf(navigator.language ?? "") ?? null;
}

export function LocaleProvider({
  children,
  initial = DEFAULT_INITIAL,
}: {
  children: React.ReactNode;
  initial?: Initial;
}) {
  const [language, setChosen] = useState(initial.language);
  const [source, setSource] = useState<Source>(initial.source);
  const [region, setStoredRegion] = useState<string | null>(null);
  const [heardRegion, setHeardRegion] = useState<string | null>(initial.region ?? null);
  const [workspaceLanguage, setWorkspaceLanguage] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountLanguage | null>(null);
  const adopted = useRef(false);
  const [translating, setTranslating] = useState<RemoteProgress | null>(null);
  // Bumped each time a translation's words arrive: the screens read them.
  const [arrived, setArrived] = useState(0);

  // What only the browser knows: a choice made in this tab, its storage,
  // its own languages. Once, on mount.
  useEffect(() => {
    qaFromAddress(window.location.search);
    const found = resolve(browserSignals(initial.country ?? null));
    // An account adopted meanwhile has the last word.
    if (!adopted.current) {
      setChosen(found.language);
      setSource(found.source);
    }
    setHeardRegion(browserRegion() ?? initial.region ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A language LEKA translates itself: the words this device kept first,
  // then the API's — read again as they arrive, until it is done.
  useEffect(() => {
    if (!translatedByLeka(language)) {
      setTranslating(null);
      return;
    }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let applied = -1;
    let appliedAt = 0;
    const kept = keptInterface(language);
    if (kept) {
      applyInterface(language, kept.words);
      applied = kept.done;
      setTranslating(progressOf(kept));
      setArrived((n) => n + 1);
    } else {
      setTranslating(null);
    }
    async function look(withWords: boolean) {
      let found: RemoteInterface | null = null;
      try {
        found = await readInterface(language, withWords);
      } catch {
        found = null;
      }
      if (stopped) return;
      if (found) {
        if (withWords) {
          applyInterface(language, found.words);
          keepInterface(found);
          applied = found.done;
          appliedAt = Date.now();
          setArrived((n) => n + 1);
        }
        setTranslating(progressOf(found));
        if (found.status === "ready" || found.status === "failed") {
          // Done since the last words read: the last ones.
          if (!withWords && found.done !== applied) void look(true);
          return;
        }
      }
      const seen = found;
      timer = setTimeout(
        () => void look(seen !== null && seen.done !== applied && Date.now() - appliedAt >= WORDS_EVERY),
        // Unreachable, or not started (too many asked from this address):
        // at the calm pace.
        seen && seen.status === "translating" ? LOOK_EVERY : LIVE_SLOW,
      );
    }
    void look(true);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [language]);

  const words = useMemo(
    () => wordsFor(language, workspaceLanguage),
    // `arrived`: a translation's words came in — the same language, new words.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, workspaceLanguage, arrived],
  );
  const dir: Direction = language === "ar-XB" ? "rtl" : direction(words.shown);
  const format = isPseudo(words.shown) ? "en" : formatLocale(words.shown, region ?? heardRegion);
  // fill() picks "1 source" or "2 sources" by these rules — set while
  // rendering, so the first paint already speaks them.
  setPluralLocale(isPseudo(words.shown) ? "en" : words.shown);

  // The document says what it is written in, for screen readers, fonts,
  // hyphenation and spelling — and which way it reads.
  useEffect(() => {
    const root = document.documentElement;
    root.lang = words.shown;
    root.dir = dir;
    root.dataset.language = language;
    if (words.missing.length && process.env.NODE_ENV === "development") {
      console.warn(`[i18n] ${language}: ${words.missing.length} keys fall back`, words.missing);
    }
  }, [words, dir, language]);

  const setLanguage = useCallback((next: string) => {
    if (!isListed(next) && !isPseudo(next)) return;
    setChosen(next);
    setSource("now");
    if (!isPseudo(next)) remember(next);
  }, []);

  const adopt = useCallback(
    (said: AccountLanguage | null, workspace?: string | null): string | null => {
      adopted.current = true;
      setAccount(said);
      setWorkspaceLanguage(workspace ?? null);
      setStoredRegion(said?.region ?? null);
      if (said === null) return null;
      const signals = browserSignals(initial.country ?? null);
      const found = resolve({ ...signals, account: said.language ?? null });
      setChosen(found.language);
      setSource(found.source);
      // A choice made just now, or on this device before the account had
      // any: the account takes it.
      const keep =
        (found.source === "now" && found.language !== said.language) ||
        (found.source === "device" && !said.language);
      return keep ? found.language : null;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const saved = useCallback((kept: string) => {
    settled();
    setAccount((previous) => (previous ? { ...previous, language: kept } : previous));
    setSource("account");
  }, []);

  const setRegion = useCallback((next: string | null) => setStoredRegion(next), []);

  const unconfirmed =
    account !== null && !account.language && ["browser", "country", "default"].includes(source);

  const value = useMemo<LocaleValue>(
    () => ({
      language,
      source,
      locale: words.shown,
      region,
      format,
      dir,
      workspaceLanguage,
      dictionary: words.dictionary,
      missing: words.missing,
      translating,
      unconfirmed,
      setLanguage,
      setRegion,
      setWorkspaceLanguage,
      adopt,
      saved,
    }),
    [
      language,
      source,
      words,
      region,
      format,
      dir,
      workspaceLanguage,
      translating,
      unconfirmed,
      setLanguage,
      setRegion,
      adopt,
      saved,
    ],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

function useLocaleContext(): LocaleValue {
  const value = useContext(LocaleContext);
  if (value === null) {
    throw new Error("useLocale must be used inside <LocaleProvider>");
  }
  return value;
}

/** The words, in the current language. `const t = useDictionary()` then `t.nav.overview`. */
export function useDictionary(): Dictionary {
  return useLocaleContext().dictionary;
}

/** The current language, and how to change it.
 *
 * `locale` is what the screens speak (fr, en…); `format` what writes dates
 * and numbers — give `format`, never `locale`, to Intl. `setLocale` is the
 * person's own choice. */
export function useLocale(): Pick<LocaleValue, "locale" | "format" | "language" | "dir"> & {
  setLocale: (language: string) => void;
} {
  const { locale, format, language, dir, setLanguage } = useLocaleContext();
  return { locale, format, language, dir, setLocale: setLanguage };
}

/** The language an account or an e-mail may be given — one the catalogue
 * lists, never a QA pseudo-language. */
export function useSpokenLanguage(): string | undefined {
  const { language } = useLocaleContext();
  return isListed(language) ? language : undefined;
}

/** Everything, for the language picker, the settings and the shell. */
export function useLanguage(): LocaleValue {
  return useLocaleContext();
}
