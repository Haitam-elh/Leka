"use client";

import { useParams } from "next/navigation";

import { ApprovalsPage } from "@/components/approvals/approvals-page";

export default function Page() {
  const { approvalId } = useParams<{ approvalId: string }>();
  return <ApprovalsPage initialId={approvalId} />;
}
