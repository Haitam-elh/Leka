"use client";

import { CompactIntentionComposer } from "@/components/intentions/compact-composer";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

export default function Page() {
  const t = useDictionary();
  return (
    <PageContainer>
      <PageHeader title={t.nav.overview} subtitle={t.composer.compactTitle} />
      <CompactIntentionComposer />
    </PageContainer>
  );
}
