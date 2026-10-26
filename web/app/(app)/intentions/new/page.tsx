"use client";

import { Suspense, useState } from "react";

import { IntentionForm } from "@/components/intentions/intention-form";
import {
  IntentionStepper,
  type Step,
  StepBadge,
} from "@/components/intentions/intention-stepper";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { SourceLocked, useSourceLock } from "@/components/sources/source-lock";
import { useDictionary } from "@/lib/i18n/locale-provider";

export default function Page() {
  const t = useDictionary();
  // Sent, the request is being analysed: the steps say so (LEKA-438).
  const [step, setStep] = useState<Step>("intention");
  // Under a contract, nothing connected (2026-10-25): the question waits.
  const locked = useSourceLock();
  return (
    <PageContainer>
      <PageHeader
        title={t.nav.newIntention}
        subtitle={t.composer.lead}
        actions={<StepBadge step={step} />}
      />
      {locked ? (
        <SourceLocked what="ask" />
      ) : (
        <>
          {/* Mockup 02: the five steps, at the first. */}
          <IntentionStepper current={step} reached={step === "intention" ? 0 : 1} />
          {/* useSearchParams needs a boundary for static rendering. */}
          <Suspense fallback={null}>
            <IntentionForm onStep={setStep} />
          </Suspense>
        </>
      )}
    </PageContainer>
  );
}
