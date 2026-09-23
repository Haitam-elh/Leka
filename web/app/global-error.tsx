"use client";

import { TriangleAlert } from "lucide-react";

import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { DICTIONARIES, fill } from "@/lib/i18n/dictionaries";
import "./globals.css";

/**
 * The last resort: the root layout itself failed.
 *
 * Nothing above this survived — no locale, no providers, not even <html>,
 * which is why this file renders its own. French, the product's default,
 * because the preference that would say otherwise lives in a provider that
 * is gone. Plain markup and one retry, and nothing that could fail the same
 * way twice.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = DICTIONARIES.fr;
  // The way back is an <a>, not next/link: after the root layout failed, a
  // full reload is the point.

  return (
    <html lang="fr">
      <body className="flex min-h-screen items-center justify-center bg-shell-canvas antialiased">
        <main>
          <StatePanel
            role="alert"
            icon={TriangleAlert}
            tone="danger"
            headingLevel={1}
            title={t.states.errorTitle}
            description={t.states.errorBody}
            actions={
              <>
                <Button onClick={reset}>{t.states.retry}</Button>
                <a href={routes.overview()} className={buttonVariants({ variant: "outline" })}>
                  {t.states.backToOverview}
                </a>
              </>
            }
            footer={error.digest ? fill(t.states.reference, { id: error.digest }) : undefined}
          />
        </main>
      </body>
    </html>
  );
}
