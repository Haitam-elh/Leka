"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

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
      <WorkspaceGeneralForm failOnce={failOnce} />
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
