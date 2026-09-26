"use client";

import { ArrowDownLeft, ArrowUpRight, ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "cn";

import { EntityIcon } from "@/components/knowledge/entity-card";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { EntityStatus, KnowledgeEntity, RelationshipType } from "@/lib/knowledge";

export interface Dependency {
  entity: Pick<KnowledgeEntity, "id" | "type" | "name">;
  /**
   * upstream: what this entity depends on ("Dépend de").
   * downstream: what depends on it ("Utilisé par").
   */
  direction: "upstream" | "downstream";
  /** depends_on by default. */
  relation?: RelationshipType;
  status?: EntityStatus;
  /** What the link means right now: "Latence +32 %", "Aucun impact détecté". */
  detail?: string;
}

export interface DependencyListProps {
  items: readonly Dependency[];
  /** How many rows before "Voir N de plus". 5 by default. */
  maxVisible?: number;
  onSelect?: (id: string) => void;
  className?: string;
}

/**
 * What an entity depends on and what depends on it, compact (LEKA-340) —
 * the "Dépendances (5)" block of mockup 11.
 *
 * Direction is said in words and with an arrow, never by position alone.
 */
export function DependencyList({
  items,
  maxVisible = 5,
  onSelect,
  className,
}: DependencyListProps) {
  const t = useDictionary();
  const [expanded, setExpanded] = useState(false);
  const listId = useId();

  if (items.length === 0) {
    return (
      <p className={cn("py-3 text-[0.8125rem] text-shell-muted", className)}>
        {t.knowledge.dependencies.empty}
      </p>
    );
  }

  const limit = Math.max(1, maxVisible);
  const shown = expanded ? items : items.slice(0, limit);
  const hidden = items.length - limit;

  return (
    <div className={className}>
      <ul id={listId} className="divide-y divide-shell-line">
        {shown.map((item) => {
          const upstream = item.direction === "upstream";
          const Arrow = upstream ? ArrowUpRight : ArrowDownLeft;
          const direction = upstream
            ? t.knowledge.dependencies.upstream
            : t.knowledge.dependencies.downstream;
          const relation = item.relation && item.relation !== "depends_on"
            ? t.knowledge.relationships[item.relation]
            : null;

          return (
            <li
              key={`${item.direction}:${item.entity.id}`}
              data-direction={item.direction}
              className="relative flex items-center gap-3 py-2"
            >
              <EntityIcon type={item.entity.type} size="sm" />
              <div className="min-w-0 flex-1">
                {onSelect ? (
                  <button
                    type="button"
                    onClick={() => onSelect(item.entity.id)}
                    title={item.entity.name}
                    className="block max-w-full truncate text-left text-[0.8125rem] font-semibold text-brand-navy outline-none after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:after:ring-3 focus-visible:after:ring-brand-violet/40"
                  >
                    {item.entity.name}
                  </button>
                ) : (
                  <p title={item.entity.name} className="truncate text-[0.8125rem] font-semibold text-brand-navy">
                    {item.entity.name}
                  </p>
                )}
                <p className="flex items-center gap-1 text-[0.6875rem] text-shell-muted">
                  <Arrow aria-hidden="true" className="size-3 shrink-0" />
                  <span className="truncate">
                    {direction}
                    {relation ? ` · ${relation}` : null}
                    {item.detail ? ` · ${item.detail}` : null}
                  </span>
                </p>
              </div>
              {item.status ? <StatusBadge variant={`entity.${item.status}`} size="sm" /> : null}
              {onSelect ? (
                <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-shell-icon" />
              ) : null}
            </li>
          );
        })}
      </ul>
      {hidden > 0 ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => setExpanded((open) => !open)}
          className="mt-1 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {expanded
            ? t.knowledge.dependencies.showLess
            : fill(t.knowledge.dependencies.showMore, { count: hidden })}
        </button>
      ) : null}
    </div>
  );
}
