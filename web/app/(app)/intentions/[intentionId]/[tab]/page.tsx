"use client";

import { IntentionScreen } from "@/components/intentions/intention-screen";

/**
 * A tab of an intention's page. The segment is the truth — see RouteTabs —
 * so each one is a real route rather than a piece of React state.
 */
export default function Page() {
  return <IntentionScreen />;
}
