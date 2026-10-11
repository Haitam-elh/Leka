"use client";

import { Suspense } from "react";

import { IntentionForm } from "@/components/intentions/intention-form";
import { IntentionStepper, StepBadge } from "@/components/intentions/intention-stepper";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

export default function Page() {
  const t = useDictionary();
  return (
    <PageContainer>
      <PageHeader
        title={t.nav.newIntention}
        subtitle={t.composer.lead}
        actions={<StepBadge step="intention" />}
      />
      {/* Mockup 02: the five steps, at the first. */}
      <IntentionStepper current="intention" reached={0} />
      {/* useSearchParams needs a boundary for static rendering. */}
      <Suspense fallback={null}>
        <IntentionForm />
      </Suspense>
    </PageContainer>
  );
}
