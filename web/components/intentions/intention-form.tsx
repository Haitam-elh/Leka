"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useWatch } from "react-hook-form";

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
import { IntentContext } from "@/components/intentions/intent-context";
import { useCurrentWorkspace } from "@/components/shell/shell-provider";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { routes } from "@/config/routes";
import { useEnvironment } from "@/lib/environment-queries";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { ApiError } from "@/lib/api";
import type { AssembledContext } from "@/lib/context";
import { intentAsk, submitIntention } from "@/lib/intentions/api";
import { notify } from "@/lib/notify";
import { KIND_CATEGORY, type Source } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";
import { type IntentionRequest, intentionRequestSchema } from "@/lib/validation/intentions";

/**
 * Step 1 of "Nouvelle intention": what to ask, and what to read to answer.
 *
 * Every field on this screen comes from LEKA-342's set, which is the point
 * of the ticket — the composer is the only thing built for this page, and
 * even it is a textarea with a keyboard contract. If any of it needs a
 * shape this form cannot express, the field is wrong, not the screen.
 *
 * WHAT IT OFFERS IS THE WORKSPACE'S OWN (LEKA-341). The sources are those
 * it has connected and can read — active, or degraded but still read — all
 * ticked once they arrive, as mockup 02's list; none connected says so and
 * leads to connecting one. The environments and the services are those the
 * company model knows, from the environment's map (LEKA-359): "Tous les
 * environnements" first, production chosen when there is one. Nothing is
 * offered that the workspace does not have.
 *
 * SUBMITTED, IT IS READ. Until LEKA-384 keeps intentions, submitting one
 * assembles the context it asks for (LEKA-373) and step 2 shows it: what
 * LEKA understood, what is missing, what it gathered (intent-context.tsx).
 */

/** Every environment: the scope's default when the model names none. */
const ALL = "all";

/** The sources LEKA can read from: connected, and not broken or off. */
function readable(source: Source): boolean {
  return source.status === "active" || source.status === "degraded";
}

/** The scope's choices, read from the company model. */
interface ScopeOptions {
  environments: { value: string; label: string }[];
  services: { value: string; label: string }[];
}

export function IntentionForm() {
  const t = useDictionary();
  const confirm = useConfirm();
  const workspace = useCurrentWorkspace();
  // The palette hands the text over in the URL (LEKA-338). Reading it here
  // rather than in the composer keeps the composer usable anywhere.
  const params = useSearchParams();
  const prefilled = params.get("q") ?? "";
  // The decision step lives at ?step=decision rather than at a route of its
  // own: the route registry is LEKA-338's, and a step that only shows an
  // example (LEKA-341) does not earn an entry in it. Decisions do
  // (LEKA-390).
  const onDecision = params.get("step") === "decision";
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [assembled, setAssembled] = useState<AssembledContext | null>(null);

  const form = useLekaForm<IntentionRequest>({
    schema: intentionRequestSchema,
    defaultValues: {
      text: prefilled,
      // Ticked once they arrive: the workspace's, never a guess.
      sources: [],
      environment: ALL,
      period: { preset: "7d", range: { from: "", to: "" } },
      services: [],
      attachments: [],
    },
    onSubmit: async (values) => {
      const ask = intentAsk(values, {
        everySource: values.sources.length === sourceItems.length,
        periodChosen: form.getFieldState("period").isDirty,
      });
      try {
        const made = await submitIntention(ask);
        clearDraft(workspace?.id);
        setAssembled(made);
        notify.success({ title: t.composer.submit });
      } catch (caught) {
        // Nothing to start from: said in the words of the form, not the API's.
        if (caught instanceof ApiError && caught.status === 422) {
          form.setError("root", { type: "server", message: t.intent.nothing });
          return;
        }
        throw caught;
      }
    },
  });

  useUnsavedChangesGuard(form.formState.isDirty && assembled === null);

  const sources = useSources();
  const environment = useEnvironment();
  const sourceItems = useMemo(
    () =>
      (sources.data ?? []).filter(readable).map((source) => ({
        value: source.id,
        title: source.display_name,
        subtitle: `${sourceTitle(source.type)} · ${
          t.sources.categories[KIND_CATEGORY[source.type] ?? "other"]
        }`,
        icon: <SourceLogo kind={source.type} className="size-5" />,
      })),
    [sources.data, t],
  );
  const scope = useMemo<ScopeOptions>(() => {
    const known = environment.data;
    const services = new Map<string, string>();
    for (const node of known?.nodes ?? []) {
      if (node.type === "service" && node.entity_id) services.set(node.entity_id, node.name);
    }
    return {
      environments: [
        { value: ALL, label: t.composer.allEnvironments },
        // "production" as the model says it, "Production" as a person reads it.
        ...(known?.environments ?? []).map((name) => ({
          value: name,
          label: name.charAt(0).toLocaleUpperCase() + name.slice(1),
        })),
      ],
      services: [...services]
        .map(([value, label]) => ({ value, label }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    };
  }, [environment.data, t]);

  // What arrives fills what nobody has touched: every readable source, and
  // production when the model knows one. Not marked dirty — nobody typed it.
  const { getFieldState, setValue } = form;
  useEffect(() => {
    if (sourceItems.length === 0 || getFieldState("sources").isDirty) return;
    setValue("sources", sourceItems.map((item) => item.value));
  }, [sourceItems, getFieldState, setValue]);
  useEffect(() => {
    if (getFieldState("environment").isDirty) return;
    if (environment.data?.environments.includes("production")) {
      setValue("environment", "production");
    }
  }, [environment.data, getFieldState, setValue]);

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

  if (assembled !== null) {
    return <IntentContext assembled={assembled} onEdit={() => setAssembled(null)} />;
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

      <aside aria-label={t.composer.sidePanel} className="space-y-4">
        <Panel title={t.composer.contextTitle} aside={<WhySources />}>
          {sources.isPending ? (
            <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
          ) : sourceItems.length === 0 ? (
            <div className="space-y-2 text-sm" data-testid="intention-no-sources">
              <p className="text-shell-muted">{t.composer.noSources}</p>
              <Link
                href={routes.sources()}
                className="font-medium text-brand-violet underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {t.composer.connectSource}
              </Link>
            </div>
          ) : (
            <SelectableListField<IntentionRequest, "sources">
              name="sources"
              label={t.composer.contextTitle}
              items={sourceItems}
              selectAll
              // The panel's heading already says it.
              hideLabel
            />
          )}
        </Panel>

        <Panel title={t.composer.scopeTitle}>
          <ScopePanel options={scope} />
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
      {/* Wraps as a whole: at 1024px the link used to break and leave its
          question mark alone on a line. */}
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
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
      <PopoverTrigger className="text-xs whitespace-nowrap text-brand-violet underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40">
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
function ScopePanel({ options }: { options: ScopeOptions }) {
  const t = useDictionary();
  const [editing, setEditing] = useState(false);
  // Watched, not read once: production is chosen after the model arrives,
  // and the summary must say so.
  const values = useWatch<IntentionRequest>() as IntentionRequest;

  if (!editing) {
    const environment =
      options.environments.find((option) => option.value === values.environment)?.label ?? "—";
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
        ? t.composer.allServices
        : options.services
            .filter((option) => values.services.includes(option.value))
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
        options={options.environments}
      />
      <PeriodField<IntentionRequest> name="period" label={t.composer.period} />
      <MultiSelectField<IntentionRequest, "services">
        name="services"
        label={t.composer.services}
        optional
        options={options.services}
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
