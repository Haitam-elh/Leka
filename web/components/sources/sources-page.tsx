"use client";

import { CircleAlert, Clock, FileText, type LucideIcon, Plug, RefreshCw } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";
import { SearchInput } from "@/components/forms/search-input";
import { type KnowledgeColumn, KnowledgeTable } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { capabilityWord, SourcePanel } from "@/components/sources/source-panel";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { StatePanel } from "@/components/states/state-panel";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import {
  type ConnectorCategory,
  isConnected,
  KIND_CATEGORY,
  lastSeen,
  type Source,
  sourceTone,
} from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * The sources screen, laid out as docs/product/mockups/12-sources.jpeg.
 *
 * Every figure is the workspace's own. What LEKA does not count yet — the
 * items a sync brings, which is LEKA-352's — says so instead of showing the
 * mockup's "48 320" (the overview's rule, 2026-09-25). Deltas ("+2 ce
 * mois-ci") wait for a history of counts to compute them from.
 */

type Category = ConnectorCategory | "other";

function categoryOf(source: Source): Category {
  return KIND_CATEGORY[source.type] ?? "other";
}

export function SourcesPage() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/sources";
  const list = useSources();
  const [category, setCategory] = useState<Category | "all">("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const ownerOf = useOwnerOf();

  const all = list.data ?? [];
  const shown = all.filter(
    (source) => (category === "all" || categoryOf(source) === category) && matches(source, search),
  );
  const selected = all.find((source) => source.id === selectedId) ?? null;

  return (
    <PageContainer>
      <PageHeader
        title={t.sources.title}
        subtitle={t.sources.subtitle}
        breadcrumb={buildBreadcrumb(pathname, t)}
      />
      {list.isPending ? (
        <LoadingState size="page" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} size="page" />
      ) : all.length === 0 ? (
        <NoSources />
      ) : (
        <div className="flex flex-col gap-5">
          <Stats sources={all} />
          <Filters
            sources={all}
            category={category}
            onCategory={setCategory}
            search={search}
            onSearch={setSearch}
          />
          <div className={cn("grid gap-4", selected && "xl:grid-cols-[minmax(0,1fr)_22rem]")}>
            <SourcesTable
              sources={shown}
              selectedId={selectedId}
              ownerOf={ownerOf}
              onSelect={(source) => setSelectedId(source.id === selectedId ? null : source.id)}
            />
            {selected ? (
              <SourcePanel
                source={selected}
                owner={ownerOf(selected)}
                onClose={() => setSelectedId(null)}
              />
            ) : null}
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function matches(source: Source, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return [source.display_name, sourceTitle(source.type)].some((text) =>
    text.toLowerCase().includes(needle),
  );
}

/** Who added it. The API names no one but by id, and lists no members
 * yet (Équipe & accès): "you", or "a member" — never an invented name. */
function useOwnerOf(): (source: Source) => string {
  const t = useDictionary();
  const me = useCurrentUser();
  return (source) => {
    if (source.created_by === null) return "—";
    return source.created_by === me?.id ? t.sources.owner.you : t.sources.owner.member;
  };
}

// ── The figures ─────────────────────────────────────────────────────────────

function Stats({ sources }: { sources: Source[] }) {
  const t = useDictionary();
  const s = t.sources.stats;
  const connected = sources.filter(isConnected).length;
  const running = sources.filter((source) => source.sync_status === "running").length;
  const errors = sources.filter((source) => sourceTone(source) === "error").length;
  const toWatch = sources.filter((source) => sourceTone(source) === "attention").length;
  const synced = sources
    .map((source) => source.last_sync_at)
    .filter((at): at is string => at !== null)
    .sort()
    .at(-1);

  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Stat
        icon={Plug}
        tone="violet"
        value={connected}
        label={s.connected}
        note={fill(s.ofTotal, { total: sources.length })}
      />
      <Stat icon={RefreshCw} tone="success" value={running} label={s.running} />
      <Stat
        icon={CircleAlert}
        tone={errors > 0 ? "danger" : "success"}
        value={errors}
        label={s.errors}
        note={errors === 0 ? s.noErrors : undefined}
      />
      <Stat icon={FileText} tone="info" value="—" label={s.items} note={s.itemsPending} />
      <Stat
        icon={Clock}
        tone="violet"
        value={synced ? timeAgo(t, synced) : s.neverSynced}
        label={s.lastSync}
        note={synced ? (toWatch > 0 ? fill(s.toWatch, { count: toWatch }) : s.upToDate) : undefined}
      />
    </ul>
  );
}

const TONES = {
  success: "bg-state-success-soft text-state-success",
  danger: "bg-state-danger-soft text-state-danger",
  info: "bg-state-info-soft text-state-info",
  violet: "bg-brand-violet-soft text-shell-nav-active",
} as const;

function Stat({
  icon: Icon,
  tone,
  value,
  label,
  note,
}: {
  icon: LucideIcon;
  tone: keyof typeof TONES;
  value: string | number;
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

const CATEGORY_ORDER: Category[] = [
  "code",
  "project",
  "docs",
  "cloud",
  "observability",
  "chat",
  "other",
];

function Filters({
  sources,
  category,
  onCategory,
  search,
  onSearch,
}: {
  sources: Source[];
  category: Category | "all";
  onCategory: (next: Category | "all") => void;
  search: string;
  onSearch: (next: string) => void;
}) {
  const t = useDictionary();
  const counts = new Map<Category, number>();
  for (const source of sources) {
    const key = categoryOf(source);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  // Only the categories this workspace has: an empty "Data 0" is noise.
  const present = CATEGORY_ORDER.filter((key) => counts.has(key));

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label={t.sources.filters.label} className="flex flex-wrap gap-2">
        <Chip
          active={category === "all"}
          onClick={() => onCategory("all")}
          label={t.sources.filters.all}
          count={sources.length}
        />
        {present.map((key) => (
          <Chip
            key={key}
            active={category === key}
            onClick={() => onCategory(key)}
            label={t.sources.categories[key]}
            count={counts.get(key) ?? 0}
          />
        ))}
      </div>
      <SearchInput
        value={search}
        onChange={onSearch}
        placeholder={t.sources.filters.search}
        className="ml-auto w-full sm:w-64"
      />
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
  count: number;
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
      <span className="text-xs text-shell-muted">{count}</span>
    </button>
  );
}

// ── The table ───────────────────────────────────────────────────────────────

function SourcesTable({
  sources,
  selectedId,
  ownerOf,
  onSelect,
}: {
  sources: Source[];
  selectedId: string | null;
  ownerOf: (source: Source) => string;
  onSelect: (source: Source) => void;
}) {
  const t = useDictionary();
  const c = t.sources.columns;
  const columns: KnowledgeColumn<Source>[] = [
    {
      id: "name",
      header: c.name,
      sortValue: (source) => source.display_name.toLowerCase(),
      cell: (source) => (
        <div className={cn("flex items-center gap-3", source.id === selectedId && "font-semibold")}>
          <SourceLogo kind={source.type} className="size-6 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-brand-navy">{source.display_name}</p>
            <p className="truncate text-xs text-shell-muted">{summary(t, source)}</p>
          </div>
        </div>
      ),
    },
    {
      id: "type",
      header: c.type,
      sortValue: (source) => categoryOf(source),
      cell: (source) => (
        <span className="rounded-md bg-state-info-soft px-2 py-0.5 text-xs text-state-info">
          {t.sources.categories[categoryOf(source)]}
        </span>
      ),
    },
    {
      id: "status",
      header: c.status,
      sortValue: (source) => sourceTone(source),
      cell: (source) => <StatusBadge variant={`source.${sourceTone(source)}`} size="sm" />,
    },
    {
      id: "last-sync",
      header: c.lastSync,
      sortValue: (source) => lastSeen(source) ?? "",
      cell: (source) => {
        const seen = lastSeen(source);
        return seen ? timeAgo(t, seen) : t.sources.never;
      },
    },
    {
      id: "items",
      header: c.items,
      align: "end",
      cell: () => (
        <span title={t.sources.notCounted} aria-label={t.sources.notCounted}>
          —
        </span>
      ),
    },
    { id: "owner", header: c.owner, cell: ownerOf },
  ];

  return (
    <KnowledgeTable
      caption={c.caption}
      columns={columns}
      rows={sources}
      rowKey={(source) => source.id}
      onRowClick={onSelect}
      initialSort={{ id: "name", direction: "asc" }}
      empty={{ title: t.sources.filters.noMatch }}
    />
  );
}

/** "GitHub · dépôts, commits, pull requests" — the connector, and what it reads. */
function summary(t: Dictionary, source: Source): string {
  const reads = source.capabilities.slice(0, 3).map((capability) => capabilityWord(t, capability));
  return [sourceTitle(source.type), reads.join(", ")].filter(Boolean).join(" · ");
}

function NoSources() {
  const t = useDictionary();
  const canManage = usePermissions()?.includes("source:manage") ?? false;
  return (
    <StatePanel
      icon={Plug}
      title={t.sources.empty.title}
      description={canManage ? t.sources.empty.manager : t.sources.empty.reader}
      size="page"
    />
  );
}
