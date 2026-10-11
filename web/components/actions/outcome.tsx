"use client";

import {
  ArrowRight,
  Check,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  Database,
  Goal,
  Plus,
  RefreshCw,
  Sparkles,
  Target,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import type { Plan } from "@/lib/actions";
import { ApiError } from "@/lib/api";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  type Expectation,
  type ObservedResult,
  safeLink,
  type Verification,
} from "@/lib/outcomes";
import { useOutcomeAction } from "@/lib/outcomes-queries";
import { notify } from "@/lib/notify";

/**
 * What came of it (LEKA-392), in the tab Actions: what should be true once
 * the plan ran — LEKA's defaults, changed by who may approve before it
 * runs — then whether it came: each expectation met, not met, unknown or
 * awaiting a person, as the company model and the system that acted say
 * it; a person's word with what shows it; read again now, or concluded.
 * Concluded met, the company's context is built again: said, and where.
 */

const STATUS_TONES: Record<Verification["status"], TileTone> = {
  verifying: "violet",
  succeeded: "success",
  partial: "warning",
  failed: "danger",
};
const SEEN_LOOK: Record<ObservedResult["seen"], { icon: typeof Check; tone: TileTone }> = {
  met: { icon: CircleCheck, tone: "success" },
  not_met: { icon: CircleX, tone: "danger" },
  unknown: { icon: CircleHelp, tone: "neutral" },
  awaiting: { icon: UserRound, tone: "warning" },
};
const KIND_ICONS: Record<Expectation["kind"], typeof Check> = {
  healthy: Target,
  incident_resolved: CircleCheck,
  metric: Goal,
  confirmed: UserRound,
};

function said(value: unknown): string {
  return value === null || value === undefined ? "—" : String(value);
}

/** One expectation, in words. */
export function expectationSaid(t: Dictionary, expectation: Expectation): string {
  const w = t.outcome.said;
  const name = said(expectation.target?.name);
  switch (expectation.kind) {
    case "healthy":
      return fill(w.healthy, { name });
    case "incident_resolved":
      return fill(w.incident_resolved, { name, count: (expectation.incidents ?? []).length });
    case "metric": {
      const values = {
        metric: said(expectation.name),
        comparator: t.outcome.comparators[expectation.comparator ?? "eq"],
        value: said(expectation.value),
        name,
      };
      return fill(expectation.source === "system" ? w.metricSystem : w.metricModel, values);
    }
    case "confirmed":
      return fill(w.confirmed, { said: said(expectation.said) });
  }
}

/** What was read of it, in words — nothing when there is nothing to say. */
function resultSaid(t: Dictionary, result: ObservedResult): string | null {
  const w = t.outcome.details;
  switch (result.detail) {
    case "incidents":
      return result.value === 0
        ? w.noIncident
        : fill(w.incidents, { count: said(result.value) });
    case "state":
      return fill(w.state, { state: said(result.value) });
    case "still_open":
      return fill(w.still_open, { count: said(result.value) });
    case "not_seen_since":
    case "no_health":
    case "not_in_model":
    case "removed":
    case "not_reported":
    case "incident_unknown":
      return w[result.detail];
    default:
      return result.value === null || result.value === undefined || result.reported
        ? null
        : fill(w.value, { value: said(result.value) });
  }
}

function useOutcome(intentionId: string) {
  const t = useDictionary();
  const act = useOutcomeAction(intentionId);
  async function run(
    input: Parameters<typeof act.mutateAsync>[0],
    success?: string,
  ): Promise<boolean> {
    try {
      await act.mutateAsync(input);
      if (success) notify.success({ title: success });
      return true;
    } catch (error) {
      const refusal = error instanceof ApiError ? error.fieldErrors?.refusal : undefined;
      notify.error({
        title:
          refusal === "invalid_expectation"
            ? t.outcome.invalid
            : error instanceof ApiError
              ? error.message
              : String(error),
      });
      return false;
    }
  }
  return { run, pending: act.isPending };
}

// ── what is expected ────────────────────────────────────────────────────

type Thing = { id: string; name: string; type: string };

/** What the plan acts on: an expectation is about one of them. */
function thingsOf(plan: Plan): Thing[] {
  const found = new Map<string, Thing>();
  for (const step of plan.steps) {
    for (const target of step.targets) {
      const id = String(target.id ?? "");
      if (id && !found.has(id)) {
        found.set(id, { id, name: said(target.name), type: said(target.type) });
      }
    }
  }
  return [...found.values()];
}

const FIELD =
  "rounded-md border border-shell-line bg-white px-2 py-1.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

/** A new expectation, as a person says it: complete, or null. */
function drafted(
  kind: "healthy" | "metric" | "confirmed",
  form: {
    target: string;
    metric: string;
    comparator: NonNullable<Expectation["comparator"]>;
    value: string;
    source: Expectation["source"];
    said: string;
  },
  things: Thing[],
  taken: readonly Expectation[],
): Expectation | null {
  const thing = things.find((candidate) => candidate.id === form.target);
  const target = thing ? { id: thing.id, name: thing.name, type: thing.type } : null;
  const base = { name: null, comparator: null, value: null, said: null, incidents: [] };
  if (kind === "healthy") {
    if (!target) return null;
    return { ...base, id: `healthy:${target.id}`, kind, target, source: "model" };
  }
  if (kind === "confirmed") {
    const words = form.said.trim();
    if (!words) return null;
    let n = taken.filter((e) => e.kind === "confirmed").length + 1;
    while (taken.some((e) => e.id === `confirmed:${n}`)) n += 1;
    return { ...base, id: `confirmed:${n}`, kind, target: null, source: "model", said: words };
  }
  const metric = form.metric.trim();
  const raw = form.value.trim();
  if (!metric || !raw || (form.source === "model" && !target)) return null;
  const number = Number(raw.replace(",", "."));
  const value = Number.isFinite(number) ? number : raw;
  if (typeof value === "string" && form.comparator !== "eq") return null;
  const on = form.source === "model" ? target : null;
  return {
    ...base,
    id: `metric:${form.source}:${metric}${on ? `:${on.id}` : ""}`,
    kind,
    target: on,
    name: metric,
    comparator: form.comparator,
    value,
    source: form.source,
  };
}

function AddExpectation({
  plan,
  taken,
  onAdd,
}: {
  plan: Plan;
  taken: readonly Expectation[];
  onAdd: (expectation: Expectation) => void;
}) {
  const t = useDictionary();
  const w = t.outcome;
  const things = thingsOf(plan);
  const [kind, setKind] = useState<"healthy" | "metric" | "confirmed">("metric");
  const [form, setForm] = useState({
    target: things[0]?.id ?? "",
    metric: "",
    comparator: "lte" as NonNullable<Expectation["comparator"]>,
    value: "",
    source: "system" as Expectation["source"],
    said: "",
  });
  const set = (patch: Partial<typeof form>) => setForm((before) => ({ ...before, ...patch }));
  const onThing = kind === "healthy" || (kind === "metric" && form.source === "model");

  function add() {
    const made = drafted(kind, form, things, taken);
    if (!made) {
      notify.error({ title: w.incomplete });
      return;
    }
    if (taken.some((e) => e.id === made.id)) {
      notify.error({ title: w.invalid });
      return;
    }
    onAdd(made);
    set({ metric: "", value: "", said: "" });
  }

  return (
    <div
      className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-shell-line p-3"
      data-testid="expectation-add"
    >
      <label className="flex flex-col gap-1 text-xs text-shell-nav">
        {w.form.kind}
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as typeof kind)}
          className={FIELD}
          data-testid="expectation-kind"
        >
          {(["metric", "healthy", "confirmed"] as const).map((option) => (
            <option key={option} value={option}>
              {w.kinds[option]}
            </option>
          ))}
        </select>
      </label>
      {kind === "metric" ? (
        <>
          <label className="flex flex-col gap-1 text-xs text-shell-nav">
            {w.form.source}
            <select
              value={form.source}
              onChange={(event) => set({ source: event.target.value as Expectation["source"] })}
              className={FIELD}
              data-testid="expectation-source"
            >
              <option value="system">{w.form.sources.system}</option>
              <option value="model">{w.form.sources.model}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-shell-nav">
            {w.form.metric}
            <input
              value={form.metric}
              onChange={(event) => set({ metric: event.target.value })}
              placeholder="p95_ms"
              className={cn(FIELD, "w-32")}
              data-testid="expectation-metric"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-shell-nav">
            {w.form.comparator}
            <select
              value={form.comparator}
              onChange={(event) =>
                set({ comparator: event.target.value as NonNullable<Expectation["comparator"]> })
              }
              className={FIELD}
              data-testid="expectation-comparator"
            >
              {(["lt", "lte", "eq", "gte", "gt"] as const).map((option) => (
                <option key={option} value={option}>
                  {w.comparators[option]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-shell-nav">
            {w.form.value}
            <input
              value={form.value}
              onChange={(event) => set({ value: event.target.value })}
              className={cn(FIELD, "w-24")}
              data-testid="expectation-value"
            />
          </label>
        </>
      ) : null}
      {onThing ? (
        <label className="flex flex-col gap-1 text-xs text-shell-nav">
          {w.form.target}
          <select
            value={form.target}
            onChange={(event) => set({ target: event.target.value })}
            className={FIELD}
            data-testid="expectation-target"
          >
            {things.map((thing) => (
              <option key={thing.id} value={thing.id}>
                {thing.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {kind === "confirmed" ? (
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-shell-nav">
          {w.form.said}
          <input
            value={form.said}
            onChange={(event) => set({ said: event.target.value })}
            className={FIELD}
            data-testid="expectation-said"
          />
        </label>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={add}
        data-testid="expectation-add-button"
      >
        <Plus className="size-4" aria-hidden="true" />
        {w.add}
      </Button>
    </div>
  );
}

/** What should be true once it ran — changed by who may approve, before
 * it runs. */
export function ExpectedOutcome({ plan, steward }: { plan: Plan; steward: boolean }) {
  const t = useDictionary();
  const w = t.outcome;
  const { run, pending } = useOutcome(plan.intention_id);
  const [draft, setDraft] = useState<Expectation[] | null>(null);
  const editable = steward && plan.status === "planned";
  const shown = draft ?? plan.expectations;

  async function save() {
    if (!draft) return;
    if (await run({ kind: "expect", expectations: draft }, w.saved)) setDraft(null);
  }

  return (
    <Card
      title={w.expectedTitle}
      icon={<Goal className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        editable && !draft ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setDraft([...plan.expectations])}
            data-testid="expectations-edit"
          >
            {w.edit}
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-3" data-testid="expectations">
        <p className="text-[0.8125rem] text-shell-muted">{w.expectedBody}</p>
        {shown.length ? (
          <ul className="space-y-1.5 text-[0.875rem]">
            {shown.map((expectation) => {
              const Icon = KIND_ICONS[expectation.kind];
              return (
                <li
                  key={expectation.id}
                  className="flex items-start gap-2"
                  data-testid="expectation"
                  data-kind={expectation.kind}
                >
                  <Icon className="mt-0.5 size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
                  <span className="min-w-0 flex-1 text-brand-navy">
                    {expectationSaid(t, expectation)}
                  </span>
                  {draft ? (
                    <button
                      type="button"
                      aria-label={`${w.remove} : ${expectationSaid(t, expectation)}`}
                      className="rounded p-0.5 text-shell-muted hover:bg-shell-canvas hover:text-state-danger"
                      onClick={() => setDraft(draft.filter((e) => e.id !== expectation.id))}
                      data-testid="expectation-remove"
                    >
                      <X className="size-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-[0.8125rem] text-brand-navy">{w.expectedNone}</p>
        )}
        {draft ? (
          <>
            <AddExpectation
              plan={plan}
              taken={draft}
              onAdd={(expectation) => setDraft([...draft, expectation])}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                disabled={pending}
                onClick={() => void save()}
                data-testid="expectations-save"
              >
                <Check className="size-4" aria-hidden="true" />
                {w.save}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setDraft(null)}>
                {w.cancel}
              </Button>
            </div>
          </>
        ) : plan.status !== "planned" ? (
          <p className="text-xs text-shell-muted">{w.locked}</p>
        ) : null}
      </div>
    </Card>
  );
}

// ── whether it came ─────────────────────────────────────────────────────

function Report({
  intentionId,
  expectation,
  onDone,
}: {
  intentionId: string;
  expectation: Expectation;
  onDone: () => void;
}) {
  const t = useDictionary();
  const w = t.outcome;
  const { run, pending } = useOutcome(intentionId);
  const [note, setNote] = useState("");
  const [link, setLink] = useState("");
  async function say(met: boolean) {
    if (!note.trim()) {
      notify.error({ title: w.noteRequired });
      return;
    }
    const ok = await run({
      kind: "report",
      expectationId: expectation.id,
      met,
      note: note.trim(),
      link: link.trim() || null,
    });
    if (ok) onDone();
  }
  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-state-warning/40 bg-state-warning-soft/40 p-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.reportNote}</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          className={FIELD}
          data-testid="expectation-report-note"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.reportLink}</span>
        <input
          value={link}
          onChange={(event) => setLink(event.target.value)}
          className={FIELD}
          data-testid="expectation-report-link"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={pending}
          onClick={() => void say(true)}
          data-testid="expectation-met"
        >
          <Check className="size-4" aria-hidden="true" />
          {w.confirm}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={pending}
          className="border-state-danger/40 text-state-danger hover:bg-state-danger-soft"
          onClick={() => void say(false)}
          data-testid="expectation-not-met"
        >
          <CircleX className="size-4" aria-hidden="true" />
          {w.deny}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {w.cancel}
        </Button>
      </div>
    </div>
  );
}

function ResultLine({
  verification,
  expectation,
  result,
  steward,
}: {
  verification: Verification;
  expectation: Expectation;
  result: ObservedResult | undefined;
  steward: boolean;
}) {
  const t = useDictionary();
  const me = useCurrentUser();
  const w = t.outcome;
  const [reporting, setReporting] = useState(false);
  const seen = result?.seen ?? (expectation.kind === "confirmed" ? "awaiting" : "unknown");
  const look = SEEN_LOOK[seen];
  const Icon = look.icon;
  const detail = result ? resultSaid(t, result) : null;
  const reported = result?.reported as
    | { by?: string; note?: string; link?: string | null }
    | null
    | undefined;
  const link = safeLink(reported?.link);
  const open = verification.status === "verifying";
  return (
    <li
      className="flex flex-col rounded-lg border border-shell-line p-3"
      data-testid="verification-result"
      data-expectation={expectation.id}
      data-seen={seen}
    >
      <div className="flex flex-wrap items-start gap-2">
        <Icon
          className={cn(
            "mt-0.5 size-4 shrink-0",
            look.tone === "success" && "text-state-success",
            look.tone === "danger" && "text-state-danger",
            look.tone === "warning" && "text-state-warning",
            look.tone === "neutral" && "text-shell-muted",
          )}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="text-[0.875rem] text-brand-navy">{expectationSaid(t, expectation)}</p>
          {detail ? <p className="text-xs text-shell-muted">{detail}</p> : null}
          {reported?.note ? (
            <p className="text-xs text-brand-navy" data-testid="verification-reported">
              {fill(w.reported, {
                verdict: w.seen[seen],
                who: reported.by && reported.by === me?.id ? w.you : w.someone,
                note: reported.note,
              })}
              {link ? (
                <>
                  {" · "}
                  <a
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-shell-nav-active hover:underline"
                  >
                    {w.open}
                  </a>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
        <Pill tone={look.tone} data-testid="verification-seen">
          {w.seen[seen]}
        </Pill>
        {open && steward && !reporting && seen !== "met" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setReporting(true)}
            data-testid="expectation-report"
          >
            {w.report}
          </Button>
        ) : null}
      </div>
      {reporting ? (
        <Report
          intentionId={verification.intention_id}
          expectation={expectation}
          onDone={() => setReporting(false)}
        />
      ) : null}
    </li>
  );
}

/** Whether what ran achieved what was expected. */
export function VerificationCard({
  verification,
  steward,
}: {
  verification: Verification;
  steward: boolean;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const me = useCurrentUser();
  const confirm = useConfirm();
  const w = t.outcome;
  const { run, pending } = useOutcome(verification.intention_id);
  const results = new Map(verification.results.map((r) => [r.expectation_id, r]));
  const open = verification.status === "verifying";
  const settling = open && new Date(verification.observe_after).getTime() > Date.now();
  const note = typeof verification.detail.note === "string" ? verification.detail.note : null;
  const rebuilt =
    verification.status === "succeeded" &&
    typeof verification.context_update.operation_id === "string";

  async function conclude() {
    const reason = await confirm({
      title: w.concludeTitle,
      description: w.concludeBody,
      confirmLabel: w.conclude,
      reasonLabel: w.concludeReason,
    });
    if (reason === null) return;
    if (!reason.trim()) {
      notify.error({ title: w.reasonRequired });
      return;
    }
    await run({ kind: "conclude", note: reason.trim() });
  }

  return (
    <Card
      title={w.verificationTitle}
      icon={<Sparkles className="size-4 text-shell-nav-active" aria-hidden="true" />}
      action={
        <Pill tone={STATUS_TONES[verification.status]} data-testid="verification-status">
          {w.statuses[verification.status]}
        </Pill>
      }
    >
      <div
        className="flex flex-col gap-3"
        data-testid="verification"
        data-status={verification.status}
      >
        {open ? (
          <p className="text-[0.8125rem] text-shell-muted">
            {settling
              ? fill(w.settle, { at: exactDate(locale, verification.observe_after) })
              : fill(w.until, { at: exactDate(locale, verification.deadline) })}
            {verification.observed_at
              ? ` ${fill(w.observed, { when: timeAgo(t, verification.observed_at) })}`
              : ""}
          </p>
        ) : (
          <p
            className={cn(
              "text-[0.875rem]",
              verification.status === "succeeded" ? "text-brand-navy" : "text-state-danger",
            )}
          >
            {verification.status === "succeeded"
              ? w.succeededBody
              : verification.status === "partial"
                ? w.partialBody
                : w.failedBody}
          </p>
        )}
        {verification.expectations.length ? (
          <ul className="flex flex-col gap-2" data-testid="verification-results">
            {verification.expectations.map((expectation) => (
              <ResultLine
                key={expectation.id}
                verification={verification}
                expectation={expectation}
                result={results.get(expectation.id)}
                steward={steward}
              />
            ))}
          </ul>
        ) : (
          <p className="text-[0.8125rem] text-brand-navy">{w.expectedNone}</p>
        )}
        {note && verification.concluded_by ? (
          <p className="text-[0.8125rem] text-brand-navy" data-testid="verification-concluded">
            {fill(w.concludedBy, {
              who: verification.concluded_by === me?.id ? w.you : w.someone,
              note,
            })}
          </p>
        ) : null}
        {rebuilt ? (
          <p
            className="flex flex-wrap items-center gap-2 rounded-lg bg-state-success-soft/60 px-3 py-2 text-[0.8125rem] text-brand-navy"
            data-testid="verification-context"
          >
            <Database className="size-4 text-state-success" aria-hidden="true" />
            {w.context}
            <Link href={routes.activity()} className="font-medium text-shell-nav-active hover:underline">
              {w.contextLink}
            </Link>
          </p>
        ) : null}
        {open ? (
          steward ? (
            <div className="flex flex-wrap gap-2" data-testid="verification-controls">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={pending}
                onClick={() => void run({ kind: "check" })}
                data-testid="verification-check"
              >
                <RefreshCw className="size-4" aria-hidden="true" />
                {w.checkNow}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={pending}
                onClick={() => void conclude()}
                data-testid="verification-conclude"
              >
                <CircleDashed className="size-4" aria-hidden="true" />
                {w.conclude}
              </Button>
            </div>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.readOnly}</p>
          )
        ) : null}
      </div>
    </Card>
  );
}

/** "De l'intention à l'impact." — and its whole story, one click away. */
export function ImpactBanner({ intentionId }: { intentionId: string }) {
  const t = useDictionary();
  const w = t.outcome;
  return (
    <section
      className="flex flex-wrap items-center gap-4 rounded-xl bg-brand-violet-soft/60 px-5 py-4"
      data-testid="impact-banner"
    >
      <Sparkles className="size-6 shrink-0 text-shell-nav-active" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-brand-navy">{w.impactTitle}</p>
        <p className="text-[0.8125rem] text-shell-muted">{w.impactBody}</p>
      </div>
      <Link
        href={routes.intention(intentionId, "history")}
        className={buttonVariants({ variant: "default" })}
        data-testid="impact-history"
      >
        {w.fullHistory}
        <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
      </Link>
    </section>
  );
}
