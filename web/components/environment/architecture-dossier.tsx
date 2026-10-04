"use client";

import { Maximize2, Minus, Plus } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { cn } from "cn";

import {
  type Arrow,
  ArrowLayer,
  CardBox,
  cardName,
  DetailPanel,
  kindIcon,
  kindLabel,
  Legend,
  Nothing,
  ownArrows,
  roleWords,
  ruleWords,
  Sentences,
  StatusDot,
  useArrows,
  type Words,
} from "@/components/environment/architecture";
import { IconTile, Logo } from "@/components/environment/parts";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { hasSourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type {
  Architecture,
  ArchitectureCard,
  ArchitectureLink,
} from "@/lib/knowledge-graph";
import { KIND_CATEGORY, type SourceKind } from "@/lib/sources";

/**
 * La cartographie détaillée (LEKA-369): the architecture as a dossier, after
 * the DSI's architecture prompt — every brick and every link, then what
 * follows from them — distinct from the screen's overview at a glance:
 *
 *   1  the architecture in LAYERS — code, applications, data, technology,
 *      outside — every card, every link drawn card to card and named
 *   2  the FLOWS — what a request or a job goes through, step by step, as a
 *      sequence diagram
 *   3  CONTACTS AND RESPONSIBILITIES — each element's team and maintainers;
 *      "À confirmer" where no source names one, never a name invented
 *   4  CONTROL POINTS — what LEKA deduced rather than read, what nobody
 *      owns or watches, what is tied to nothing: in orange
 *   5  SOURCES AND LIMITS — what it was read from, when, and what is not
 *      read at all
 *
 * Every word is the API's (GET /knowledge/architecture?detailed=true):
 * factual, nothing invented; a gap is said in orange, never filled.
 */

const LAYERS = ["code", "services", "data", "cloud", "external"] as const;
type Layer = (typeof LAYERS)[number];

const LAYER_LOOK: Record<Layer, string> = {
  code: "bg-shell-canvas/70",
  services: "bg-state-info-soft/60",
  data: "bg-brand-violet-soft/50",
  cloud: "bg-state-success-soft/50",
  external: "bg-shell-canvas/40",
};

/** The links the layers draw at rest with their names; past this, only the
 * chosen card's are named — the rest are lines. */
const NAMED_AT_REST = 18;

const SECTIONS = ["layers", "flows", "responsibilities", "checks", "sources"] as const;

export function ArchitectureDossier({ data }: { data: Architecture }) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const d = w.dossier;
  const byId = useMemo(() => new Map(data.cards.map((card) => [card.id, card])), [data.cards]);

  if (data.cards.length === 0) return <Nothing />;

  const count = (column: string, type?: string) =>
    data.cards.filter((card) => card.column === column && (!type || card.type === type)).length;
  const scope = fill(d.scope, {
    repositories: data.figures.repositories,
    modules: count("code", "module"),
    services: data.figures.services + data.figures.applications,
    stores: data.figures.databases + data.figures.stores,
    cloud: data.figures.cloud_resources,
    external: count("external"),
  });

  return (
    <div className="flex flex-col gap-6" data-testid="architecture-dossier">
      <header className="rounded-xl border border-shell-line bg-white px-5 py-4">
        <h2 className="text-[1.375rem] font-bold tracking-[-0.01em] text-brand-navy">
          {d.title}
        </h2>
        <p className="mt-0.5 text-[0.9375rem] text-state-warning italic">{scope}</p>
        <p className="mt-1 text-[0.8125rem] text-shell-muted">{d.layersLine}</p>
        <nav aria-label={d.contents} className="mt-3">
          <ol className="flex flex-wrap gap-x-5 gap-y-1 text-[0.8125rem]">
            {SECTIONS.map((section, index) => (
              <li key={section}>
                <a
                  href={`#${section}`}
                  className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  {`${index + 1} · ${d.sections[section].title}`}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </header>

      <Section id="layers" index={1}>
        <Layers data={data} byId={byId} />
      </Section>
      <Section id="flows" index={2}>
        <Flows data={data} byId={byId} />
      </Section>
      <Section id="responsibilities" index={3}>
        <Responsibilities data={data} />
      </Section>
      <Section id="checks" index={4}>
        <Checks data={data} byId={byId} />
      </Section>
      <Section id="sources" index={5}>
        <SourcesAndLimits data={data} />
      </Section>
    </div>
  );
}

function Section({
  id,
  index,
  children,
}: {
  id: (typeof SECTIONS)[number];
  index: number;
  children: React.ReactNode;
}) {
  const t = useDictionary();
  const d = t.environment.architecture.dossier.sections[id];
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="scroll-mt-4 rounded-xl border border-shell-line bg-white p-4"
      data-testid={`dossier-${id}`}
    >
      <h2 id={`${id}-title`} className="text-[1.0625rem] font-bold text-brand-navy">
        {`${index} · ${d.title}`}
      </h2>
      <p className="mb-3 text-[0.8125rem] text-state-warning italic">{d.subtitle}</p>
      {children}
    </section>
  );
}

// ── 1 · the layers ──────────────────────────────────────────────────────────

/** Every link, card to card; the chosen card's over them, its alike ones
 * one each — the dossier names them all. A repository laid out by its
 * modules speaks through them. */
function layerArrows(
  data: Architecture,
  byId: ReadonlyMap<string, ArchitectureCard>,
  selected: string | null,
): Arrow[] {
  const laidOut = new Set(
    data.cards.filter((card) => card.type === "module").map((card) => card.repository_id),
  );
  const shown = data.links.filter((link) => !laidOut.has(link.from_id));
  const arrows: Arrow[] = shown.map((link) => ({
    id: `${link.from_id}:${link.role}:${link.to_id}`,
    from: { card: link.from_id },
    to: { card: link.to_id },
    role: link.role,
    status: link.status,
    inferred: link.origin === "inferred",
    own: false,
  }));
  if (!selected) return arrows;
  const end = (at: Arrow["from"]) => ("card" in at ? at.card : "");
  const own = ownArrows(shown, byId, selected, false).map((arrow) => ({
    ...arrow,
    id: `own:${end(arrow.from)}:${arrow.role}:${end(arrow.to)}`,
  }));
  const mine = new Set(own.map((arrow) => arrow.id.slice(4)));
  return [...arrows.filter((arrow) => !mine.has(arrow.id)), ...own];
}

function Layers({
  data,
  byId,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  // Nothing chosen: the whole width for the layers; a brick chosen, its panel.
  const [selected, setChosen] = useState<string | null>(null);
  const card = selected ? (byId.get(selected) ?? null) : null;
  const arrows = useMemo(() => layerArrows(data, byId, selected), [data, byId, selected]);
  const drawn = useArrows(frame, arrows, selected, scale, {
    around: false,
    labels: arrows.length <= NAMED_AT_REST,
  });

  return (
    <div className={cn("grid gap-3", card ? "xl:grid-cols-[minmax(0,1fr)_18.5rem]" : "")}>
      <div className="min-w-0" data-testid="architecture">
        <div className="overflow-x-auto">
          <div
            ref={frame}
            className="relative flex min-w-[44rem] flex-col gap-2"
            style={
              scale !== 1
                ? { transform: `scale(${scale})`, transformOrigin: "0 0", width: `${100 / scale}%` }
                : undefined
            }
          >
            <ArrowLayer drawn={drawn} id="dossier" />
            {LAYERS.map((layer) => (
              <Band
                key={layer}
                layer={layer}
                cards={data.cards.filter((one) => one.column === layer)}
                selected={selected}
                onSelect={setChosen}
              />
            ))}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-1" role="group" aria-label={w.zoom.label}>
            {(
              [
                [Plus, w.zoom.in, () => setScale((s) => Math.min(1.3, s + 0.1))],
                [Minus, w.zoom.out, () => setScale((s) => Math.max(0.6, s - 0.1))],
                [Maximize2, w.zoom.fit, () => setScale(1)],
              ] as const
            ).map(([Icon, label, act]) => (
              <button
                key={label}
                type="button"
                onClick={act}
                aria-label={label}
                title={label}
                className="flex size-7 items-center justify-center rounded-md border border-shell-line bg-white text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
              >
                <Icon className="size-3.5" aria-hidden="true" />
              </button>
            ))}
          </div>
          <Legend />
        </div>
        <Sentences data={data} byId={byId} />
      </div>
      {card ? (
        <DetailPanel
          key={card.id}
          card={card}
          data={data}
          byId={byId}
          onSelect={setChosen}
          onClose={() => setChosen(null)}
        />
      ) : null}
    </div>
  );
}

/** One layer: its name and how many it holds, then every card of it — a
 * cloud's by provider and region. */
function Band({
  layer,
  cards,
  selected,
  onSelect,
}: {
  layer: Layer;
  cards: readonly ArchitectureCard[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const d = w.dossier;
  const groups = new Map<string, ArchitectureCard[]>();
  for (const card of cards) groups.set(card.group, [...(groups.get(card.group) ?? []), card]);
  return (
    <section
      aria-label={d.layers[layer]}
      data-panel={`layer-${layer}`}
      className={cn(
        "grid grid-cols-[8.5rem_minmax(0,1fr)] items-start gap-3 rounded-lg px-3 py-2.5",
        LAYER_LOOK[layer],
      )}
      data-testid={`dossier-layer-${layer}`}
    >
      <div className="pt-1">
        <p className="text-[0.8125rem] font-semibold text-brand-navy">{d.layers[layer]}</p>
        <p className="text-[0.6875rem] text-shell-muted">
          {fill(d.layerCount, { count: cards.length })}
        </p>
      </div>
      {cards.length === 0 ? (
        <p className="self-center text-xs text-shell-muted">{w.columnEmpty[layer]}</p>
      ) : (
        <div className="flex min-w-0 flex-col gap-2">
          {[...groups].map(([group, members]) => (
            <div key={group} className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2.5">
              {layer === "cloud" ? (
                <span className="flex items-center gap-1.5 text-[0.75rem] font-medium text-brand-navy">
                  {hasSourceLogo(group) ? <Logo kind={group} className="size-4" /> : null}
                  {(w.providers as Record<string, string>)[group] ?? group}
                </span>
              ) : null}
              {members.map((card) => (
                <div key={card.id} className="w-[12rem] min-w-0">
                  <CardBox card={card} selected={card.id === selected} onSelect={onSelect} />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── 2 · the flows ───────────────────────────────────────────────────────────

const COLUMN = 156;
const ROW = 34;

function Flows({
  data,
  byId,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
}) {
  const t = useDictionary();
  const d = t.environment.architecture.dossier;
  if (data.flows.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{d.noFlows}</p>;
  }
  return (
    <div className="flex flex-col gap-5">
      {data.flows.map((flow, index) => (
        <SequenceDiagram
          key={flow.entries.join(",")}
          index={index}
          entries={flow.entries}
          steps={flow.steps}
          byId={byId}
        />
      ))}
    </div>
  );
}

/** What one entry goes through: its participants along the top, a lifeline
 * each, every step an arrow from one to the other, numbered and named. */
function SequenceDiagram({
  index,
  entries,
  steps,
  byId,
}: {
  index: number;
  entries: readonly string[];
  steps: readonly ArchitectureLink[];
  byId: ReadonlyMap<string, ArchitectureCard>;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const d = w.dossier;
  const order: string[] = [];
  for (const id of [...entries.slice(0, 1), ...steps.flatMap((s) => [s.from_id, s.to_id])]) {
    if (!order.includes(id) && byId.has(id)) order.push(id);
  }
  const at = (id: string) => order.indexOf(id) * COLUMN + COLUMN / 2;
  const width = order.length * COLUMN;
  const height = steps.length * ROW + 12;
  const names = entries.map((id) => (byId.get(id) ? cardName(byId.get(id)!) : id));
  return (
    <figure className="min-w-0" data-testid="dossier-flow">
      <figcaption className="mb-2 text-[0.875rem] font-semibold text-brand-navy">
        {fill(entries.length > 1 ? d.flowMany : d.flowOne, {
          index: index + 1,
          names: names.join(", "),
        })}
      </figcaption>
      <div className="overflow-x-auto rounded-lg border border-shell-line bg-shell-canvas/30 p-2">
        <div style={{ width }} className="relative">
          <ol
            className="grid"
            style={{ gridTemplateColumns: `repeat(${order.length}, ${COLUMN}px)` }}
          >
            {order.map((id) => {
              const card = byId.get(id)!;
              return (
                <li key={id} className="px-1.5">
                  <span className="flex min-w-0 items-center gap-1.5 rounded-md border border-shell-line bg-white px-1.5 py-1">
                    <IconTile
                      icon={kindIcon(card.kind)}
                      tone="neutral"
                      className="size-5 rounded [&>svg]:size-3"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[0.6875rem] font-semibold text-brand-navy">
                        {cardName(card)}
                      </span>
                      <span className="block truncate text-[0.625rem] text-shell-muted">
                        {kindLabel(w, card)}
                      </span>
                    </span>
                    <StatusDot card={card} />
                  </span>
                </li>
              );
            })}
          </ol>
          <svg
            width={width}
            height={height}
            className="block"
            role="img"
            aria-label={steps
              .map((step) => {
                const from = cardName(byId.get(step.from_id)!);
                const to = cardName(byId.get(step.to_id)!);
                return `${from} ${roleWords(w, step.role).sentence} ${to}`;
              })
              .join(" ; ")}
          >
            <defs>
              <marker
                id={`flow-${index}-head`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--brand-navy, #0b1437)" />
              </marker>
            </defs>
            {order.map((id) => (
              <line
                key={id}
                x1={at(id)}
                x2={at(id)}
                y1={0}
                y2={height}
                stroke="var(--shell-line, #dfe3ee)"
                strokeDasharray="3 3"
              />
            ))}
            {steps.map((step, k) => {
              const y = k * ROW + ROW / 2 + 6;
              const x1 = at(step.from_id);
              const x2 = at(step.to_id);
              const inward = x2 > x1 ? -6 : 6;
              return (
                <g key={`${step.from_id}:${step.role}:${step.to_id}`}>
                  <line
                    x1={x1}
                    x2={x2 + inward}
                    y1={y}
                    y2={y}
                    stroke="var(--brand-navy, #0b1437)"
                    strokeWidth={1.25}
                    strokeDasharray={step.origin === "inferred" ? "4 3" : undefined}
                    markerEnd={`url(#flow-${index}-head)`}
                  />
                  <text
                    x={(x1 + x2) / 2}
                    y={y - 5}
                    textAnchor="middle"
                    className={cn(
                      "text-[10px]",
                      step.origin === "inferred" ? "fill-state-warning" : "fill-brand-navy",
                    )}
                  >
                    {`${k + 1}. ${roleWords(w, step.role).label}`}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    </figure>
  );
}

// ── 3 · contacts and responsibilities ──────────────────────────────────────

function Responsibilities({ data }: { data: Architecture }) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const d = w.dossier;
  const rows = data.cards.filter((card) => card.type !== "module" && card.type !== "tool");
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] border-collapse text-[0.78125rem]" data-testid="dossier-raci">
        <thead>
          <tr className="bg-brand-navy text-left text-white">
            {d.raci.columns.map((column) => (
              <th key={column} scope="col" className="px-2 py-1.5 font-semibold">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((card, index) => {
            const known = card.team !== null || card.maintainers.length > 0;
            return (
              <tr key={card.id} className={index % 2 ? "bg-shell-canvas/60" : "bg-white"}>
                <th scope="row" className="px-2 py-1 text-left font-medium text-brand-navy">
                  {cardName(card)}
                </th>
                <td className="px-2 py-1 text-brand-navy">{kindLabel(w, card)}</td>
                <td className="px-2 py-1">
                  {card.team ? (
                    card.team.name
                  ) : (
                    <span className="text-state-warning">{d.raci.toConfirm}</span>
                  )}
                </td>
                <td className="px-2 py-1">
                  {card.maintainers.length ? (
                    card.maintainers.map((person) => person.name).join(", ")
                  ) : (
                    <span className="text-state-warning">{d.raci.toConfirm}</span>
                  )}
                </td>
                <td className="px-2 py-1">
                  <span className="flex items-center gap-1">
                    {card.sources.map((kind) =>
                      hasSourceLogo(kind) ? (
                        <Logo key={kind} kind={kind} className="size-3.5" />
                      ) : null,
                    )}
                    <span className="text-shell-muted">
                      {card.sources.map(kindName).join(", ")}
                    </span>
                  </span>
                </td>
                <td className="px-2 py-1">
                  <span
                    className={cn(
                      "rounded px-1.5 py-px text-[0.6875rem] font-medium",
                      known
                        ? "bg-state-success-soft text-state-success"
                        : "bg-state-warning-soft text-state-warning",
                    )}
                  >
                    {known ? d.raci.documented : d.raci.toConfirm}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── 4 · control points ─────────────────────────────────────────────────────

const CHECK_KINDS = [
  "incident",
  "attention",
  "deduced",
  "inferred",
  "unmonitored",
  "no_team",
  "unlinked",
] as const;

function checkSentence(
  w: Words,
  check: Architecture["checks"][number],
  byId: ReadonlyMap<string, ArchitectureCard>,
): string {
  const d = w.dossier.checks;
  const name = byId.get(check.card_id) ? cardName(byId.get(check.card_id)!) : check.card_id;
  const other = check.other_id && byId.get(check.other_id) ? byId.get(check.other_id)! : null;
  switch (check.kind) {
    case "deduced":
      return other
        ? fill(d.deducedFrom, { name, other: cardName(other), kind: kindLabel(w, other) })
        : fill(d.deduced, { name });
    case "inferred":
      return fill(d.inferred, {
        name,
        role: roleWords(w, check.role ?? "depends").sentence,
        other: other ? cardName(other) : "",
        rule: ruleWords(w, check.rule ?? "other"),
        confidence: Math.round((check.confidence ?? 0) * 100),
      });
    default:
      return fill((d as Record<string, string>)[check.kind] ?? check.kind, { name });
  }
}

function Checks({
  data,
  byId,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const d = w.dossier;
  if (data.checks.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{d.noChecks}</p>;
  }
  return (
    <div className="grid items-start gap-3 lg:grid-cols-2" data-testid="dossier-check-list">
      {CHECK_KINDS.map((kind) => {
        const found = data.checks.filter((check) => check.kind === kind);
        if (found.length === 0) return null;
        const grouped = kind === "no_team" || kind === "unlinked";
        return (
          <div
            key={kind}
            className={cn(
              "rounded-lg border-l-4 px-3 py-2",
              kind === "incident"
                ? "border-state-danger bg-state-danger-soft/50"
                : "border-state-warning bg-state-warning-soft/40",
            )}
            data-testid={`dossier-check-${kind}`}
          >
            <p className="text-[0.8125rem] font-semibold text-brand-navy">
              {fill(d.checkTitles[kind], { count: found.length })}
            </p>
            {grouped ? (
              <p className="mt-1 text-[0.78125rem] text-brand-navy">
                {found
                  .map((check) =>
                    byId.get(check.card_id) ? cardName(byId.get(check.card_id)!) : check.card_id,
                  )
                  .join(", ")}
              </p>
            ) : (
              <ul className="mt-1 flex flex-col gap-0.5 text-[0.78125rem] text-brand-navy">
                {found.map((check) => (
                  <li key={`${check.kind}:${check.card_id}:${check.other_id}:${check.role}`}>
                    {checkSentence(w, check, byId)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── 5 · sources and limits ─────────────────────────────────────────────────

/** A source's kind by its vendor's name: GitHub, Amazon Web Services. */
function kindName(kind: string): string {
  return hasSourceLogo(kind) ? sourceTitle(kind as SourceKind) : kind;
}

function tone(status: string): "synced" | "attention" | "error" | "setup" | "off" {
  if (status === "disabled") return "off";
  if (status === "draft" || status === "tested") return "setup";
  if (status === "error") return "error";
  if (status === "degraded") return "attention";
  return "synced";
}

function SourcesAndLimits({ data }: { data: Architecture }) {
  const t = useDictionary();
  const d = t.environment.architecture.dossier;
  const watched = data.sources.some(
    (source) => KIND_CATEGORY[source.kind as SourceKind] === "observability",
  );
  const limits = [d.limits.code, d.limits.buckets, d.limits.databases, d.limits.teams];
  if (!watched) limits.unshift(d.limits.monitoring);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] border-collapse text-[0.78125rem]" data-testid="dossier-sources-table">
          <thead>
            <tr className="bg-brand-navy text-left text-white">
              {d.sourceColumns.map((column) => (
                <th key={column} scope="col" className="px-2 py-1.5 font-semibold">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.sources.map((source, index) => (
              <tr key={source.source_id} className={index % 2 ? "bg-shell-canvas/60" : "bg-white"}>
                <th scope="row" className="px-2 py-1 text-left font-medium text-brand-navy">
                  <span className="flex items-center gap-1.5">
                    {hasSourceLogo(source.kind) ? (
                      <Logo kind={source.kind} className="size-4" />
                    ) : null}
                    {source.name}
                  </span>
                </th>
                <td className="px-2 py-1 text-brand-navy">
                  {kindName(source.kind)}
                </td>
                <td className="px-2 py-1">
                  <StatusBadge variant={`source.${tone(source.status)}`} size="sm" />
                </td>
                <td className="px-2 py-1 text-shell-muted">
                  {source.last_synced_at ? timeAgo(t, source.last_synced_at) : d.never}
                </td>
                <td className="px-2 py-1 text-right text-brand-navy tabular-nums">
                  {source.entities}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <p className="text-[0.8125rem] font-semibold text-brand-navy">{d.limitsTitle}</p>
        <ul className="mt-1 flex list-disc flex-col gap-1 pl-4 text-[0.78125rem] text-brand-navy" data-testid="dossier-limits">
          {limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
