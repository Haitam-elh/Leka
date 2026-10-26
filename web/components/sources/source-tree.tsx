"use client";

import { ChevronRight, ExternalLink, FileText, FolderTree, Rocket } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/environment/parts";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Source } from "@/lib/sources";
import { type TreeNode, useSourceTree } from "@/lib/source-tree";

/**
 * « Arborescence » (2026-10-25): what a Confluence source synced, space by
 * space — how many pages, how deep, each in its place under its parent — to
 * check that everything came up before the architect reads it. The space's
 * dossier one click away (/architecte).
 */

/** Drawn at most: a tree past this many pages is listed by its top. */
const MOST_DRAWN = 1500;

function Branch({ node, depth, budget }: { node: TreeNode; depth: number; budget: { left: number } }) {
  const t = useDictionary();
  budget.left -= 1;
  const children = node.children ?? [];
  const title = node.url ? (
    <a
      href={node.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-brand-navy hover:underline"
      title={t.sources.tree.open}
    >
      {node.title}
      <ExternalLink className="size-3 text-shell-muted" aria-hidden="true" />
    </a>
  ) : (
    <span className="text-brand-navy">{node.title}</span>
  );
  if (!children.length || budget.left <= 0) {
    return (
      <li className="flex items-center gap-1.5 py-0.5" data-testid="tree-page" data-depth={depth}>
        <FileText className="size-3.5 shrink-0 text-shell-muted" aria-hidden="true" />
        {title}
      </li>
    );
  }
  return (
    <li data-testid="tree-page" data-depth={depth}>
      <details open={depth < 1} className="group">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 py-0.5 [&::-webkit-details-marker]:hidden">
          <ChevronRight className="size-3.5 shrink-0 text-shell-muted transition-transform group-open:rotate-90 rtl:-scale-x-100" aria-hidden="true" />
          {title}
          <span className="text-xs text-shell-muted">({children.length})</span>
        </summary>
        <ul className="ms-4 border-s border-shell-line ps-2">
          {children.map((child) =>
            budget.left > 0 ? <Branch key={child.id} node={child} depth={depth + 1} budget={budget} /> : null,
          )}
        </ul>
      </details>
    </li>
  );
}

export function SourceTreeSection({ source }: { source: Source }) {
  const t = useDictionary();
  const w = t.sources.tree;
  const tree = useSourceTree(source.type === "confluence" ? source.id : null);
  if (source.type !== "confluence") return null;
  const spaces = tree.data?.spaces ?? [];
  const budget = { left: MOST_DRAWN };
  return (
    <Card title={w.title} icon={<FolderTree className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="flex flex-col gap-3" data-testid="source-tree">
        <p className="text-[0.8125rem] text-shell-muted">{w.lead}</p>
        {tree.data && !spaces.length ? <p className="text-[0.8125rem] text-shell-muted">{w.none}</p> : null}
        {spaces.map((space) => (
          <section
            key={space.key}
            className="rounded-lg border border-shell-line p-3"
            data-testid="tree-space"
            data-key={space.key}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="text-[0.9375rem] font-semibold text-brand-navy">
                {space.name} <span className="font-normal text-shell-muted">({space.key})</span>
              </h3>
              <span className="text-xs text-shell-muted" data-testid="tree-space-counts">
                {fill(w.pages, { count: space.pages })} · {fill(w.depth, { depth: space.depth })}
              </span>
              <Link
                href={`${routes.architect()}?source=${encodeURIComponent(source.id)}&space=${encodeURIComponent(space.key)}`}
                className={buttonVariants({ size: "xs", variant: "outline", className: "ms-auto" })}
                data-testid="tree-space-document"
              >
                <Rocket aria-hidden="true" />
                {w.document}
              </Link>
            </div>
            <ul className="mt-2 text-[0.8125rem]">
              {space.nodes.map((node) => (
                <Branch key={node.id} node={node} depth={0} budget={budget} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Card>
  );
}
