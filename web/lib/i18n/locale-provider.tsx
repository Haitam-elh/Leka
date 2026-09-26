"use client";

/**
 * Which language the interface speaks, and how a component asks for a word.
 *
 * French by default: the product is sold in French and the mockups are in
 * French. English is one click away in the account menu.
 *
 * The choice lives in the browser, not in the URL: locale-prefixed routes
 * (/en/…, /fr/…) are a routing decision with consequences for every link,
 * every redirect and the session cookie's path, and nothing yet needs them.
 * When something does — a shared link that must open in the recipient's
 * language — this provider is where that changes, and no component moves.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  DICTIONARIES,
  type Dictionary,
  isLocale,
  type Locale,
} from "@/lib/i18n/dictionaries";

const STORAGE_KEY = "leka.locale";
// The language chosen on leka-core.com's own pages (public/i18n.js). Same
// origin, same storage: someone who read the site in English arrives in an
// application in English, as long as the application speaks that language.
const SITE_KEY = "leka-lang";
const FALLBACK: Locale = "fr";

interface LocaleValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  dictionary: Dictionary;
}

const LocaleContext = createContext<LocaleValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // Always starts at the fallback, and only then reads the browser. The
  // server renders the same HTML for everyone, and a first paint that
  // disagreed with it would be a hydration error rather than a translation.
  const [locale, setStored] = useState<Locale>(FALLBACK);

  useEffect(() => {
    let remembered: string | null = null;
    try {
      remembered =
        window.localStorage.getItem(STORAGE_KEY) ?? window.localStorage.getItem(SITE_KEY);
    } catch {
      // Private browsing, or storage refused. English it is.
    }
    if (isLocale(remembered) && remembered !== locale) {
      setStored(remembered);
      document.documentElement.lang = remembered;
    }
    // Once, on mount: this restores a preference, it does not follow it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setStored(next);
    document.documentElement.lang = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The language still changes for this visit; it just will not persist.
    }
  }, []);

  const value = useMemo<LocaleValue>(
    () => ({ locale, setLocale, dictionary: DICTIONARIES[locale] }),
    [locale, setLocale],
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

/** The current language, and how to change it. */
export function useLocale(): Pick<LocaleValue, "locale" | "setLocale"> {
  const { locale, setLocale } = useLocaleContext();
  return { locale, setLocale };
}
