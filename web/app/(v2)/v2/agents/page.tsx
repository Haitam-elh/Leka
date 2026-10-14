"use client";

import { Suspense } from "react";

import { AgentsScreen } from "@/components/v2/agents-screen";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <AgentsScreen />
    </Suspense>
  );
}
