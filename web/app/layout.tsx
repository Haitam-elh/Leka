import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { TooltipProvider } from "@/components/ui/tooltip";
import { direction } from "@/lib/i18n/languages";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { initialLanguage } from "@/lib/i18n/server";
import { wordsFor } from "@/lib/i18n/translate";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// No title at all here, deliberately. Next renders metadata into the head
// before anything else, so a title declared at this level wins over the one
// the page computes — and every tab said "LEKA". Each layout below renders
// its own <title>, which React 19 hoists into the head.
export const metadata: Metadata = {
  description: "Understand. Decide. Act.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // From the request: the first paint is already in the right language
  // (lib/i18n/server.ts) — no flash of another one, nothing waited for.
  const initial = await initialLanguage();
  const shown = wordsFor(initial.language).shown;
  return (
    // The font variables belong on <html>, not <body>: globals.css resolves
    // --font-sans at :root, and a variable declared one level lower is not
    // there yet — which is how every heading came out in the browser's serif.
    <html
      lang={shown}
      dir={direction(shown)}
      data-language={initial.language}
      className={`${geistSans.variable} ${geistMono.variable}`}
      // The browser may know better (a choice made in this tab): the
      // provider says so on mount.
      suppressHydrationWarning
    >
      <body className="antialiased">
        {/* Both wrap the whole app, including the sign-in screens: the
            language is a preference someone sets before signing in, and a
            tooltip must work wherever a component happens to be used. */}
        <LocaleProvider initial={initial}>
          <TooltipProvider>{children}</TooltipProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
