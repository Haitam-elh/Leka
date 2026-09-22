"use client";

import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A placeholder, on purpose: this ticket builds the frame, not the pictures
 * inside it. What it proves is that every route wears the same shell.
 */
export default function EnvironmentPage() {
  const t = useDictionary();

  return (
    <PageContainer>
      <PageHeader title={t.nav.environment} />
      <p className="text-sm text-shell-muted">{t.shell.emptyPage}</p>
    </PageContainer>
  );
}
