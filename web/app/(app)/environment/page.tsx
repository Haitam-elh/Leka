"use client";

import { Suspense } from "react";

import { EnvironmentScreen } from "@/components/environment/environment-screen";

export default function Page() {
  return (
    // The tab is in the query, and useSearchParams needs a boundary for
    // static rendering.
    <Suspense fallback={null}>
      <EnvironmentScreen />
    </Suspense>
  );
}
