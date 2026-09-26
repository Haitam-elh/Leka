"use client";

import { ArrowDown, ArrowUp, Sparkles, X } from "lucide-react";
import { useId } from "react";

import { cn } from "cn";

import { type Dependency, DependencyList } from "@/components/knowledge/dependency-list";
import { EntityIcon } from "@/components/knowledge/entity-card";
import { EventTimeline, type TimelineEvent } from "@/components/knowledge/event-timeline";
import { FreshnessIndicator, QualityIndicator } from "@/components/knowledge/indicators";
import { type MetadataSection, MetadataPanel } from "@/components/knowledge/metadata-panel";
import { ProvenanceBadge } from "@/components/knowledge/provenance-badge";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { TONES } from "@/components/knowledge/status";
import { Button } from "@/components/ui/button";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { confidenceToScore, type KnowledgeEntity } from "@/lib/knowledge";

export interface EntityMetric {
  id: string;
  label: string;
  /** Already formatted, unit included: "520 ms", "4,2 %". */
  value: string;
  delta?: {
    value: string;
    direction: "up" | "down";
    /** Whether this direction is good news: latency up is not. Sets the colour. */
    good: boolean;
  };
  /** The recent values, oldest first, for the sparkline. */
  series?: readonly number[];
}

export interface EntityDetail extends KnowledgeEntity {
  version?: string;
  environment?: string;
  metrics?: readonly EntityMetric[];
  dependencies?: readonly Dependency[];
  changes?: readonly TimelineEvent[];
  incidents?: readonly TimelineEvent[];
  /** Anything else, as label and value pairs: infrastructure, data, docs. */
  sections?: readonly MetadataSection[];
}

export interface EntityDetailPanelProps {
  entity: EntityDetail;
  onAskLeka?: (id: string) => void;
  onClose?: () => void;
  /** Opens another entity — a dependency, from this panel. */
  onSelectEntity?: (id: string) => void;
  /** "sidebar": one column beside a graph or a list. "full": the entity's page. */
  mode?: "sidebar" | "full";
  className?: string;
}

/**
 * A small line of recent values, drawn here rather than by a chart library
 * (LEKA-340). Decoration: the metric's value and its change carry the
 * meaning, in text.
 */
export function Sparkline({
  values,
  tone,
  className,
}: {
  values: readonly number[];
  tone: keyof typeof TONES;
  className?: string;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = 100 / (values.length - 1);
  const points = values.map((value, index) => [index * step, 28 - ((value - min) / span) * 26 + 1]);
  const line = points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");

  return (
    <svg
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      aria-hidden="true"
      data-points={values.length}
      className={cn("h-8 w-full", className)}
    >
      <polygon points={`0,30 ${line} 100,30`} fill={TONES[tone].stroke} fillOpacity={0.12} />
      <polyline
        points={line}
        fill="none"
        stroke={TONES[tone].stroke}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const DELTA_TEXT = {
  success: "text-state-success",
  danger: "text-state-danger",
  accent: "text-shell-nav-active",
} as const;

function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className={cn("rounded-xl border border-shell-line bg-white p-4", className)}
    >
      <h3 id={id} className="mb-3 text-sm font-semibold text-brand-navy">
        {title}
      </h3>
      {children}
    </section>
  );
}

/**
 * Everything known about one entity (LEKA-340) — the "Payment API" screen
 * of mockup 11, as a component. Every section is optional and shows only
 * when it has something to show: a panel built from the backend's bare
 * EntityRead is a header, and that is a correct panel.
 */
export function EntityDetailPanel({
  entity,
  onAskLeka,
  onClose,
  onSelectEntity,
  mode = "sidebar",
  className,
}: EntityDetailPanelProps) {
  const t = useDictionary();
  const titleId = useId();
  const full = mode === "full";
  const typeLabel = t.knowledge.entityTypes[entity.type];
  const Frame = full ? "article" : "aside";

  const metrics = entity.metrics ?? [];
  const changes = entity.changes ?? [];
  const incidents = entity.incidents ?? [];
  const dependencies = entity.dependencies ?? [];
  const sections = (entity.sections ?? []).filter((section) => section.items.length > 0);
  const trust =
    entity.lastUpdated !== undefined ||
    entity.source !== undefined ||
    entity.confidence !== undefined;

  const history = (
    <>
      {changes.length > 0 ? (
        <Section title={t.knowledge.detail.changes}>
          <EventTimeline events={changes} maxVisible={5} />
        </Section>
      ) : null}
      {incidents.length > 0 ? (
        <Section title={t.knowledge.detail.incidents}>
          <EventTimeline events={incidents} maxVisible={5} />
        </Section>
      ) : null}
    </>
  );
  const context = (
    <>
      {dependencies.length > 0 ? (
        <Section title={`${t.knowledge.detail.dependencies} (${dependencies.length})`}>
          <DependencyList items={dependencies} onSelect={onSelectEntity} />
        </Section>
      ) : null}
      {sections.map((section, index) => (
        <Section key={section.title ?? index} title={section.title ?? t.knowledge.detail.general}>
          <MetadataPanel sections={[{ items: section.items }]} />
        </Section>
      ))}
    </>
  );

  return (
    <Frame
      aria-labelledby={titleId}
      data-slot="entity-detail-panel"
      data-mode={mode}
      className={cn("flex min-w-0 flex-col gap-4", className)}
    >
      <header className="flex flex-wrap items-start gap-4">
        <EntityIcon type={entity.type} className={full ? "size-14 [&>svg]:size-7" : undefined} />
        <div className="min-w-0 flex-1">
          <h2
            id={titleId}
            className={cn(
              "font-bold tracking-[-0.02em] break-words text-brand-navy",
              full ? "text-3xl" : "text-lg",
            )}
          >
            {entity.name}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.8125rem] text-shell-accent-muted">
            <span>
              {typeLabel}
              {entity.environment ? ` · ${entity.environment}` : null}
            </span>
            {entity.status ? <StatusBadge variant={`entity.${entity.status}`} /> : null}
            {entity.version ? (
              <span className="rounded-md border border-shell-line px-1.5 py-0.5 text-xs text-shell-nav">
                <span className="sr-only">
                  {fill(t.knowledge.detail.version, { version: entity.version })}
                </span>
                <span aria-hidden="true">{entity.version}</span>
              </span>
            ) : null}
          </div>
          {entity.owner ? (
            <p className="mt-2 text-[0.8125rem] text-shell-muted">
              {t.knowledge.detail.owner} :{" "}
              <span className="font-medium text-brand-navy">{entity.owner.name}</span>
              {entity.owner.role ? ` · ${entity.owner.role}` : null}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {onAskLeka ? (
            <Button onClick={() => onAskLeka(entity.id)} className="gap-2">
              <Sparkles aria-hidden="true" className="size-4" />
              {t.knowledge.detail.askLeka}
            </Button>
          ) : null}
          {onClose ? (
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              aria-label={t.knowledge.detail.close}
            >
              <X aria-hidden="true" className="size-4" />
            </Button>
          ) : null}
        </div>
      </header>

      {trust ? (
        <div
          role="group"
          className="flex flex-wrap items-center gap-2"
          aria-label={t.knowledge.detail.provenance}
        >
          {entity.lastUpdated !== undefined ? (
            <FreshnessIndicator lastUpdated={entity.lastUpdated} />
          ) : null}
          {entity.source ? (
            <ProvenanceBadge
              source={entity.source}
              quality={
                entity.confidence !== undefined ? confidenceToScore(entity.confidence) : undefined
              }
            />
          ) : null}
          {entity.confidence !== undefined ? (
            <QualityIndicator score={confidenceToScore(entity.confidence)} />
          ) : null}
        </div>
      ) : null}

      {entity.description || (entity.tags && entity.tags.length > 0) ? (
        <div className="flex flex-col gap-2">
          {entity.description ? (
            <p className="text-[0.9375rem] text-shell-accent-muted">{entity.description}</p>
          ) : null}
          {entity.tags && entity.tags.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label={t.knowledge.detail.tags}>
              {entity.tags.map((tag) => (
                <li
                  key={tag}
                  className="rounded-md bg-shell-canvas px-1.5 py-0.5 text-xs text-shell-nav"
                >
                  {tag}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {metrics.length > 0 ? (
        <section aria-label={t.knowledge.detail.metrics}>
          <ul className={cn("grid gap-3", full ? "grid-cols-2 lg:grid-cols-4" : "grid-cols-2")}>
            {metrics.map((metric) => {
              const tone: keyof typeof DELTA_TEXT = metric.delta
                ? metric.delta.good
                  ? "success"
                  : "danger"
                : "accent";
              const Arrow = metric.delta?.direction === "up" ? ArrowUp : ArrowDown;
              return (
                <li key={metric.id} className="rounded-xl border border-shell-line bg-white p-3">
                  <p className="text-xs text-shell-muted">{metric.label}</p>
                  <p className="text-xl font-bold text-brand-navy tabular-nums">{metric.value}</p>
                  {metric.delta ? (
                    <p
                      className={cn(
                        "flex items-center gap-1 text-xs font-medium",
                        DELTA_TEXT[tone],
                      )}
                    >
                      <Arrow aria-hidden="true" className="size-3" />
                      <span aria-hidden="true">{metric.delta.value}</span>
                      <span className="sr-only">
                        {fill(
                          metric.delta.direction === "up"
                            ? t.knowledge.detail.rising
                            : t.knowledge.detail.falling,
                          { value: metric.delta.value },
                        )}
                      </span>
                    </p>
                  ) : null}
                  {metric.series ? (
                    <Sparkline values={metric.series} tone={tone} className="mt-1" />
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {full ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-4">{history}</div>
          <div className="flex min-w-0 flex-col gap-4">{context}</div>
        </div>
      ) : (
        <>
          {history}
          {context}
        </>
      )}
    </Frame>
  );
}
