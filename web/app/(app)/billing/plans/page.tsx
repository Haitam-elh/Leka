"use client";

import { Suspense } from "react";

import { PlansPage } from "@/components/billing/plans-page";

export default function Page() {
  return (
    // The plan and cadence offered are in the query (LEKA-527), and
    // useSearchParams needs a boundary for static rendering.
    <Suspense fallback={null}>
      <PlansPage />
    </Suspense>
  );
}
