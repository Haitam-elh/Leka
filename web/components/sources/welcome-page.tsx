"use client";

import { Check, CircleCheck, Lock, Plug, Wrench } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";
import { ExploreDemoButton } from "@/components/demo/demo";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useInDemo } from "@/components/demo/in-demo";
import { AddSourceDialog } from "@/components/sources/add-source-dialog";
import { capabilityWord } from "@/components/sources/source-panel";
import { SourceLogo } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { isCustom } from "@/lib/custom-connectors";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import {
  type CatalogEntry,
  CATEGORY_ORDER,
  isConnected,
  type Source,
  type SourceKind,
} from "@/lib/sources";
import { useCatalog, useSources } from "@/lib/sources-queries";

/**
 * Where a new workspace starts — registered, the address confirmed, the
 * workspace created (components/shell/workspace-gate.tsx): which tools does
 * the company use?
 *
 *   1. choose   the catalogue, by category; a tool already connected says
 *               so and is not chosen again
 *   2. connect  the tools chosen, one by one, in Sources' own wizard opened
 *               at their connection; when one is done, the next opens.
 *               Closing the wizard stops there: each row says where its
 *               tool stands — from the workspace's sources, not from this
 *               page's memory — and takes it up again.
 *
 * The page asks the API nothing Sources does not: it is a guide over the
 * same wizard. "Plus tard" leaves it, and Sources is where tools are added
 * any time after.
 */

type Standing =
  | { state: "connected"; source: Source }
  | { state: "started"; source: Source }
  | { state: "waiting" };

/** Where a tool stands in the workspace: one of its sources connected, one
 * begun and not switched on, or none. */
export function standingOf(kind: SourceKind, all: readonly Source[]): Standing {
  const mine = all.filter((source) => source.type === kind);
  const connected = mine.find(isConnected);
  if (connected) return { state: "connected", source: connected };
  const begun = mine.find((source) => source.status === "draft" || source.status === "tested");
  if (begun) return { state: "started", source: begun };
  return { state: "waiting" };
}

/** What the wizard is open on: a tool, and the source it left in draft. */
type Opened = { tool: SourceKind; draft?: Source };

export function WelcomePage() {
  const t = useDictionary();
  const pathname = usePathname() ?? routes.welcome();
  const catalog = useCatalog();
  const list = useSources();
  const [chosen, setChosen] = useState<SourceKind[]>([]);
  const [connecting, setConnecting] = useState(false);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [custom, setCustom] = useState(false);

  const inDemo = useInDemo();

  const breadcrumb = buildBreadcrumb(pathname, t);
  if (catalog.isPending || list.isPending) {
    return (
      <PageContainer>
        <PageHeader title={t.sources.welcome.title} breadcrumb={breadcrumb} />
        <LoadingState size="page" />
      </PageContainer>
    );
  }
  if (catalog.isError || list.isError) {
    const failed = catalog.isError ? catalog : list;
    return (
      <PageContainer>
        <PageHeader title={t.sources.welcome.title} breadcrumb={breadcrumb} />
        <ErrorState error={failed.error} onRetry={() => void failed.refetch()} size="page" />
      </PageContainer>
    );
  }

  const natives = catalog.data.filter((entry) => !isCustom(entry.key));
  const all = list.data;
  const standing = (kind: SourceKind) => standingOf(kind, all);

  /** The wizard on a tool: at its connection, or at its draft's. */
  function open(tool: SourceKind) {
    const now = standing(tool);
    setOpened({ tool, draft: now.state === "started" ? now.source : undefined });
  }

  /** The next tool chosen, after `after`, that is not connected yet. */
  function next(after: SourceKind | null): SourceKind | null {
    const from = after === null ? 0 : chosen.indexOf(after) + 1;
    return chosen.slice(from).find((kind) => standing(kind).state !== "connected") ?? null;
  }

  function start() {
    setConnecting(true);
    const first = next(null);
    if (first) open(first);
  }

  const wizard = (
    <AddSourceDialog
      // A fresh wizard per tool: what was typed for one is not the next's.
      key={opened ? `${opened.tool}-${opened.draft?.id ?? "new"}` : "closed"}
      open={opened !== null}
      tool={opened?.tool}
      editing={opened?.draft}
      onOpenChange={(isOpen) => {
        if (!isOpen) setOpened(null);
      }}
      onDone={(done) => {
        const following = next(done.type);
        if (following) open(following);
      }}
    />
  );

  if (connecting) {
    const entries = chosen
      .map((kind) => natives.find((entry) => entry.key === kind))
      .filter((entry): entry is CatalogEntry => entry !== undefined);
    const done = entries.filter((entry) => standing(entry.key).state === "connected").length;
    return (
      <PageContainer>
        <PageHeader
          title={t.sources.welcome.connectTitle}
          subtitle={t.sources.welcome.connectBody}
          breadcrumb={breadcrumb}
        />
        {wizard}
        <p className="mb-3 text-sm font-medium text-brand-navy" aria-live="polite">
          {fill(t.sources.welcome.progress, { done, total: entries.length })}
        </p>
        <ol className="flex flex-col gap-2">
          {entries.map((entry) => (
            <ToolRow
              key={entry.key}
              entry={entry}
              standing={standing(entry.key)}
              onOpen={() => open(entry.key)}
            />
          ))}
        </ol>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={() => setConnecting(false)}>
            {t.sources.welcome.change}
          </Button>
          <Link href={routes.sources()} className={buttonVariants()}>
            {t.sources.welcome.finish}
          </Link>
        </div>
      </PageContainer>
    );
  }

  const categories = CATEGORY_ORDER.flatMap((category) => {
    const entries = natives.filter((entry) => entry.category === category);
    return entries.length > 0 ? [{ category, entries }] : [];
  });

  function toggle(kind: SourceKind) {
    setChosen((now) => (now.includes(kind) ? now.filter((k) => k !== kind) : [...now, kind]));
  }

  return (
    <PageContainer>
      <PageHeader
        title={t.sources.welcome.title}
        subtitle={t.sources.welcome.subtitle}
        breadcrumb={breadcrumb}
      />
      {wizard}
      {inDemo ? null : <StartChoice />}
      <AddSourceDialog
        open={custom}
        start="custom"
        onOpenChange={(isOpen) => setCustom(isOpen)}
        onDone={() => setCustom(false)}
      />
      <p className="mb-5 flex items-center gap-1.5 text-xs text-shell-muted">
        <Lock className="size-3.5" aria-hidden="true" />
        {t.sources.add.readOnly}
      </p>
      <div id="welcome-tools" className="flex scroll-mt-4 flex-col gap-6">
        {categories.map(({ category, entries }) => (
          <section key={category} aria-labelledby={`welcome-${category}`}>
            <h2 id={`welcome-${category}`} className="mb-2 text-sm font-semibold text-brand-navy">
              {t.sources.categories[category]}
            </h2>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {entries.map((entry) => (
                <ToolChoice
                  key={entry.key}
                  entry={entry}
                  connected={standing(entry.key).state === "connected"}
                  chosen={chosen.includes(entry.key)}
                  onToggle={() => toggle(entry.key)}
                />
              ))}
            </ul>
          </section>
        ))}
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-shell-line p-3 sm:flex-row sm:items-center">
          <p className="flex-1 text-xs text-shell-muted">
            <span className="font-medium text-brand-navy">{t.sources.custom.fromCatalog}</span>{" "}
            {t.sources.welcome.customBody}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => setCustom(true)}>
            <Wrench aria-hidden="true" />
            {t.sources.custom.fromCatalogAction}
          </Button>
        </div>
      </div>
      {/* Kept in view while the catalogue scrolls: what was chosen, and on. */}
      <div className="sticky bottom-0 -mx-4 mt-6 flex flex-wrap items-center gap-3 border-t border-shell-line bg-shell-page px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <p className="flex-1 text-sm text-shell-muted" aria-live="polite">
          {chosen.length > 0
            ? fill(t.sources.welcome.chosen, { count: chosen.length })
            : t.sources.welcome.none}
        </p>
        <Link href={routes.overview()} className={buttonVariants({ variant: "ghost" })}>
          {t.sources.welcome.later}
        </Link>
        <Button disabled={chosen.length === 0} onClick={start}>
          {t.sources.welcome.connect}
        </Button>
      </div>
    </PageContainer>
  );
}

/** Two ways in, of the same weight (LEKA-451): one's own tools, below, or
 * the demonstration — Nova Retail, nothing to connect. */
function StartChoice() {
  const t = useDictionary();
  const w = t.demo;
  return (
    <section aria-labelledby="welcome-start" className="mb-6" data-testid="welcome-start">
      <h2 id="welcome-start" className="mb-2 text-sm font-semibold text-brand-navy">
        {w.chooseTitle}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <a
          href="#welcome-tools"
          className="flex flex-col gap-1 rounded-xl border border-shell-line bg-white p-4 outline-none hover:border-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <span className="flex items-center gap-2 font-semibold text-brand-navy">
            <Plug className="size-4 text-brand-violet" aria-hidden="true" />
            {w.connectTitle}
          </span>
          <span className="text-[0.8125rem] text-shell-muted">{w.connectBody}</span>
        </a>
        <div className="flex flex-col items-start gap-2 rounded-xl border border-shell-line bg-white p-4">
          <span className="font-semibold text-brand-navy">{w.exploreTitle}</span>
          <span className="text-[0.8125rem] text-shell-muted">{w.exploreBody}</span>
          <ExploreDemoButton />
        </div>
      </div>
    </section>
  );
}

function ToolChoice({
  entry,
  connected,
  chosen,
  onToggle,
}: {
  entry: CatalogEntry;
  connected: boolean;
  chosen: boolean;
  onToggle: () => void;
}) {
  const t = useDictionary();
  return (
    <li>
      <button
        type="button"
        aria-pressed={connected ? undefined : chosen}
        disabled={connected}
        onClick={onToggle}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg border bg-white p-3 text-start outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40",
          chosen ? "border-brand-violet bg-brand-violet-soft" : "border-shell-line",
          connected ? "cursor-default opacity-70" : "hover:border-brand-violet",
        )}
      >
        <SourceLogo kind={entry.key} className="size-7 shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-brand-navy">{entry.display_name}</span>
          <span className="block truncate text-xs text-shell-muted">
            {connected
              ? t.sources.welcome.connected
              : entry.capabilities.map((c) => capabilityWord(t, c, entry.key)).join(", ")}
          </span>
        </span>
        {connected ? (
          <CircleCheck className="size-4 shrink-0 text-state-success" aria-hidden="true" />
        ) : (
          <span
            aria-hidden="true"
            className={cn(
              "flex size-5 shrink-0 items-center justify-center rounded border",
              chosen ? "border-brand-violet bg-brand-violet text-white" : "border-shell-line",
            )}
          >
            {chosen ? <Check className="size-3.5" /> : null}
          </span>
        )}
      </button>
    </li>
  );
}

function ToolRow({
  entry,
  standing,
  onOpen,
}: {
  entry: CatalogEntry;
  standing: Standing;
  onOpen: () => void;
}) {
  const t = useDictionary();
  const w = t.sources.welcome;
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-shell-line bg-white p-3">
      <SourceLogo kind={entry.key} className="size-7 shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-brand-navy">{entry.display_name}</span>
        <span
          className={cn(
            "block text-xs",
            standing.state === "connected" ? "text-state-success" : "text-shell-muted",
          )}
        >
          {w[standing.state]}
        </span>
      </span>
      {standing.state === "connected" ? (
        <Link
          href={routes.source(standing.source.id)}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          {w.see}
        </Link>
      ) : (
        <Button size="sm" onClick={onOpen}>
          {standing.state === "started" ? w.resume : w.connectOne}
        </Button>
      )}
    </li>
  );
}
