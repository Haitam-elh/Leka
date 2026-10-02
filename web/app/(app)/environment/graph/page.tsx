"use client";

import { Suspense } from "react";

import { GraphExplorer } from "@/components/environment/graph-explorer";

/** The detailed map (LEKA-369): ?entity= centres it on one thing. */
export default function Page() {
  return (
    // useSearchParams needs a boundary for static rendering.
    <Suspense fallback={null}>
      <GraphExplorer />
    </Suspense>
  );
}
