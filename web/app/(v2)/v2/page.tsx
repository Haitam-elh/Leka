"use client";

import { Suspense } from "react";

import { Home } from "@/components/v2/home";

export default function Page() {
  // The exchange open is in the address (?i=): read under a boundary.
  return (
    <Suspense fallback={null}>
      <Home />
    </Suspense>
  );
}
