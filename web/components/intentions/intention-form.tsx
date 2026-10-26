"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useWatch } from "react-hook-form";

import { SelectField } from "@/components/forms/choice-fields";
import { MultiSelectField } from "@/components/forms/combobox-field";
import { PeriodField } from "@/components/forms/date-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { SelectableListField } from "@/components/forms/selectable-list-field";
import { useConfirm } from "@/components/interactions/confirm";
import { useAttachments } from "@/components/intentions/attachments";
import { clearDraft, IntentionComposer } from "@/components/intentions/intention-composer";
import { BriefView } from "@/components/intentions/brief";
import { DecisionStep } from "@/components/intentions/decision-step";
import { FeasibilityPanel } from "@/components/intentions/feasibility";
import { ControlNotice } from "@/components/intelligence";
import { IntentContext } from "@/components/intentions/intent-context";
import type { Step } from "@/components/intentions/intention-stepper";
import { useCurrentWorkspace, usePermissions } from "@/components/shell/shell-provider";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { routes } from "@/config/routes";
import { useEnvironment } from "@/lib/environment-queries";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { ApiError } from "@/lib/api";
import type { AssembledContext } from "@/lib/context";
import {
  intentAsk,
  type IntentionAnswer,
  type IntentionDetail,
  type IntentionPreview,
  intentions,
  reaskIntention,
  submitIntention,
} from "@/lib/intentions/api";
import { intentionKeys, useIntention } from "@/lib/intentions/queries";
import { notify } from "@/lib/notify";
import { isConnected, KIND_CATEGORY, type Source } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";
import {
  type IntentionRequest,
  intentionRequestSchema,
} from "@/lib/validation/intentions";

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

/** One of each kind first, then the next of each — code, tickets, docs,
 * cloud, observability… — as mockup 02 lists them: the first few rows say
 * what LEKA reads, not three repositories in a row. Alphabetical within a
 * kind. */
const KINDS_FIRST = [
  "code",
  "project",
  "docs",
  "cloud",
  "observability",
  "data",
  "chat",
  "custom",
];

export function oneOfEach(sources: readonly Source[]): Source[] {
  const kinds = new Map<string, Source[]>();
  for (const source of [...sources].sort((a, b) =>
    a.display_name.localeCompare(b.display_name),
  )) {
    const kind = KIND_CATEGORY[source.type] ?? "other";
    kinds.set(kind, [...(kinds.get(kind) ?? []), source]);
  }
  const rank = (kind: string) => {
    const at = KINDS_FIRST.indexOf(kind);
    return at === -1 ? KINDS_FIRST.length : at;
  };
  const ordered: Source[] = [];
  const queues = [...kinds.entries()]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([, queue]) => queue);
  for (let round = 0; ordered.length < sources.length; round++) {
    for (const queue of queues) if (queue[round]) ordered.push(queue[round]);
  }
  return ordered;
}

/** The scope's choices, read from the company model. */
interface ScopeOptions {
  environments: { value: string; label: string }[];
  services: { value: string; label: string }[];
}

export function IntentionForm({
  onStep,
}: {
  /** The step it is on: "analysis" once sent, so the page's steps say so. */
  onStep?: (step: Step) => void;
} = {}) {
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
  // Its files, sent as they are chosen: only those kept go with it.
  const files = useAttachments();
  const [assembled, setAssembled] = useState<AssembledContext | null>(null);
  useEffect(() => {
    onStep?.(assembled ? "analysis" : "intention");
  }, [assembled, onStep]);
  // Edited after step 2: the same intention is asked again (LEKA-374) —
  // its id, kept (LEKA-384). Opened with ?intention=<id> — an intention
  // LEKA needs clarified (LEKA-385) — it is that one, asked again.
  const clarifying = params.get("intention");
  const [reasking, setReasking] = useState<string | null>(clarifying);
  const [intention, setIntention] = useState<IntentionDetail | null>(null);
  const kept = useIntention(clarifying ?? "");
  const client = useQueryClient();
  // Before it is asked (LEKA-439): what LEKA understood of it, what it asks,
  // what it takes — read again with each answer, and with the request as it
  // stands; the answers sent with it once launched.
  const [preview, setPreview] = useState<IntentionPreview | null>(null);
  const [answers, setAnswers] = useState<IntentionAnswer[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [readAs, setReadAs] = useState<string | null>(null);
  // One key per request as it stands (LEKA-443): sent again — a click
  // twice, a network that gave up and is retried — it is the intention it
  // made, never a second one. Changed, it is another request.
  const requestKey = useRef<{ ask: string; key: string } | null>(null);

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
      // A file on its way: asked once it is kept, or let go.
      if (files.uploading) {
        form.setError("root", { type: "server", message: t.composer.files.waiting });
        return;
      }
      // Its files, when it has some: without, the request is as it was.
      const ask = { ...askOf(values), answers, ...(files.ids.length ? { attachments: files.ids } : {}) };
      const said = JSON.stringify(ask);
      if (requestKey.current?.ask !== said) {
        requestKey.current = { ask: said, key: crypto.randomUUID() };
      }
      try {
        const made = reasking
          ? await reaskIntention(reasking, ask)
          : await submitIntention(ask, requestKey.current.key);
        clearDraft(workspace?.id);
        // Kept with it now: no longer the form's to remove.
        if (!reasking) files.clear();
        // What every list and page says of it is now this.
        client.setQueryData(
          intentionKeys.one(made.intention.id),
          made.intention,
        );
        void client.invalidateQueries({ queryKey: intentionKeys.all });
        setIntention(made.intention);
        setAssembled(made.context);
        notify.success({ title: t.composer.submit });
      } catch (caught) {
        // Under a contract, nothing connected (2026-10-25): said, the words kept.
        if (caught instanceof ApiError && caught.code === "source_required") {
          form.setError("root", { type: "server", message: t.sourceLock.refused });
          return;
        }
        // Nothing to start from: said in the words of the form, not the API's.
        if (caught instanceof ApiError && caught.status === 422) {
          form.setError("root", {
            type: "server",
            message:
              caught.fieldErrors?.attachments === "attachment_unknown"
                ? t.composer.files.unknown
                : caught.code === "off_topic"
                  ? t.intentions.brief.offTopic
                  : t.intent.nothing,
          });
          return;
        }
        throw caught;
      }
    },
  });

  useUnsavedChangesGuard(form.formState.isDirty && assembled === null);

  const sources = useSources();
  const canConnect = usePermissions()?.includes("source:manage") ?? false;
  // Connected yet unreadable (in error): said, not « Aucune source connectée ».
  const failing = (sources.data ?? []).filter((source) => isConnected(source) && !readable(source)).length;
  const environment = useEnvironment();
  const sourceItems = useMemo(
    () =>
      oneOfEach((sources.data ?? []).filter(readable)).map((source) => ({
        value: source.id,
        title: source.display_name,
        subtitle: `${sourceTitle(source.type)} · ${
          t.sources.categories[KIND_CATEGORY[source.type] ?? "other"]
        }`,
        icon: <SourceLogo kind={source.type} className="size-5" />,
      })),
    [sources.data, t],
  );
  /** The request as the API reads it, from what the form holds now. */
  function askOf(values: IntentionRequest) {
    return intentAsk(values, {
      everySource: values.sources.length === sourceItems.length,
      periodChosen: form.getFieldState("period").isDirty,
    });
  }

  /** What LEKA makes of it before it is asked — nothing kept. */
  async function review(given: IntentionAnswer[] = answers) {
    if (!(await form.trigger())) {
      // Nothing to read, no source field to show it on: said, not silent (LEKA-445).
      if (sources.data && sourceItems.length === 0) {
        form.setError("root", {
          type: "client",
          message: t.composer.noSources,
        });
      }
      return;
    }
    const ask = askOf(form.getValues());
    setReviewing(true);
    try {
      setPreview(await intentions.brief({ ...ask, answers: given }));
      setReadAs(JSON.stringify(ask));
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        form.setError("root", { type: "server", message: t.intent.nothing });
        return;
      }
      notify.error({ title: t.intentions.brief.failed });
    } finally {
      setReviewing(false);
    }
  }

  function answer(given: IntentionAnswer) {
    const next = [
      ...answers.filter((a) => a.question !== given.question),
      given,
    ];
    setAnswers(next);
    void review(next);
  }

  // Changed since it was read: read again before it is launched.
  const watched = useWatch({ control: form.control }) as IntentionRequest;
  const stale =
    preview !== null &&
    readAs !== JSON.stringify(askOf({ ...form.getValues(), ...watched }));
  const launchable =
    preview !== null &&
    !stale &&
    (preview.brief.decision === "analyse" ||
      preview.brief.decision === "continue");

  const scope = useMemo<ScopeOptions>(() => {
    const known = environment.data;
    const services = new Map<string, string>();
    for (const node of known?.nodes ?? []) {
      if (node.type === "service" && node.entity_id)
        services.set(node.entity_id, node.name);
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
    setValue(
      "sources",
      sourceItems.map((item) => item.value),
    );
  }, [sourceItems, getFieldState, setValue]);
  useEffect(() => {
    if (getFieldState("environment").isDirty) return;
    if (environment.data?.environments.includes("production")) {
      setValue("environment", "production");
    }
  }, [environment.data, getFieldState, setValue]);

  // The intention to clarify: its words, to be said better (LEKA-385).
  useEffect(() => {
    if (!kept.data || getFieldState("text").isDirty) return;
    setValue("text", kept.data.text);
  }, [kept.data, getFieldState, setValue]);

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
    return (
      <IntentContext
        assembled={assembled}
        intention={intention}
        onEdit={() => {
          setReasking(intention?.id ?? null);
          setAssembled(null);
          // New words, read anew: what was asked and answered before goes.
          setPreview(null);
          setAnswers([]);
        }}
      />
    );
  }

  return (
    <Form
      form={form}
      className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start"
    >
      <div className="space-y-4">
        <FormAlert />
        <IntentionComposer
          files={files}
          onSubmit={() => void review()}
          submitting={reviewing}
          submitLabel={
            preview ? t.intentions.brief.read : t.intentions.brief.review
          }
          suggested={preview === null}
        />
        {reviewing && !preview ? (
          <p className="text-[0.8125rem] text-shell-muted" role="status">
            {t.intentions.brief.reviewing}
          </p>
        ) : null}
        {preview ? (
          <section
            className="space-y-4"
            data-testid="intention-review"
            aria-busy={reviewing}
          >
            {stale ? (
              <p
                role="status"
                className="flex flex-wrap items-center gap-2 rounded-lg bg-state-warning-soft px-4 py-3 text-[0.8125rem] text-brand-navy"
                data-testid="intention-review-stale"
              >
                {t.intentions.brief.stale}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void review()}
                >
                  {t.intentions.brief.read}
                </Button>
              </p>
            ) : null}
            {preview.brief.decision === "off_topic" ? (
              // Not about technology: said what LEKA answers about — nothing
              // to answer, nothing greyed without a word (2026-10-14).
              <p
                role="status"
                className="rounded-lg bg-brand-violet-soft px-4 py-3 text-[0.875rem] text-brand-navy"
                data-testid="intention-off-topic"
              >
                {t.intentions.brief.offTopic}
              </p>
            ) : (
              <BriefView
                brief={preview.brief}
                understanding={preview.understanding}
                answers={answers}
                onAnswer={answer}
                pending={reviewing}
              />
            )}
            <ReadsCard sources={preview.sources} />
            <FeasibilityPanel feasibility={preview.feasibility} />
            <div className="flex flex-wrap items-center justify-end gap-3">
              {!launchable && !stale && preview.brief.decision !== "off_topic" ? (
                <span className="text-[0.8125rem] text-shell-muted">
                  {t.intentions.brief.launchBlocked}
                </span>
              ) : null}
              <Button
                type="button"
                disabled={!launchable || form.formState.isSubmitting}
                onClick={() => void form.submit()}
                data-testid="intention-launch"
              >
                {t.intentions.brief.launch}
              </Button>
            </div>
          </section>
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void abandon()}
        >
          {t.forms.cancel}
        </Button>
      </div>

      <aside aria-label={t.composer.sidePanel} className="space-y-4">
        <Panel title={t.composer.contextTitle} aside={<WhySources />}>
          {sources.isPending ? (
            <div
              className="h-24 animate-pulse rounded-lg bg-shell-canvas"
              aria-hidden="true"
            />
          ) : sourceItems.length === 0 ? (
            <div
              className="space-y-2 text-sm"
              data-testid="intention-no-sources"
            >
              <p className="text-shell-muted">
                {failing > 0 ? fill(t.composer.noReadable, { count: failing }) : t.composer.noSources}
              </p>
              {canConnect ? (
              <Link
                href={routes.sources()}
                className="font-medium text-brand-violet underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {t.composer.connectSource}
              </Link>
              ) : null}
            </div>
          ) : (
            <SelectableListField<IntentionRequest, "sources">
              name="sources"
              label={t.composer.contextTitle}
              items={sourceItems}
              selectAll
              max={5}
              more={t.composer.allSources}
              // The panel's heading already says it.
              hideLabel
            />
          )}
        </Panel>

        <Panel title={t.composer.scopeTitle}>
          <ScopePanel options={scope} />
        </Panel>
        {/* Mockup 02: nothing changes without a yes. */}
        <ControlNotice />
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
      <PopoverContent className="max-w-xs text-sm">
        {t.composer.whySourcesBody}
      </PopoverContent>
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
      options.environments.find((option) => option.value === values.environment)
        ?.label ?? "-";
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
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={() => setEditing(true)}
        >
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
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setEditing(false)}
      >
        {t.forms.save}
      </Button>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <p className="flex justify-between gap-3">
      <span className="text-shell-muted">{label}</span>
      <span className="text-end font-medium text-shell-nav">{value}</span>
    </p>
  );
}

/** What LEKA will read for it: the sources it is held to, else every one it
 * can (LEKA-439). */
function ReadsCard({ sources }: { sources: IntentionPreview["sources"] }) {
  const t = useDictionary();
  const w = t.intentions.brief;
  return (
    <section
      className="rounded-xl border border-shell-line bg-white p-4"
      data-testid="intention-reads"
    >
      <h2 className="mb-2 text-[0.875rem] font-semibold text-brand-navy">
        {w.reads}
      </h2>
      {sources.length ? (
        <>
          <p className="mb-2 text-[0.8125rem] text-shell-muted">
            {fill(w.readsAll, { count: sources.length })}
          </p>
          <ul className="flex flex-wrap gap-2">
            {sources.map((source) => (
              <li
                key={source.id}
                className="flex items-center gap-1.5 rounded-md bg-shell-canvas px-2 py-1 text-xs text-brand-navy"
              >
                <SourceLogo
                  kind={source.kind as Source["type"]}
                  className="size-3.5"
                />
                {source.name}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noSource}</p>
      )}
    </section>
  );
}
