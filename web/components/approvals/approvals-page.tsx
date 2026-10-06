"use client";

import {
  CircleCheck,
  CircleSlash,
  CircleX,
  Clock,
  type LucideIcon,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";
import { CandidatePanel } from "@/components/approvals/candidate-panel";
import { CandidateBadge, FAMILY_ICON } from "@/components/approvals/parts";
import { wordCandidate } from "@/components/approvals/words";
import { SearchInput } from "@/components/forms/search-input";
import { type KnowledgeColumn, KnowledgeTable } from "@/components/knowledge/knowledge-table";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { StatePanel } from "@/components/states/state-panel";
import {
  type Candidate,
  type CandidateStatus,
  type EnrichmentSummary,
  FAMILIES,
  type Family,
  STATUSES,
} from "@/lib/enrichment";
import { useCandidates, useEnrichmentSummary } from "@/lib/enrichment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";

/**
 * À valider, laid out as docs/product/mockups/09-a-valider.jpeg (LEKA-380):
 * what waits on someone. Today that is what LEKA proposes to add to the
 * company model — a relationship, an owner, a criticality — each with how
 * sure it is and what shows it; the decisions on intentions (LEKA-390)
 * join the same queue.
 *
 * Every figure is the workspace's own. The mockup's "Échéance < 24h" and
 * "Équipes concernées" wait for what would compute them: a proposal has no
 * deadline, and is about a thing, not a team.
 */
export function ApprovalsPage({ initialId = null }: { initialId?: string | null }) {
  const t = useDictionary();
  const a = t.approvals;
  const pathname = usePathname() ?? "/approvals";
  const [status, setStatus] = useState<CandidateStatus>("proposed");
  const [family, setFamily] = useState<Family | "all">("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const summary = useEnrichmentSummary();
  const list = useCandidates(status);

  const all = list.data?.data ?? [];
  const shown = all.filter(
    (candidate) =>
      (family === "all" || candidate.family === family) && matches(t, candidate, search),
  );
  const total = summary.data
    ? summary.data.proposed + summary.data.accepted + summary.data.rejected + summary.data.withdrawn
    : 0;

  return (
    <PageContainer>
      <PageHeader
        title={t.nav.approvals}
        subtitle={a.subtitle}
        breadcrumb={buildBreadcrumb(pathname, t)}
      />
      {summary.isPending ? (
        <LoadingState size="page" />
      ) : summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} size="page" />
      ) : total === 0 && selectedId === null ? (
        <StatePanel icon={ShieldCheck} title={a.empty.title} description={a.empty.body} size="page" />
      ) : (
        <div className="flex flex-col gap-5">
          {summary.data ? <Stats summary={summary.data} /> : null}
          <Filters
            status={status}
            onStatus={(next) => {
              setStatus(next);
              setFamily("all");
            }}
            candidates={all}
            family={family}
            onFamily={setFamily}
            search={search}
            onSearch={setSearch}
          />
          <div className={cn("grid gap-4", selectedId && "xl:grid-cols-[minmax(0,1fr)_22rem]")}>
            {list.isPending ? (
              <LoadingState />
            ) : list.isError ? (
              <ErrorState error={list.error} onRetry={() => void list.refetch()} />
            ) : (
              <CandidatesTable
                candidates={shown}
                selectedId={selectedId}
                compact={selectedId !== null}
                empty={all.length === 0 ? a.none : a.noMatch}
                onSelect={(candidate) =>
                  setSelectedId(candidate.id === selectedId ? null : candidate.id)
                }
              />
            )}
            {selectedId ? (
              <CandidatePanel id={selectedId} onClose={() => setSelectedId(null)} />
            ) : null}
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function matches(t: ReturnType<typeof useDictionary>, candidate: Candidate, search: string) {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  const { title } = wordCandidate(t, candidate);
  return [title, candidate.subject.name, candidate.start?.name ?? "", candidate.end?.name ?? ""]
    .some((said) => said.toLowerCase().includes(needle));
}

// ── The figures ─────────────────────────────────────────────────────────────

const TONES = {
  warning: "bg-state-warning-soft text-state-warning",
  success: "bg-state-success-soft text-state-success",
  danger: "bg-state-danger-soft text-state-danger",
  muted: "bg-shell-canvas text-shell-muted",
} as const;

function Stats({ summary }: { summary: EnrichmentSummary }) {
  const t = useDictionary();
  const s = t.approvals.stats;
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="approvals-stats">
      <Stat icon={Clock} tone="warning" value={summary.proposed} label={s.proposed} />
      <Stat
        icon={CircleCheck}
        tone="success"
        value={summary.accepted}
        label={s.accepted}
        note={summary.by_policy ? fill(s.byPolicy, { count: summary.by_policy }) : undefined}
      />
      <Stat icon={CircleX} tone="danger" value={summary.rejected} label={s.rejected} />
      <Stat
        icon={CircleSlash}
        tone="muted"
        value={summary.withdrawn}
        label={s.withdrawn}
        note={summary.withdrawn ? s.withdrawnNote : undefined}
      />
    </ul>
  );
}

function Stat({
  icon: Icon,
  tone,
  value,
  label,
  note,
}: {
  icon: LucideIcon;
  tone: keyof typeof TONES;
  value: number;
  label: string;
  note?: string;
}) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-shell-line bg-white p-4">
      <span
        className={cn("flex size-11 shrink-0 items-center justify-center rounded-lg", TONES[tone])}
      >
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-xl font-semibold text-brand-navy">{value}</p>
        <p className="text-sm text-shell-muted">{label}</p>
        {note ? <p className="text-xs text-shell-muted">{note}</p> : null}
      </div>
    </li>
  );
}

// ── Filters ─────────────────────────────────────────────────────────────────

function Filters({
  status,
  onStatus,
  candidates,
  family,
  onFamily,
  search,
  onSearch,
}: {
  status: CandidateStatus;
  onStatus: (next: CandidateStatus) => void;
  candidates: Candidate[];
  family: Family | "all";
  onFamily: (next: Family | "all") => void;
  search: string;
  onSearch: (next: string) => void;
}) {
  const t = useDictionary();
  const a = t.approvals;
  const counts = new Map<string, number>();
  for (const candidate of candidates) {
    counts.set(candidate.family, (counts.get(candidate.family) ?? 0) + 1);
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
            active={family === "all"}
            onClick={() => onFamily("all")}
            label={a.families.all}
            count={candidates.length}
          />
          {FAMILIES.filter((key) => counts.has(key)).map((key) => (
            <Chip
              key={key}
              active={family === key}
              onClick={() => onFamily(key)}
              label={a.families[key]}
              count={counts.get(key) ?? 0}
            />
          ))}
        </div>
        <SearchInput
          value={search}
          onChange={onSearch}
          placeholder={a.search}
          className="ml-auto w-full sm:w-64"
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

/** The proposals. Beside an opened one, what fits a 13-inch screen: the
 * proposal, how sure, where it stands — its type and date are in the
 * panel. Who proposed is always LEKA: the panel says which analysis. */
function CandidatesTable({
  candidates,
  selectedId,
  compact,
  empty,
  onSelect,
}: {
  candidates: Candidate[];
  selectedId: string | null;
  compact: boolean;
  empty: string;
  onSelect: (candidate: Candidate) => void;
}) {
  const t = useDictionary();
  const a = t.approvals;
  const c = a.columns;
  const columns: KnowledgeColumn<Candidate>[] = [
    {
      id: "element",
      header: c.element,
      sortValue: (candidate) => wordCandidate(t, candidate).title.toLowerCase(),
      cell: (candidate) => {
        const { title, why } = wordCandidate(t, candidate);
        const Icon = FAMILY_ICON[candidate.family] ?? Sparkles;
        return (
          <div
            className={cn(
              "flex items-center gap-3",
              candidate.id === selectedId && "font-semibold",
            )}
          >
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
      sortValue: (candidate) => candidate.family,
      cell: (candidate) => (
        <span className="rounded-md bg-state-info-soft px-2 py-0.5 text-xs text-state-info">
          {(a.family as Record<string, string>)[candidate.family] ?? candidate.family}
        </span>
      ),
    },
    {
      id: "confidence",
      header: c.confidence,
      align: "end",
      sortValue: (candidate) => candidate.confidence,
      cell: (candidate) => `${Math.round(candidate.confidence * 100)} %`,
    },
    {
      id: "date",
      header: c.date,
      sortValue: (candidate) => candidate.decided_at ?? candidate.last_seen_at,
      cell: (candidate) => timeAgo(t, candidate.decided_at ?? candidate.last_seen_at),
    },
    {
      id: "status",
      header: c.status,
      cell: (candidate) => <CandidateBadge candidate={candidate} />,
    },
  ];

  const shownColumns = compact
    ? columns.filter((column) => column.id !== "type" && column.id !== "date")
    : columns;

  return (
    <KnowledgeTable
      caption={c.caption}
      columns={shownColumns}
      rows={candidates}
      rowKey={(candidate) => candidate.id}
      onRowClick={onSelect}
      initialSort={{ id: "confidence", direction: "desc" }}
      empty={{ title: empty }}
    />
  );
}
