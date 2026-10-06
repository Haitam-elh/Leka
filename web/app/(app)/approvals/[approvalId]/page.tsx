"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ApprovalsPage } from "@/components/approvals/approvals-page";

/** One item of À valider, opened: a proposal — or, with `?kind=conflict`,
 * a conflict between sources (LEKA-382). */
function Opened() {
  const { approvalId } = useParams<{ approvalId: string }>();
  const kind = useSearchParams().get("kind") === "conflict" ? "conflict" : "candidate";
  return <ApprovalsPage initialId={approvalId} initialKind={kind} />;
}

export default function Page() {
  return (
    // useSearchParams needs a boundary for static rendering.
    <Suspense fallback={null}>
      <Opened />
    </Suspense>
  );
}
