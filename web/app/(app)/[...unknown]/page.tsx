"use client";

import { PageContainer } from "@/components/shell/page-container";
import { RouteState } from "@/components/shell/route-state";

/**
 * Any address inside the application that matches no route.
 *
 * A catch-all rather than app/not-found.tsx, because a 404 that drops the
 * sidebar tells someone who mistyped a URL that they have been logged out.
 * Here they keep the frame, and a way back.
 */
export default function UnknownRoute() {
  return (
    <PageContainer>
      <RouteState variant="not-found" />
    </PageContainer>
  );
}
