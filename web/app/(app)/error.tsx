"use client";

import { PageContainer } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";

/**
 * A page that crashed while rendering, inside the shell.
 *
 * Without this file, one exception in one component replaced the whole
 * application — sidebar, header, everything — with Next's own "Application
 * error: a client-side exception has occurred", in English, with no way
 * forward but the browser's reload button. Here the frame stays, the page
 * says it could not be displayed, and "Try again" re-renders just the page.
 *
 * `digest` is Next's identifier for an error thrown on the server; quoted
 * as the reference, it is what finds the matching server log line.
 */
export default function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <PageContainer>
      <ErrorState error={error} onRetry={reset} reference={error.digest} headingLevel={1} />
    </PageContainer>
  );
}
