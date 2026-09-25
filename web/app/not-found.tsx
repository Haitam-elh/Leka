"use client";

import { RouteState } from "@/components/shell/route-state";

/**
 * An address outside the application that matches nothing.
 *
 * Rare: inside the application, (app)/[...unknown] catches every unknown
 * address and keeps the frame around it. This is for the rest — a page
 * that calls notFound() outside the shell — which otherwise got Next's
 * bare "404 | This page could not be found", in English.
 */
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-shell-page">
      <RouteState variant="not-found" />
    </main>
  );
}
