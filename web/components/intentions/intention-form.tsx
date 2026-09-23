"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useFormContext } from "react-hook-form";

import { SelectField } from "@/components/forms/choice-fields";
import { MultiSelectField } from "@/components/forms/combobox-field";
import { PeriodField } from "@/components/forms/date-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { SelectableListField } from "@/components/forms/selectable-list-field";
import { useConfirm } from "@/components/interactions/confirm";
import {
  type Attachment,
  clearDraft,
  IntentionComposer,
} from "@/components/intentions/intention-composer";
import { DecisionStep } from "@/components/intentions/decision-step";
import { useCurrentWorkspace } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { submitIntention } from "@/lib/intentions/api";
import { notify } from "@/lib/notify";
import { type IntentionRequest, intentionRequestSchema } from "@/lib/validation/intentions";

/**
 * Step 1 of "Nouvelle intention": what to ask, and what to read to answer.
 *
 * Every field on this screen comes from LEKA-342's set, which is the point
 * of the ticket — the composer is the only thing built for this page, and
 * even it is a textarea with a keyboard contract. If any of it needs a
 * shape this form cannot express, the field is wrong, not the screen.
 *
 * TODO LEKA-341: sources, environments and services are mocked here. They
 * come from /sources and /workspaces/current once those screens exist.
 * TODO LEKA-384: submitIntention resolves after a delay and invents an id.
 */

const SOURCES = [
  { value: "github", title: "GitHub", subtitle: "12 dépôts" },
  { value: "jira", title: "Jira", subtitle: "Projet LEKA" },
  { value: "datadog", title: "Datadog", subtitle: "Métriques et traces" },
  { value: "confluence", title: "Confluence", subtitle: "Espace Produit" },
];

const ENVIRONMENTS = [
  { value: "production", label: "Production" },
  { value: "staging", label: "Pré-production" },
  { value: "dev", label: "Développement" },
];

const SERVICES = [
  { value: "payment-api", label: "Payment API" },
  { value: "auth-service", label: "Auth Service" },
  { value: "billing", label: "Billing" },
  { value: "notifications", label: "Notifications" },
];

export function IntentionForm() {
  const t = useDictionary();
  const confirm = useConfirm();
  const workspace = useCurrentWorkspace();
  // The palette hands the text over in the URL (LEKA-338). Reading it here
  // rather than in the composer keeps the composer usable anywhere.
  const params = useSearchParams();
  const prefilled = params.get("q") ?? "";
  // The decision step lives at ?step=decision rather than at a route of its
  // own: the route registry is LEKA-338's, and a skeleton does not earn an
  // entry in it. LEKA-341 gives it a real one.
  const onDecision = params.get("step") === "decision";
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [submittedId, setSubmittedId] = useState<string | null>(null);

  const form = useLekaForm<IntentionRequest>({
    schema: intentionRequestSchema,
    defaultValues: {
      text: prefilled,
      sources: ["github", "jira"],
      environment: "production",
      period: { preset: "7d", range: { from: "", to: "" } },
      services: [],
      attachments: [],
    },
    onSubmit: async (values) => {
      const created = await submitIntention({ ...values, attachments: attachments.map((a) => a.name) });
      clearDraft(workspace?.id);
      setSubmittedId(created.id);
      notify.success({ title: t.composer.submit, description: t.states.unavailableTitle });
    },
  });

  useUnsavedChangesGuard(form.formState.isDirty && submittedId === null);

  async function abandon() {
    const text = form.getValues("text");
    // Nothing typed, nothing to lose: asking would be a dialog about an
    // empty box.
    if (text.trim() !== "") {
      const leave = await confirm({
        title: t.composer.abandonTitle,
        description: t.composer.abandonBody,
        confirmLabel: t.composer.abandonConfirm,
        destructive: true,
      });
      if (!leave) return;
    }
    clearDraft(workspace?.id);
    form.reset();
  }

  if (onDecision) return <DecisionStep />;

  if (submittedId !== null) {
    return (
      <div
        data-testid="intention-step-2"
        className="rounded-xl border border-shell-line bg-white p-8 text-center"
      >
        <h2 className="text-lg font-semibold text-brand-navy">{t.tabs.analysis}</h2>
        <p className="mt-2 text-sm text-shell-muted">{t.states.unavailableBody}</p>
      </div>
    );
  }

  return (
    <Form form={form} className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
      <div className="space-y-4">
        <FormAlert />
        <IntentionComposer
          attachments={attachments}
          onAttachmentsChange={setAttachments}
          onSubmit={() => void form.submit()}
          submitting={form.formState.isSubmitting}
        />
        <Button type="button" variant="ghost" size="sm" onClick={() => void abandon()}>
          {t.forms.cancel}
        </Button>
      </div>

      <aside className="space-y-4">
        <Panel title={t.composer.contextTitle} aside={<WhySources />}>
          <SelectableListField<IntentionRequest, "sources">
            name="sources"
            label={t.composer.contextTitle}
            items={SOURCES}
            selectAll
            className="[&>label]:sr-only"
          />
        </Panel>

        <Panel title={t.composer.scopeTitle}>
          <ScopePanel />
        </Panel>
      </aside>
    </Form>
  );
}

function Panel({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-shell-nav">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function WhySources() {
  const t = useDictionary();
  return (
    <Popover>
      <PopoverTrigger className="text-xs text-brand-violet underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40">
        {t.composer.whySources}
      </PopoverTrigger>
      <PopoverContent className="max-w-xs text-sm">{t.composer.whySourcesBody}</PopoverContent>
    </Popover>
  );
}

/**
 * Read first, edit on request.
 *
 * The scope is right nine times out of ten — the workspace's own defaults —
 * and three controls open on a screen whose subject is a question above
 * them is three chances to fiddle with something that did not need it.
 */
function ScopePanel() {
  const t = useDictionary();
  const [editing, setEditing] = useState(false);
  const { getValues } = useFormContext<IntentionRequest>();

  if (!editing) {
    const values = getValues();
    const environment =
      ENVIRONMENTS.find((option) => option.value === values.environment)?.label ?? "—";
    const period =
      values.period.preset === "24h"
        ? t.forms.period24h
        : values.period.preset === "7d"
          ? t.forms.period7d
          : values.period.preset === "30d"
            ? t.forms.period30d
            : t.forms.periodCustom;
    const services =
      values.services.length === 0
        ? "—"
        : SERVICES.filter((option) => values.services.includes(option.value))
            .map((option) => option.label)
            .join(", ");

    return (
      <div className="space-y-2 text-sm">
        <Line label={t.composer.environment} value={environment} />
        <Line label={t.composer.period} value={period} />
        <Line label={t.composer.services} value={services} />
        <Button type="button" variant="link" size="sm" onClick={() => setEditing(true)}>
          {t.composer.edit}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <SelectField<IntentionRequest, "environment">
        name="environment"
        label={t.composer.environment}
        options={ENVIRONMENTS}
      />
      <PeriodField<IntentionRequest> name="period" label={t.composer.period} />
      <MultiSelectField<IntentionRequest, "services">
        name="services"
        label={t.composer.services}
        optional
        options={SERVICES}
      />
      <Button type="button" variant="outline" size="sm" onClick={() => setEditing(false)}>
        {t.forms.save}
      </Button>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <p className="flex justify-between gap-3">
      <span className="text-shell-muted">{label}</span>
      <span className="text-right font-medium text-shell-nav">{value}</span>
    </p>
  );
}
