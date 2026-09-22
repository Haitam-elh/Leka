import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { TooltipProvider } from "@/components/ui/tooltip";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // The font variables belong on <html>, not <body>: globals.css resolves
    // --font-sans at :root, and a variable declared one level lower is not
    // there yet — which is how every heading came out in the browser's serif.
    <html lang="fr" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        {/* Both wrap the whole app, including the sign-in screens: the
            language is a preference someone sets before signing in, and a
            tooltip must work wherever a component happens to be used. */}
        <LocaleProvider>
          <TooltipProvider>{children}</TooltipProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
