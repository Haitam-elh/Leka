"use client";

import { ChevronDown, FileSearch, PencilLine } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { changeSaid } from "@/components/environment/context-freshness";
import { QualityPanel, qualityGapSaid } from "@/components/environment/context-quality";
import { gapSaid } from "@/components/intentions/gap-said";
import { UnderstandingPanel } from "@/components/intentions/understanding";
import { entityHref, IconTile, Logo, typeIcon, typeLabel } from "@/components/environment/parts";
import { IntelligenceSection, Pill } from "@/components/intelligence";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import type { AssembledContext, IntentPlan, QualityGap } from "@/lib/context";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";

/**
 * Step 2 of "Nouvelle intention", as mockup 03 draws it — with what LEKA
 * actually did (LEKA-373): what it understood of the question — its kind,
 * what it is about and how it knows, when, where — what is missing, said
 * rather than ignored, the context it gathered from the company model, and
 * the sources that context came from. Asked again, the same context is
 * made again and says what LEKA reads differently (LEKA-374); how sure LEKA
 * can be of that context, and what it lacks — the intention's gaps and its
 * own — as mockup 03's « Niveau de confiance » says it (LEKA-375). The findings
 * and the recommendations come with the analysis engine; nothing here
 * pretends to be them.
 */


const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

// Said where it lived (LEKA-373): its own module since LEKA-375.
export { gapSaid };

export function IntentContext({
  assembled,
  intention = null,
  onEdit,
}: {
  assembled: AssembledContext;
  /** The intention kept (LEKA-384): followed from Mes intentions. */
  intention?: IntentionDetail | null;
  onEdit: () => void;
}) {
  const t = useDictionary();
  const w = t.intent;
  const plan = assembled.intent;
  return (
    <div className="space-y-4" data-testid="intention-step-2">
      <section className="flex flex-col gap-4 rounded-xl border border-shell-line bg-white p-5">
        <div className="flex items-start gap-3">
          <IconTile icon={FileSearch} tone="violet" className="size-11" />
          <div className="min-w-0">
            <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.title}</h2>
            <p className="text-[0.8125rem] text-shell-muted">{w.body}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-shell-line bg-shell-canvas/60 px-4 py-3">
          <p className="min-w-0 flex-1 text-[0.9375rem] text-brand-navy">{assembled.purpose}</p>
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <PencilLine className="size-3.5" aria-hidden="true" />
            {w.edit}
          </Button>
          {intention ? (
            <Link
              href={routes.intention(intention.id)}
              className="text-[0.8125rem] font-medium text-shell-nav-active underline-offset-2 hover:underline"
              data-testid="intention-follow"
            >
              {w.follow}
            </Link>
          ) : null}
        </div>
        {assembled.trigger === "reasked" ? <AskedAgain assembled={assembled} /> : null}
      </section>
      {/* What LEKA understood of it (LEKA-385), and what it would ask. */}
      {intention?.understanding ? (
        <UnderstandingPanel understanding={intention.understanding} />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
        <div className="min-w-0 space-y-4">
          {plan || assembled.quality ? <Missing assembled={assembled} /> : null}
          <Gathered assembled={assembled} />
        </div>
        <div className="min-w-0 space-y-4">
          <QualityPanel assembled={assembled} compact level={2} title={t.quality.stepTitle} />
          {plan ? <Scope plan={plan} /> : null}
          <SourcesRead assembled={assembled} />
        </div>
      </div>

      <p className="rounded-xl bg-shell-highlight px-5 py-4 text-[0.8125rem] text-shell-muted">
        {w.next}
      </p>
    </div>
  );
}

/** Asked again (LEKA-374): which version this is, what LEKA reads
 * differently, and how what it gathered changed. */
function AskedAgain({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const read = (assembled.changes ?? []).filter(
    (change) => change.kind === "intent" && change.field !== "text",
  );
  const delta = assembled.delta;
  return (
    <div className="text-[0.8125rem] text-shell-muted" data-testid="intent-asked-again">
      <p className="font-medium text-brand-navy">
        {fill(t.intent.again, { version: assembled.version })}
      </p>
      {read.length > 0 ? (
        <ul className="mt-1 space-y-0.5">
          {read.map((change) => (
            <li key={change.field ?? ""}>{changeSaid(t, locale, change)}</li>
          ))}
        </ul>
      ) : null}
      {delta ? (
        <p className="mt-1 tabular-nums">
          {fill(t.intent.againDelta, {
            added: delta.added,
            removed: delta.removed,
            changed: delta.changed,
          })}
        </p>
      ) : null}
    </div>
  );
}

/** What is missing — the intention's gaps, and, judged (LEKA-375), the
 * context's own — the critical first. */
function Missing({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.intent.gaps;
  const names = new Map(assembled.elements.map((element) => [element.ref_id, element.label]));
  const said: QualityGap[] =
    assembled.quality?.gaps ??
    (assembled.intent?.gaps ?? []).map((gap) => ({
      ...gap,
      measure: "completeness",
      origin: "intent",
    }));
  const rank = { critical: 0, warning: 1, info: 2 } as const;
  const ordered = [...said].sort((a, b) => rank[a.severity] - rank[b.severity]);
  const tones = { critical: "danger", warning: "warning", info: "neutral" } as const;
  return (
    <IntelligenceSection kind="missing" title={fill(w.title, { count: said.length })} level={2}>
      {ordered.length === 0 ? (
        <p className="text-[0.8125rem] text-state-success" data-testid="intent-nothing-missing">
          {w.none}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="intent-gaps">
          {ordered.map((gap, index) => (
            <li
              key={`${gap.kind}-${index}`}
              className="flex items-start gap-2 text-[0.8125rem]"
              data-testid="intent-gap"
              data-kind={gap.kind}
              data-severity={gap.severity}
            >
              <Pill tone={tones[gap.severity]}>{t.quality.gaps.severity[gap.severity]}</Pill>
              <span className="min-w-0 text-brand-navy">{qualityGapSaid(t, gap, names)}</span>
            </li>
          ))}
        </ul>
      )}
    </IntelligenceSection>
  );
}


function Scope({ plan }: { plan: IntentPlan }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intent;
  const kinds = w.kinds as Record<string, string>;
  const how = w.how as Record<string, string>;
  const period = plan.period;
  const origin =
    period.origin === "text"
      ? fill(w.origin.text, { said: period.said ?? "" })
      : period.origin === "model"
        ? fill(w.origin.model, { said: period.said ?? "" })
        : period.origin === "asked"
          ? w.origin.asked
          : w.origin.kind;
  const sources = plan.constraints.find((c) => c.kind === "sources");
  return (
    <IntelligenceSection kind="context" title={w.scope.title} level={2}>
      <dl
        className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-[0.8125rem]"
        data-testid="intent-scope"
      >
        <dt className="text-shell-muted">{w.scope.kind}</dt>
        <dd className="text-brand-navy">
          <span className="font-medium">{kinds[plan.kind] ?? plan.kind}</span>
          {plan.kind_said.length ? (
            <span className="text-shell-muted"> · « {plan.kind_said.join(", ")} »</span>
          ) : null}
        </dd>
        <dt className="text-shell-muted">{w.scope.subjects}</dt>
        <dd>
          {plan.subjects.length === 0 ? (
            <span className="text-shell-muted">{w.scope.none}</span>
          ) : (
            <ul className="flex flex-wrap gap-1.5" data-testid="intent-subjects">
              {plan.subjects.map((subject) => (
                <li key={subject.entity_id}>
                  <Link
                    href={entityHref({ id: subject.entity_id, type: subject.type })}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md border border-shell-line bg-white px-2 py-0.5 text-xs text-brand-navy hover:bg-shell-canvas",
                      FOCUS,
                    )}
                  >
                    <span className="font-medium">{subject.name}</span>
                    <span className="text-shell-muted">
                      {subject.how === "named" && subject.said
                        ? fill(w.namedBy, { said: subject.said })
                        : (how[subject.how] ?? subject.how)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </dd>
        <dt className="text-shell-muted">{w.scope.period}</dt>
        <dd className="text-brand-navy">
          {fill(w.range, {
            since: exactDate(locale, period.since),
            until: exactDate(locale, period.until),
          })}
          <span className="block text-xs text-shell-muted">{origin}</span>
        </dd>
        <dt className="text-shell-muted">{w.scope.environment}</dt>
        <dd className="text-brand-navy">{plan.environment ?? w.scope.everywhere}</dd>
        <dt className="text-shell-muted">{w.scope.sources}</dt>
        <dd className="text-brand-navy">{sources ? sources.said : w.scope.allSources}</dd>
      </dl>
    </IntelligenceSection>
  );
}

function Gathered({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.intent.gathered;
  const [open, setOpen] = useState(false);
  const entities = assembled.elements.filter((e) => e.kind === "entity");
  const ties = assembled.elements.length - entities.length;
  const groups = useMemo(() => {
    const byType = new Map<string, typeof entities>();
    for (const element of entities) {
      const type = element.entity?.type ?? element.ref_type;
      byType.set(type, [...(byType.get(type) ?? []), element]);
    }
    return [...byType.entries()];
  }, [entities]);
  return (
    <IntelligenceSection
      kind="evidence"
      title={w.title}
      count={fill(w.count, { count: entities.length })}
      level={2}
    >
      {entities.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.empty}</p>
      ) : (
        <>
          <ul className="divide-y divide-shell-line/60" data-testid="intent-gathered">
            {groups.map(([type, things]) => {
              const kinds = [
                ...new Set(things.flatMap((e) => e.provenance.sources.map((s) => s.kind))),
              ].filter((kind): kind is string => Boolean(kind));
              return (
                <li key={type} className="flex items-center gap-3 py-2 text-[0.8125rem]">
                  <IconTile icon={typeIcon(type)} tone="violet" className="size-9" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-brand-navy">
                      {typeLabel(t, type)} · {things.length}
                    </span>
                    <span className="block truncate text-xs text-shell-muted">
                      {things
                        .slice(0, 3)
                        .map((e) => e.label)
                        .join(", ")}
                    </span>
                  </span>
                  <span className="flex shrink-0 gap-1">
                    {kinds.slice(0, 4).map((kind) => (
                      <Logo key={kind} kind={kind} className="size-4" />
                    ))}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-shell-muted">{fill(w.ties, { count: ties })}</p>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className={cn(
              "mt-2 flex items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active hover:underline",
              FOCUS,
            )}
          >
            {open ? w.less : w.more}
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
          {open ? (
            <ul className="mt-2 flex flex-wrap gap-1.5" data-testid="intent-elements">
              {entities.map((element) => (
                <li key={element.ref_id}>
                  <Link
                    href={entityHref({
                      id: element.ref_id,
                      type: element.entity?.type ?? element.ref_type,
                    })}
                    className={cn(
                      "rounded-md bg-shell-canvas px-2 py-0.5 text-xs text-brand-navy hover:underline",
                      FOCUS,
                    )}
                  >
                    {element.label}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </IntelligenceSection>
  );
}

function SourcesRead({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.intent.read;
  return (
    <IntelligenceSection kind="evidence" title={w.title} level={2}>
      {assembled.sources.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="space-y-2 text-[0.8125rem]" data-testid="intent-sources">
          {assembled.sources.map((source) => (
            <li key={source.source_id} className="flex items-center gap-2">
              {source.kind ? <Logo kind={source.kind} className="size-5" /> : null}
              <span className="min-w-0 flex-1 truncate text-brand-navy">
                {source.name ?? t.environment.sheet.context.deletedSource}
              </span>
              <span className="shrink-0 text-xs text-shell-muted">
                {fill(w.count, { count: source.elements })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </IntelligenceSection>
  );
}
