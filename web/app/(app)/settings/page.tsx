"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ActionEndpoints } from "@/components/settings/action-endpoints";
import { WorkspaceGeneralForm } from "@/components/settings/workspace-general-form";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

function Settings() {
  const t = useDictionary();
  // ?fail=1 makes the save return LEKA-333's error shape, which is how the
  // server-error path is demonstrated without an endpoint to break.
  const failOnce = useSearchParams().get("fail") === "1";
  return (
    <PageContainer>
      <PageHeader title={t.nav.settings} subtitle={t.settings.generalTitle} />
      <div className="flex flex-col gap-6">
        <WorkspaceGeneralForm failOnce={failOnce} />
        {/* The systems LEKA may act through (LEKA-391). */}
        <ActionEndpoints />
      </div>
    </PageContainer>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <Settings />
    </Suspense>
  );
}
