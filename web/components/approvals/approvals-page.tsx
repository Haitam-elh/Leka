"use client";

import { CircleCheck, CircleSlash, CircleX, Clock, ShieldCheck, Sparkles } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";
import { CandidatePanel } from "@/components/approvals/candidate-panel";
import { ConflictPanel } from "@/components/approvals/conflict-panel";
import { DecisionPanel } from "@/components/approvals/decision-panel";
import {
  CONFLICT_STATUS,
  DECISION_STATUS,
  dateOf,
  type Item,
  items as itemsOf,
  wordItem,
} from "@/components/approvals/items";
import { FAMILY_ICON, ItemBadge } from "@/components/approvals/parts";
import { Pill } from "@/components/intelligence/pill";
import { SearchInput } from "@/components/forms/search-input";
import { type KnowledgeColumn, KnowledgeTable } from "@/components/knowledge/knowledge-table";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { StatePanel } from "@/components/states/state-panel";
import { routes } from "@/config/routes";
import { useConflicts, useConflictSummary } from "@/lib/conflicts-queries";
import type { DecisionSummary } from "@/lib/decisions";
import { useDecisionQueue, useDecisionSummary } from "@/lib/decisions-queries";
import { type CandidateStatus, FAMILIES, STATUSES } from "@/lib/enrichment";
import { useCandidates, useEnrichmentSummary } from "@/lib/enrichment-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";

type Kind = Item["kind"];
const RISK_RANK = { low: 1, medium: 2, high: 3, critical: 4 } as const;
const RISK_TONE = { low: "success", medium: "warning", high: "danger", critical: "danger" } as const;
type Selected = { kind: Kind; id: string } | null;
/** The type chips: the actions to decide, a proposal's families, then the
 * conflicts. */
const TYPES = ["action", ...FAMILIES, "conflict"] as const;
type Type = (typeof TYPES)[number];

/**
 * À valider, laid out as docs/product/mockups/09-a-valider.jpeg: what waits
 * on someone. What LEKA proposes to add to the company model — a
 * relationship, an owner, a criticality (LEKA-380) — and what its sources
 * disagree on, to settle (LEKA-382): each worded, with why and how sure; the
 * decisions on intentions (LEKA-390) join the same queue.
 *
 * Every figure is the workspace's own. The mockup's "Échéance < 24h" and
 * "Équipes concernées" wait for what would compute them: nothing here has
 * a deadline, and each is about a thing, not a team.
 */
export function ApprovalsPage({
  initialId = null,
  initialKind = "candidate",
}: {
  initialId?: string | null;
  initialKind?: Kind;
}) {
  const t = useDictionary();
  const a = t.approvals;
  const pathname = usePathname() ?? "/approvals";
  const [status, setStatus] = useState<CandidateStatus>("proposed");
  const [type, setType] = useState<Type | "all">("all");
  const [search, setSearch] = useState("");
  const [selected, setOpened] = useState<Selected>(
    initialId ? { kind: initialKind, id: initialId } : null,
  );
  // What is open is in the address — /approvals/<id>?kind=… — so it can be
  // shared, reloaded, gone back to; without a navigation, the page stays.
  const setSelected = (next: Selected) => {
    setOpened(next);
    const url = next
      ? `${routes.approval(next.id)}${next.kind === "candidate" ? "" : `?kind=${next.kind}`}`
      : routes.approvals();
    window.history.replaceState(null, "", url);
  };
  const proposals = useEnrichmentSummary();
  const disputes = useConflictSummary();
  const choices = useDecisionSummary();
  const candidates = useCandidates(status);
  const conflicts = useConflicts(CONFLICT_STATUS[status]);
  const decisions = useDecisionQueue(DECISION_STATUS[status]);

  const all = itemsOf(
    candidates.data?.data ?? [],
    conflicts.data?.data ?? [],
    decisions.data?.data ?? [],
  );
  const shown = all.filter(
    (item) => (type === "all" || item.family === type) && matches(t, item, search),
  );
  const figures = figuresOf(proposals.data, disputes.data, choices.data);
  const pending = proposals.isPending || disputes.isPending || choices.isPending;
  const failed = proposals.isError
    ? proposals
    : disputes.isError
      ? disputes
      : choices.isError
        ? choices
        : null;
  const opened =
    selected?.kind === "decision"
      ? (decisions.data?.data ?? []).find((item) => item.decision.id === selected.id)
      : undefined;

  return (
    <PageContainer>
      <PageHeader
        title={t.nav.approvals}
        subtitle={a.subtitle}
        breadcrumb={buildBreadcrumb(pathname, t)}
      />
      {pending ? (
        <LoadingState size="page" />
      ) : failed ? (
        <ErrorState error={failed.error} onRetry={() => void failed.refetch()} size="page" />
      ) : figures.total === 0 && selected === null ? (
        <StatePanel icon={ShieldCheck} title={a.empty.title} description={a.empty.body} size="page" />
      ) : (
        <div className="flex flex-col gap-5">
          <Stats figures={figures} />
          <Filters
            status={status}
            onStatus={(next) => {
              setStatus(next);
              setType("all");
            }}
            items={all}
            type={type}
            onType={setType}
            search={search}
            onSearch={setSearch}
          />
          <div className={cn("grid gap-4", selected && "xl:grid-cols-[minmax(0,1fr)_22rem]")}>
            {candidates.isPending || conflicts.isPending || decisions.isPending ? (
              <LoadingState />
            ) : candidates.isError ? (
              <ErrorState error={candidates.error} onRetry={() => void candidates.refetch()} />
            ) : conflicts.isError ? (
              <ErrorState error={conflicts.error} onRetry={() => void conflicts.refetch()} />
            ) : decisions.isError ? (
              <ErrorState error={decisions.error} onRetry={() => void decisions.refetch()} />
            ) : (
              <ItemsTable
                items={shown}
                selected={selected}
                compact={selected !== null}
                empty={all.length === 0 ? a.none : a.noMatch}
                onSelect={(item) =>
                  setSelected(
                    selected?.id === item.id ? null : { kind: item.kind, id: item.id },
                  )
                }
              />
            )}
            {selected?.kind === "candidate" ? (
              <CandidatePanel id={selected.id} onClose={() => setSelected(null)} />
            ) : selected?.kind === "conflict" ? (
              <ConflictPanel id={selected.id} onClose={() => setSelected(null)} />
            ) : opened ? (
              <DecisionPanel item={opened} onClose={() => setSelected(null)} />
            ) : null}
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function matches(t: Dictionary, item: Item, search: string) {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  const { title } = wordItem(t, item);
  const names =
    item.kind === "candidate"
      ? [item.data.subject.name, item.data.start?.name ?? "", item.data.end?.name ?? ""]
      : item.kind === "decision"
        ? [item.data.intention.title]
        : [item.data.subject.name, item.data.about];
  return [title, ...names].some((said) => said.toLowerCase().includes(needle));
}

// ── The figures ─────────────────────────────────────────────────────────────

interface Figures {
  waiting: number;
  decided: number;
  refused: number;
  withdrawn: number;
  byPolicy: number;
  total: number;
}

function figuresOf(
  proposals: { proposed: number; accepted: number; rejected: number; withdrawn: number; by_policy: number } | undefined,
  conflicts: { open: number; resolved: number; dismissed: number; gone: number } | undefined,
  decisions?: DecisionSummary,
): Figures {
  const waiting = (proposals?.proposed ?? 0) + (conflicts?.open ?? 0) + (decisions?.proposed ?? 0);
  const decided = (proposals?.accepted ?? 0) + (conflicts?.resolved ?? 0) + (decisions?.approved ?? 0);
  const refused = (proposals?.rejected ?? 0) + (conflicts?.dismissed ?? 0) + (decisions?.rejected ?? 0);
  const withdrawn =
    (proposals?.withdrawn ?? 0) +
    (conflicts?.gone ?? 0) +
    (decisions?.changes_requested ?? 0) +
    (decisions?.superseded ?? 0);
  return {
    waiting,
    decided,
    refused,
    withdrawn,
    byPolicy: proposals?.by_policy ?? 0,
    total: waiting + decided + refused + withdrawn,
  };
}


function Stats({ figures }: { figures: Figures }) {
  const t = useDictionary();
  const s = t.approvals.stats;
  return (
    <StatGrid count={4} testId="approvals-stats">
      <StatCard icon={Clock} tone="warning" value={figures.waiting} label={s.proposed} />
      <StatCard
        icon={CircleCheck}
        tone="success"
        value={figures.decided}
        label={s.accepted}
        foot={figures.byPolicy ? fill(s.byPolicy, { count: figures.byPolicy }) : undefined}
      />
      <StatCard icon={CircleX} tone="danger" value={figures.refused} label={s.rejected} />
      <StatCard
        icon={CircleSlash}
        tone="neutral"
        value={figures.withdrawn}
        label={s.withdrawn}
        foot={figures.withdrawn ? s.withdrawnNote : undefined}
      />
    </StatGrid>
  );
}


// ── Filters ─────────────────────────────────────────────────────────────────

function Filters({
  status,
  onStatus,
  items,
  type,
  onType,
  search,
  onSearch,
}: {
  status: CandidateStatus;
  onStatus: (next: CandidateStatus) => void;
  items: Item[];
  type: Type | "all";
  onType: (next: Type | "all") => void;
  search: string;
  onSearch: (next: string) => void;
}) {
  const t = useDictionary();
  const a = t.approvals;
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.family, (counts.get(item.family) ?? 0) + 1);
  }
  return (
    <div className="flex flex-col gap-3">
      <div role="group" aria-label={a.statusLabel} className="flex flex-wrap gap-2">
        {STATUSES.map((key) => (
          <Chip
            key={key}
            active={status === key}
            onClick={() => onStatus(key)}
            label={a.status[key]}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label={a.familiesLabel} className="flex flex-wrap gap-2">
          <Chip
            active={type === "all"}
            onClick={() => onType("all")}
            label={a.families.all}
            count={items.length}
          />
          {TYPES.filter((key) => counts.has(key)).map((key) => (
            <Chip
              key={key}
              active={type === key}
              onClick={() => onType(key)}
              label={a.families[key]}
              count={counts.get(key) ?? 0}
            />
          ))}
        </div>
        <SearchInput
          value={search}
          onChange={onSearch}
          placeholder={a.search}
          className="ms-auto w-full sm:w-64"
        />
      </div>
    </div>
  );
}

function Chip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40",
        active
          ? "border-brand-violet bg-brand-violet-soft text-shell-nav-active"
          : "border-shell-line bg-white text-brand-navy hover:bg-brand-violet-soft/50",
      )}
    >
      {label}
      {count !== undefined ? <span className="text-xs text-shell-muted">{count}</span> : null}
    </button>
  );
}

// ── The table ───────────────────────────────────────────────────────────────

/** How sure: a proposal's confidence; for a conflict, how clearly LEKA
 * recommends a side — sorted by that side's score, among the proposals. */
function sureness(t: Dictionary, item: Item): { value: number; said: string } {
  if (item.kind === "decision") return { value: 0, said: "—" };
  if (item.kind === "candidate") {
    return { value: item.data.confidence, said: `${Math.round(item.data.confidence * 100)} %` };
  }
  const recommendation = item.data.recommendation;
  const strength = (t.approvals.conflict.strength as Record<string, string>)[recommendation.strength];
  const best = recommendation.side !== null ? item.data.sides[recommendation.side] : undefined;
  return { value: best?.score ?? 0, said: strength || "—" };
}

/** What waits. Beside an opened one, what fits a 13-inch screen: what it
 * is, how sure, where it stands — its type and date are in the panel. */
function ItemsTable({
  items,
  selected,
  compact,
  empty,
  onSelect,
}: {
  items: Item[];
  selected: Selected;
  compact: boolean;
  empty: string;
  onSelect: (item: Item) => void;
}) {
  const t = useDictionary();
  const a = t.approvals;
  const c = a.columns;
  const columns: KnowledgeColumn<Item>[] = [
    {
      id: "element",
      header: c.element,
      sortValue: (item) => wordItem(t, item).title.toLowerCase(),
      cell: (item) => {
        const { title, why } = wordItem(t, item);
        const Icon = FAMILY_ICON[item.family] ?? Sparkles;
        return (
          <div className={cn("flex items-center gap-3", item.id === selected?.id && "font-semibold")}>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-shell-nav-active">
              <Icon className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="text-brand-navy">{title}</p>
              {why ? <p className="text-xs text-shell-muted">{why}</p> : null}
            </div>
          </div>
        );
      },
    },
    {
      id: "type",
      header: c.type,
      sortValue: (item) => item.family,
      cell: (item) => (
        <span className="rounded-md bg-state-info-soft px-2 py-0.5 text-xs text-state-info">
          {(a.family as Record<string, string>)[item.family] ?? item.family}
        </span>
      ),
    },
    {
      id: "impact",
      header: c.impact,
      sortValue: (item) => (item.kind === "decision" ? RISK_RANK[item.data.decision.risk] : 0),
      cell: (item) =>
        item.kind === "decision" ? (
          <Pill tone={RISK_TONE[item.data.decision.risk]}>
            {t.decisions.impact[item.data.decision.risk]}
          </Pill>
        ) : (
          "—"
        ),
    },
    {
      id: "confidence",
      header: c.confidence,
      align: "end",
      sortValue: (item) => sureness(t, item).value,
      cell: (item) => sureness(t, item).said,
    },
    {
      id: "date",
      header: c.date,
      sortValue: (item) => dateOf(item),
      cell: (item) => timeAgo(t, dateOf(item)),
    },
    {
      id: "status",
      header: c.status,
      cell: (item) => <ItemBadge item={item} />,
    },
  ];
  // Impact is a decision's risk (mockup 09): shown when one is listed.
  const deciding = items.some((item) => item.kind === "decision");
  const shownColumns = columns.filter(
    (column) =>
      (deciding || column.id !== "impact") &&
      !(compact && (column.id === "type" || column.id === "date")),
  );

  return (
    <KnowledgeTable
      caption={c.caption}
      columns={shownColumns}
      rows={items}
      rowKey={(item) => `${item.kind}:${item.id}`}
      onRowClick={onSelect}
      initialSort={{ id: "confidence", direction: "desc" }}
      empty={{ title: empty }}
    />
  );
}
