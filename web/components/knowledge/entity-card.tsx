"use client";

import {
  AppWindow,
  Boxes,
  Building2,
  CircleDot,
  Cloud,
  Database,
  FileText,
  FolderGit2,
  FolderKanban,
  GitCommitHorizontal,
  GitPullRequest,
  Layers,
  type LucideIcon,
  Rocket,
  Server,
  Tag,
  TriangleAlert,
  User,
  Users,
} from "lucide-react";

import { cn } from "cn";

import { FreshnessIndicator, QualityIndicator } from "@/components/knowledge/indicators";
import { ProvenanceBadge } from "@/components/knowledge/provenance-badge";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { confidenceToScore, type EntityType, type KnowledgeEntity } from "@/lib/knowledge";

/** One icon per kind of entity the backend knows (leka/knowledge). */
export const ENTITY_ICONS: Record<EntityType, LucideIcon> = {
  service: Server,
  repository: FolderGit2,
  incident: TriangleAlert,
  deployment: Rocket,
  person: User,
  document: FileText,
  infra_resource: Cloud,
  database: Database,
  team: Users,
  project: FolderKanban,
  issue: CircleDot,
  pull_request: GitPullRequest,
  commit: GitCommitHorizontal,
  release: Tag,
  application: AppWindow,
  environment: Layers,
  cloud_account: Building2,
  resource_group: Boxes,
};

export function EntityIcon({
  type,
  size = "md",
  className,
}: {
  type: EntityType;
  size?: "sm" | "md";
  className?: string;
}) {
  const Icon = ENTITY_ICONS[type];
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg",
        type === "incident"
          ? "bg-state-danger-soft text-state-danger"
          : "bg-brand-violet-soft text-shell-nav-active",
        size === "sm" ? "size-7" : "size-9",
        className,
      )}
    >
      <Icon className={size === "sm" ? "size-4" : "size-[18px]"} />
    </span>
  );
}

export interface EntityCardProps extends KnowledgeEntity {
  /** Makes the whole card clickable; the name is the button. */
  onClick?: (id: string) => void;
  /** The entity is the one open elsewhere — a panel, a graph selection. */
  selected?: boolean;
  /** Icon, name and status only: dense lists and graph nodes. */
  compact?: boolean;
  className?: string;
}

/**
 * An entity of the knowledge graph, the same way on every screen (LEKA-340).
 *
 * CLICKABLE WITHOUT NESTING BUTTONS. The provenance and freshness badges are
 * buttons of their own (their tooltips open from the keyboard), and a button
 * inside a button is invalid. So the NAME is the card's button, stretched
 * over the whole card by a pseudo-element; the badges sit above it and stay
 * separately reachable.
 *
 * Everything but id, type and name is optional, and missing parts leave no
 * gap: a card built from the backend's EntityRead alone is a valid card.
 */
export function EntityCard({
  id,
  type,
  name,
  description,
  status,
  owner,
  tags,
  lastUpdated,
  confidence,
  source,
  onClick,
  selected = false,
  compact = false,
  className,
}: EntityCardProps) {
  const t = useDictionary();
  const typeLabel = t.knowledge.entityTypes[type];

  const title = onClick ? (
    <button
      type="button"
      onClick={() => onClick(id)}
      aria-current={selected ? "true" : undefined}
      title={name}
      className="block max-w-full truncate text-left outline-none after:absolute after:inset-0 after:rounded-[inherit] after:content-[''] focus-visible:after:ring-3 focus-visible:after:ring-brand-violet/40"
    >
      {name}
    </button>
  ) : (
    <span title={name} className="block truncate">
      {name}
    </span>
  );

  const frame = cn(
    "relative rounded-xl border bg-white transition-colors",
    selected ? "border-shell-nav-active ring-2 ring-brand-violet/30" : "border-shell-line",
    onClick && "hover:border-shell-nav-active/50",
  );

  if (compact) {
    return (
      <article
        data-slot="entity-card"
        data-compact="true"
        data-entity-id={id}
        className={cn(frame, "flex min-w-0 items-center gap-2.5 px-3 py-2", className)}
      >
        <EntityIcon type={type} size="sm" />
        <div className="min-w-0">
          <h3 className="text-[0.8125rem] leading-5 font-semibold text-brand-navy">{title}</h3>
          {status ? (
            <StatusBadge variant={`entity.${status}`} dot size="sm" className="mt-0.5" />
          ) : (
            <p className="text-[0.6875rem] text-shell-muted">{typeLabel}</p>
          )}
        </div>
      </article>
    );
  }

  const trust = lastUpdated !== undefined || source !== undefined || confidence !== undefined;

  return (
    <article
      data-slot="entity-card"
      data-entity-id={id}
      className={cn(frame, "flex min-w-0 flex-col gap-3 p-4", className)}
    >
      <div className="flex items-start gap-3">
        <EntityIcon type={type} />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm leading-5 font-semibold text-brand-navy">{title}</h3>
          <p className="truncate text-xs text-shell-muted">
            {typeLabel}
            {owner ? ` · ${owner.name}` : null}
          </p>
        </div>
        {status ? <StatusBadge variant={`entity.${status}`} size="sm" /> : null}
      </div>

      {description ? (
        <p className="line-clamp-2 text-[0.8125rem] text-shell-muted">{description}</p>
      ) : null}

      {tags && tags.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={t.knowledge.detail.tags}>
          {tags.map((tag) => (
            <li
              key={tag}
              className="rounded-md bg-shell-canvas px-1.5 py-0.5 text-[0.6875rem] text-shell-nav"
            >
              {tag}
            </li>
          ))}
        </ul>
      ) : null}

      {trust ? (
        // Above the stretched button, so each stays reachable on its own.
        <div className="relative z-10 flex flex-wrap items-center gap-2">
          {lastUpdated !== undefined ? <FreshnessIndicator lastUpdated={lastUpdated} /> : null}
          {source ? (
            <ProvenanceBadge
              source={source}
              quality={confidence !== undefined ? confidenceToScore(confidence) : undefined}
            />
          ) : null}
          {confidence !== undefined ? (
            <QualityIndicator score={confidenceToScore(confidence)} />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
