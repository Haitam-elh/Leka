"use client";

import { useId, useState } from "react";

import { cn } from "cn";

import { gapSaid } from "@/components/intentions/gap-said";
import {
  ConfidenceBadge,
  IntelligenceSection,
  Pill,
  retrieverName,
} from "@/components/intelligence";
import { SupportList } from "@/components/intelligence/confidence";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import {
  type AssembledContext,
  type ContextFeedbackCreate,
  type ContextQuality,
  contexts,
  type IntentGap,
  type QualityGap,
} from "@/lib/context";
import { useContextMutation, useContextQuality } from "@/lib/context-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Support } from "@/lib/intelligence";
import { notify } from "@/lib/notify";

/**
 * How good a context is (LEKA-375), as the Contexte tab and step 2 of a new
 * intention say it: its level and score, what that rests on — the sources
 * read, what happened, what two sources confirm, what they disagree on —
 * its completeness, reliability and freshness, each factor with the
 * elements it was read from; what it lacks, the critical first; what it
 * disagrees on and how badly; what each retrieval brought; what people said
 * of it, and a way to say more. The API's own sentences are for machines:
 * here each is said again from its kind and what it was read from. Nothing
 * is drawn that the API did not say.
 */

type Dictionary = ReturnType<typeof useDictionary>;

const SEVERITY_TONES = { critical: "danger", warning: "warning", info: "neutral" } as const;

const pct = (value: number) => `${Math.round(value * 100)} %`;

/** The things a context holds, by id: what a factor or a gap names. */
function namesOf(assembled: AssembledContext): Map<string, string> {
  return new Map(assembled.elements.map((element) => [element.ref_id, element.label]));
}

/** What the confidence rests on, as mockup 03 lists it. */
export function qualitySupport(t: Dictionary, quality: ContextQuality): Support[] {
  const w = t.quality.support;
  const s = quality.support;
  return [
    { id: "sources", label: fill(w.sources, { count: s.sources }), established: s.sources > 0 },
    { id: "events", label: fill(w.events, { count: s.events }), established: s.events > 0 },
    {
      id: "corroborated",
      label: fill(w.corroborated, { count: s.corroborated, entities: s.entities }),
      established: s.entities > 0 && s.corroborated * 2 >= s.entities,
    },
    {
      id: "conflicts",
      label:
        s.critical > 0
          ? fill(w.critical, { count: s.conflicts, critical: s.critical })
          : fill(w.conflicts, { count: s.conflicts }),
      established: s.critical === 0,
    },
  ];
}

/** A gap in words: an intention's as LEKA-373 says it, LEKA's from its
 * kind, what it was read from and the elements it names. */
export function qualityGapSaid(
  t: Dictionary,
  gap: QualityGap,
  names: ReadonlyMap<string, string>,
): string {
  if (gap.origin === "intent") return gapSaid(t, gap as unknown as IntentGap);
  const w = t.quality.gaps.kinds as Record<string, string>;
  const detail = (gap.detail ?? {}) as Record<string, unknown>;
  const refs = gap.refs ?? [];
  const facet = String(detail.facet ?? "");
  const said = w[gap.kind];
  if (!said) return gap.said;
  return fill(said, {
    count: Number(detail.count ?? refs.length),
    budget: Number(detail.budget ?? 0),
    hours: Number(detail.hours ?? 0),
    retriever: retrieverName(t, String(detail.retriever ?? "")),
    facet: (t.quality.facets as Record<string, string>)[facet] ?? facet,
    entity: String(detail.entity ?? names.get(refs[0] ?? "") ?? ""),
  });
}

/** The gaps, the critical first, each with its severity. */
export function QualityGaps({
  gaps,
  names,
}: {
  gaps: readonly QualityGap[];
  names: ReadonlyMap<string, string>;
}) {
  const t = useDictionary();
  const w = t.quality.gaps;
  if (gaps.length === 0) {
    return (
      <p className="text-[0.8125rem] text-state-success" data-testid="quality-no-gap">
        {w.none}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5" data-testid="quality-gaps">
      {gaps.map((gap, index) => (
        <li
          key={`${gap.kind}-${index}`}
          className="flex items-start gap-2 text-[0.8125rem]"
          data-testid="quality-gap"
          data-kind={gap.kind}
          data-severity={gap.severity}
        >
          <Pill tone={SEVERITY_TONES[gap.severity]}>{w.severity[gap.severity]}</Pill>
          <span className="min-w-0 text-brand-navy">{qualityGapSaid(t, gap, names)}</span>
        </li>
      ))}
    </ul>
  );
}

/** The score, the level, and what they rest on — and, unless compact, each
 * measure's factors, the gaps, the conflicts judged, what each retrieval
 * brought and what people said. */
export function QualityPanel({
  assembled,
  canMake = false,
  compact = false,
  level = 3,
  title,
}: {
  assembled: AssembledContext;
  canMake?: boolean;
  compact?: boolean;
  level?: 2 | 3;
  /** Step 2 says it as mockup 03: « Niveau de confiance ». */
  title?: string;
}) {
  const t = useDictionary();
  const w = t.quality;
  const quality = assembled.quality;
  const [open, setOpen] = useState(false);
  if (!quality) return null;
  const names = namesOf(assembled);
  return (
    <IntelligenceSection
      kind="confidence"
      title={title ?? w.title}
      level={level}
      action={<ConfidenceBadge score={quality.score} short detail={false} />}
    >
      <div className="space-y-3 text-[0.8125rem]" data-testid="context-quality">
        {quality.score !== null && quality.score !== undefined ? (
          <p className="-mt-1.5 text-xs text-shell-muted" data-testid="quality-score">
            {fill(w.score, { score: Math.round(quality.score * 100) })}
            {quality.capped ? ` · ${w.capped[quality.capped]}` : ""}
          </p>
        ) : null}
        <SupportList items={qualitySupport(t, quality)} />
        <Measures quality={quality} names={names} open={open && !compact} />
        {compact ? null : (
          <>
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen(!open)}
              className="rounded text-xs text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            >
              {open ? w.hideDetails : w.details}
            </button>
            <div>
              <p className="mb-1 font-semibold text-brand-navy">
                {fill(w.gaps.title, { count: quality.gaps.length })}
              </p>
              <QualityGaps gaps={quality.gaps} names={names} />
            </div>
            {quality.conflicts.length > 0 ? <Conflicts quality={quality} /> : null}
            {open ? <Retrieval quality={quality} /> : null}
            {quality.assessed === "read" ? (
              <p className="text-xs text-shell-muted">{w.read}</p>
            ) : null}
            <Feedback assembled={assembled} canMake={canMake} />
          </>
        )}
      </div>
    </IntelligenceSection>
  );
}

function Measures({
  quality,
  names,
  open,
}: {
  quality: ContextQuality;
  names: ReadonlyMap<string, string>;
  open: boolean;
}) {
  const t = useDictionary();
  const w = t.quality;
  return (
    <dl className="space-y-1.5" data-testid="quality-measures">
      {quality.measures.map((measure) => (
        <div
          key={measure.name}
          className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-x-2"
        >
          <dt className="text-shell-muted">{w.measures[measure.name]}</dt>
          <dd className="min-w-0">
            <span className="flex items-center gap-2">
              <span
                className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-shell-canvas"
                aria-hidden="true"
              >
                <span
                  className={cn(
                    "block h-full rounded-full",
                    (measure.score ?? 0) >= 0.85
                      ? "bg-state-success"
                      : (measure.score ?? 0) >= 0.6
                        ? "bg-state-warning"
                        : "bg-state-danger",
                  )}
                  style={{ width: `${Math.round((measure.score ?? 0) * 100)}%` }}
                />
              </span>
              <span className="w-12 text-end font-medium text-brand-navy tabular-nums">
                {measure.score === null || measure.score === undefined
                  ? w.unknown
                  : pct(measure.score)}
              </span>
            </span>
            {open ? (
              <ul className="mt-1 space-y-0.5 text-xs" data-testid="quality-factors">
                {measure.factors.map((factor) => {
                  const read = (factor.refs ?? [])
                    .map((ref) => names.get(ref))
                    .filter((name): name is string => Boolean(name));
                  return (
                    <li key={factor.name} className="text-shell-muted">
                      <span className="text-brand-navy">
                        {(w.factors as Record<string, string>)[factor.name] ?? factor.name}
                      </span>
                      {" · "}
                      {factor.value === null || factor.value === undefined
                        ? w.unknown
                        : pct(factor.value)}
                      {read.length > 0 ? ` · ${fill(w.readFrom, { names: read.join(", ") })}` : ""}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Conflicts({ quality }: { quality: ContextQuality }) {
  const t = useDictionary();
  const w = t.quality.conflicts;
  return (
    <div data-testid="quality-conflicts">
      <p className="mb-1 font-semibold text-brand-navy">
        {fill(w.title, { count: quality.conflicts.length })}
      </p>
      <ul className="space-y-1.5">
        {quality.conflicts.map((conflict) => (
          <li
            key={conflict.id}
            className="flex items-start gap-2"
            data-testid="quality-conflict"
            data-severity={conflict.severity}
          >
            <Pill tone={SEVERITY_TONES[conflict.severity]}>
              {t.quality.gaps.severity[conflict.severity]}
            </Pill>
            <span className="min-w-0">
              <span className="font-medium text-brand-navy">
                {conflict.label} · {conflict.about}
              </span>
              <span className="block text-xs text-shell-muted">{w.why[conflict.severity]}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Retrieval({ quality }: { quality: ContextQuality }) {
  const t = useDictionary();
  const w = t.quality.retrieval;
  return (
    <div data-testid="quality-retrieval">
      <p className="mb-1 font-semibold text-brand-navy">{w.title}</p>
      <ul className="space-y-0.5 text-xs">
        {quality.retrieval.map((run) => (
          <li key={run.retriever} className="flex justify-between gap-2">
            <span className="text-brand-navy">{retrieverName(t, run.retriever)}</span>
            <span className="text-shell-muted tabular-nums">
              {run.status === "ok"
                ? fill(w.line, { found: run.found, kept: run.kept, only: run.only, top: run.top })
                : (t.intelligence.context.runStatus as Record<string, string>)[run.status] ??
                  run.status}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What people said of this version, and a way to say what is missing. */
function Feedback({ assembled, canMake }: { assembled: AssembledContext; canMake: boolean }) {
  const t = useDictionary();
  const w = t.quality.feedback;
  const inspected = useContextQuality(assembled.context_id, assembled.version);
  const give = useContextMutation(contexts.feedback);
  const [note, setNote] = useState("");
  const id = useId();
  const counts = inspected.data?.feedback;

  function send(event: React.FormEvent) {
    event.preventDefault();
    give.mutate(
      {
        id: assembled.context_id,
        body: { version: assembled.version, verdict: "missing", note: note.trim() },
      },
      {
        onSuccess: () => {
          setNote("");
          notify.success({ title: w.sent });
        },
        onError: () => notify.error({ title: w.failed }),
      },
    );
  }

  return (
    <div data-testid="quality-feedback">
      <p className="mb-1 font-semibold text-brand-navy">{w.title}</p>
      <p className="text-xs text-shell-muted" data-testid="quality-feedback-counts">
        {counts ? fill(w.counts, { ...counts }) : "…"}
      </p>
      {canMake ? (
        <form className="mt-2 flex gap-2" onSubmit={send}>
          <label htmlFor={id} className="sr-only">
            {w.missing}
          </label>
          <Input
            id={id}
            value={note}
            maxLength={500}
            placeholder={w.missingHint}
            onChange={(event) => setNote(event.target.value)}
            className="h-8 text-xs"
          />
          <Button
            type="submit"
            size="sm"
            variant="outline"
            disabled={!note.trim() || give.isPending}
          >
            {w.send}
          </Button>
        </form>
      ) : null}
    </div>
  );
}

/** "Cet élément vous sert-il ?" — useful, not useful, wrong — said once. */
export function ElementFeedback({
  contextId,
  version,
  refId,
}: {
  contextId: string;
  version: number;
  refId: string;
}) {
  const t = useDictionary();
  const w = t.quality.feedback;
  const give = useContextMutation(contexts.feedback);
  const [said, setSaid] = useState<ContextFeedbackCreate["verdict"] | null>(null);
  const verdicts = ["useful", "not_useful", "wrong"] as const;

  function say(verdict: (typeof verdicts)[number]) {
    give.mutate(
      { id: contextId, body: { version, ref_id: refId, verdict } },
      {
        onSuccess: () => {
          setSaid(verdict);
          notify.success({ title: w.sent });
        },
        onError: (error) =>
          notify.error({
            title: error instanceof ApiError && error.status === 404 ? w.gone : w.failed,
          }),
      },
    );
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2 text-xs"
      data-testid="element-feedback"
      role="group"
      aria-label={w.element}
    >
      <span className="text-shell-muted">{w.element}</span>
      {verdicts.map((verdict) => (
        <Button
          key={verdict}
          type="button"
          size="sm"
          variant={said === verdict ? "default" : "outline"}
          disabled={said !== null || give.isPending}
          aria-pressed={said === verdict}
          onClick={() => say(verdict)}
        >
          {w[verdict]}
        </Button>
      ))}
    </div>
  );
}
