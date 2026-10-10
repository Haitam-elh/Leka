"use client";

import Image from "next/image";
import Link from "next/link";

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
 */
/* eslint-disable @next/next/no-html-link-for-pages -- static pages, above */
export function SiteHeader() {
  const t = useDictionary().auth.site;
  const link = "text-[15px] font-medium tracking-[-0.012em] text-site-slate transition-colors hover:text-site-ink";

  return (
    <header className="sticky top-0 z-10 border-b border-site-rule bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-[68px] w-[min(1240px,calc(100%-48px))] items-center gap-12">
        <a href="/" aria-label={t.home} className="flex-none">
          <Image src="/leka-logo.svg" alt="LEKA" width={80} height={19} unoptimized priority />
        </a>
        <nav aria-label={t.navigation} className="mr-auto hidden gap-6 md:flex">
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
        <div className="ml-auto flex items-center gap-4 md:ml-0">
          {/* On a phone, as on the site: the sign-in stays, the demo folds. */}
          <Link href="/login" className={link}>
            {t.signIn}
          </Link>
          <a
            href="/demo.html?type=demo"
            className="hidden h-[38px] items-center rounded-[6px] bg-site-ink sm:inline-flex px-4 text-sm font-semibold tracking-[-0.012em] text-white transition-colors hover:bg-site-violet"
          >
            {t.demo}
          </a>
        </div>
      </div>
    </header>
  );
}
