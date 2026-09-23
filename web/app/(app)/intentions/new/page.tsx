"use client";

import { Suspense } from "react";

import { IntentionForm } from "@/components/intentions/intention-form";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

export default function Page() {
  const t = useDictionary();
  return (
    <PageContainer>
      <PageHeader title={t.nav.newIntention} subtitle={t.composer.compactTitle} />
      {/* useSearchParams needs a boundary for static rendering. */}
      <Suspense fallback={null}>
        <IntentionForm />
      </Suspense>
    </PageContainer>
  );
}
