"use client";

import { Building2 } from "lucide-react";

import { IconTile } from "@/components/environment/parts";
import { ActionEndpoints } from "@/components/settings/action-endpoints";
import { LanguageModel } from "@/components/settings/language-model";
import { LanguageSettings } from "@/components/settings/language-settings";
import { WorkspaceGeneralForm } from "@/components/settings/workspace-general-form";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useDictionary } from "@/lib/i18n/locale-provider";

function Settings() {
  const t = useDictionary();
  return (
    <PageContainer>
      <PageHeader title={t.nav.settings} subtitle={t.settings.subtitle} />
      <div className="flex flex-col gap-6">
        {/* The person's language and region, and the workspace's language. */}
        <LanguageSettings />
        {/* A card like the others (LEKA-438): it was the one block without. */}
        <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="workspace-settings">
          <div className="mb-3 flex items-center gap-3">
            <IconTile icon={Building2} tone="violet" />
            <h2 className="font-semibold text-brand-navy">{t.settings.generalTitle}</h2>
          </div>
          <WorkspaceGeneralForm />
        </section>
        {/* The model that reads and answers (LEKA-394). */}
        <LanguageModel />
        {/* The systems LEKA may act through (LEKA-391). */}
        <ActionEndpoints />
      </div>
    </PageContainer>
  );
}

export default function Page() {
  return <Settings />;
}
