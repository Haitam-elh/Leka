"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { LanguageButton } from "@/components/language/language-picker";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * leka-core.com's own header, above the screens before signing in.
 *
 * Someone arrives here from the site's "Se connecter" and should not feel
 * they left it: the same logo, the same four links, the same two actions,
 * as public/index.html draws them.
 *
 * The site's pages are static files in public/, not routes of the
 * application, so they are plain <a> — a full page load, which is what
 * they need; <Link> would ask the router for a page it does not have. The
 * sign-in is the application's own, so it is a <Link>.
 *
 * And the language, before anyone signs in (docs/languages.md): chosen
 * here, it stays on the device and the account takes it on sign-in.
 */
/* eslint-disable @next/next/no-html-link-for-pages -- static pages, above */
export function SiteHeader() {
  const t = useDictionary().auth.site;
  const link = "text-[15px] font-medium tracking-[-0.012em] whitespace-nowrap text-site-slate transition-colors hover:text-site-ink";
  // A phone holds one action beside the logo (LEKA-450: both widened the
  // page to 471px): the sign-up on /login, the sign-in everywhere else. A
  // tablet holds the actions, not the links (2026-10-27: at 768px the four
  // links pushed « Essayer gratuitement » 170px past the edge).
  const onLogin = usePathname() === "/login";

  return (
    <header className="sticky top-0 z-10 border-b border-site-rule bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-[68px] w-[min(1240px,calc(100%-48px))] items-center gap-4 sm:gap-8 xl:gap-12">
        <a href="/" aria-label={t.home} className="flex-none">
          <Image src="/leka-logo.svg" alt="LEKA" width={80} height={19} unoptimized priority />
        </a>
        <nav aria-label={t.navigation} className="me-auto hidden gap-6 lg:flex">
          <a href="/#environnement" className={link}>
            {t.platform}
          </a>
          <a href="/#intention" className={link}>
            {t.method}
          </a>
          <a href="/#video" className={link}>
            {t.cases}
          </a>
          <a href="/#controle" className={link}>
            {t.security}
          </a>
        </nav>
        <div className="ms-auto flex items-center gap-3 sm:gap-4 lg:ms-0">
          <LanguageButton className="h-[38px] px-2 text-[15px] max-sm:[&>span]:hidden font-medium text-site-slate hover:text-site-ink" />
          {/* The demo folds on a phone. Creating an account was found only
              under « Se connecter » (2026-10-14): on /login it is said first. */}
          <a href="/demo.html?type=demo" className={`hidden xl:inline ${link}`}>
            {t.demo}
          </a>
          <Link href="/login" className={`${onLogin ? "hidden sm:inline" : ""} ${link}`}>
            {t.signIn}
          </Link>
          <Link
            href="/register"
            className={`${onLogin ? "inline-flex" : "hidden sm:inline-flex"} h-[38px] items-center rounded-[6px] bg-site-ink px-4 text-sm whitespace-nowrap font-semibold tracking-[-0.012em] text-white transition-colors hover:bg-site-violet`}
            data-testid="site-signup"
          >
            {t.signUp}
          </Link>
        </div>
      </div>
    </header>
  );
}
