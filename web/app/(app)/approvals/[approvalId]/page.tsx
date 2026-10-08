"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ApprovalsPage } from "@/components/approvals/approvals-page";

/** One item of À valider, opened: a proposal — or, with `?kind=conflict`,
 * a conflict between sources (LEKA-382); with `?kind=decision`, a decision
 * on what an intention asks to do (LEKA-390). */
function Opened() {
  const { approvalId } = useParams<{ approvalId: string }>();
  const said = useSearchParams().get("kind");
  const kind = said === "conflict" || said === "decision" ? said : "candidate";
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
