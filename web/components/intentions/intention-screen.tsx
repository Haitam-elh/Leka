"use client";

import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  Link2,
  MessageSquareText,
  SearchX,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { cn } from "cn";

import { ActionsTab } from "@/components/actions/actions-tab";
import { IntentionDecision } from "@/components/decisions/intention-decision";
import { Card, entityHref } from "@/components/environment/parts";
import { AgentWork } from "@/components/intentions/agent-work";
import {
  AnalysisProgress,
  AnalysisResults,
  DecisionAside,
  EvidenceTab,
  SummarySaid,
} from "@/components/intentions/analysis-tab";
import {
  IntentionStepper,
  type Step,
  StepBadge,
  STEPS,
  stepOf,
} from "@/components/intentions/intention-stepper";
import { kindOf, StatusPill } from "@/components/intentions/intentions-list";
import { ReadinessPanel } from "@/components/intentions/readiness";
import { linkedLabel } from "@/components/intentions/link-words";
import { RoutingPanel } from "@/components/intentions/routing";
import { scopeLines } from "@/components/intentions/scope";
import { TimelineTab } from "@/components/intentions/timeline-tab";
import { UnderstandingPanel } from "@/components/intentions/understanding";
import { useConfirm } from "@/components/interactions/confirm";
import { Pill } from "@/components/intelligence/pill";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail, IntentionLink } from "@/lib/intentions/api";
import { useIntention, useIntentionChange } from "@/lib/intentions/queries";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { matchRoute } from "@/lib/navigation/active";
import { useNamePage } from "@/lib/navigation/page-name";
import { notify } from "@/lib/notify";

/**
 * An intention's page (LEKA-384): where it stands, what was asked, what it
 * is linked to, and — tab Historique — its whole story, from its analysis
 * to its outcome (LEKA-392, timeline-tab). Tabs Analyse and Preuves: its
 * analysis, how it went and on what (LEKA-388). Actions: what its approved
 * decision became, how it runs, its evidence (LEKA-391).
 *
 * Its asker, or who may approve, cancels it while it can be, archives it
 * once done with, restores it. Nothing is shown that the API did not say.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function IntentionScreen() {
  const t = useDictionary();
  const params = useParams<{ intentionId: string }>();
  const pathname = usePathname() ?? "/";
  const id = params.intentionId ?? "";
  const valid = UUID.test(id);
  const intention = useIntention(valid ? id : "");
  const data = intention.data;
  const crumbs = buildBreadcrumb(pathname, t, data ? () => data.title : undefined);
  useNamePage(pathname, data?.title);
  // The address says which view; none, the step it is at.
  const segment = pathname.replace(/\/$/, "").split("/").length > 3 ? matchRoute(pathname)?.tab : null;
  const missing =
    !valid || (intention.error instanceof ApiError && intention.error.status === 404);

  const where = data ? stepOf(data.status, decides(data)) : null;
  const shown: View = (segment as View | null | undefined) ?? (where ? SEGMENT_OF[where.at] : "overview");
  const step: Step | null = STEP_OF[shown] ?? null;
  const hrefOf = (each: Step) => `${routes.intentions()}/${id}/${SEGMENT_OF[each]}`;

  let body: React.ReactNode;
  if (missing) {
    body = (
      <StatePanel
        icon={SearchX}
        title={t.intentions.notFound}
        testId="intention-not-found"
        actions={
          <Link href={routes.intentions()} className={buttonVariants({ variant: "outline" })}>
            {t.intentions.title}
          </Link>
        }
      />
    );
  } else if (intention.isError) {
    body = <ErrorState error={intention.error} onRetry={() => void intention.refetch()} />;
  } else if (!data) {
    body = <div className="h-80 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else if (shown === "history") {
    body = <TimelineTab id={data.id} />;
  } else if (shown === "evidence") {
    body = <EvidenceTab intention={data} />;
  } else if (shown === "analysis") {
    body = <AnalysisProgress intention={data} />;
  } else if (shown === "results") {
    body = <ResultsStep intention={data} />;
  } else if (shown === "decision") {
    body = <DecisionStep intention={data} />;
  } else if (shown === "actions") {
    body = <ActionsTab intention={data} />;
  } else {
    body = <Overview intention={data} />;
  }

  const w = t.intentions.steps;
  // Step 2 says it is analysing while it is, and that it analysed after.
  const analysed =
    step === "analysis" && data !== undefined && !["analysing", "submitted"].includes(data.status);
  const heading = step
    ? analysed
      ? w.analysis.done
      : w[step].heading
    : shown === "history"
      ? t.tabs.history
      : t.tabs.evidence;
  const lead = step ? (analysed ? w.analysis.doneLead : w[step].lead) : undefined;

  return (
    <PageContainer>
      <PageHeader
        title={data ? heading : t.nav.intentionDetail}
        subtitle={data ? lead : undefined}
        breadcrumb={crumbs}
        actions={
          data ? (
            <>
              {step ? <StepBadge step={step} /> : null}
              <Actions intention={data} />
            </>
          ) : undefined
        }
      />
      {data && where ? (
        <>
          <IntentionStepper
            current={where.at}
            shown={step ?? undefined}
            reached={where.reached}
            done={data.status === "completed"}
            hrefOf={hrefOf}
            testIdOf={(each) => `tab-${SEGMENT_OF[each]}`}
            last={decides(data) ? undefined : STEPS.indexOf("results")}
          />
          <Asked intention={data} />
          {/* What an agent is doing for it — its PDF the moment it is drawn. */}
          <div className="mb-4">
            <AgentWork intentionId={data.id} />
          </div>
        </>
      ) : null}
      {body}
      {data ? <MoreViews id={data.id} shown={shown} /> : null}
    </PageContainer>
  );
}

/** What the address may say, and the step each view is. */
type View = "overview" | "analysis" | "results" | "decision" | "actions" | "evidence" | "history";
const SEGMENT_OF: Record<Step, View> = {
  intention: "overview",
  analysis: "analysis",
  results: "results",
  decision: "decision",
  action: "actions",
};
const STEP_OF: Partial<Record<View, Step>> = {
  overview: "intention",
  analysis: "analysis",
  results: "results",
  decision: "decision",
  actions: "action",
};

const DECIDED: readonly IntentionDetail["status"][] = [
  "awaiting_decision",
  "approved",
  "scheduled",
  "executing",
  "verifying",
  "rejected",
];

/** Whether it goes, or went, past its results: something to do on the
 * systems, put to a decision. A question answered stops at its results —
 * as the tab Actions reads it. */
function decides(intention: IntentionDetail): boolean {
  if (DECIDED.includes(intention.status)) return true;
  const understood = intention.understanding;
  if (!understood) return intention.status !== "completed";
  return (
    understood.goal.code === "act" || understood.actions.some((action) => action.changes_systems)
  );
}

/** Mockup 04's banner: what was asked, said once above every step. */
function Asked({ intention }: { intention: IntentionDetail }) {
  return (
    <section
      className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-shell-line bg-white px-5 py-4"
      data-testid="intention-asked"
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-brand-violet-soft text-brand-violet">
        <MessageSquareText className="size-5" aria-hidden="true" />
      </span>
      <p
        className="min-w-0 flex-1 text-[1.0625rem] font-semibold text-brand-navy"
        data-testid="intention-text"
        dir="auto"
      >
        {intention.text}
      </p>
      <Subtitle intention={intention} />
    </section>
  );
}

/** The evidence and the whole story: one click away from every step, the
 * one open marked. */
function MoreViews({ id, shown }: { id: string; shown: View }) {
  const t = useDictionary();
  const w = t.intentions.steps;
  return (
    <nav className="mt-6 flex flex-wrap gap-2" aria-label={t.intentions.title}>
      {(["evidence", "history"] as const).map((view) => (
        <Link
          key={view}
          href={`${routes.intentions()}/${id}/${view}`}
          aria-current={shown === view ? "page" : undefined}
          className={cn(
            "inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-[0.8125rem] font-medium text-brand-violet hover:bg-brand-violet-soft",
            shown === view && "bg-brand-violet-soft",
          )}
          data-testid={`tab-${view}`}
        >
          {w[view]}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      ))}
    </nav>
  );
}

/** Step 3, mockup 04: what LEKA concludes, then what it found. */
function ResultsStep({ intention }: { intention: IntentionDetail }) {
  return <AnalysisResults intention={intention} />;
}

/** Step 4, mockup 05: what to decide, and why. Nothing to decide — a
 * question answered — said so. */
function DecisionStep({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
      <div className="min-w-0 space-y-4">
        <IntentionDecision intentionId={intention.id} />
        {decides(intention) ? null : (
          <p className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem] text-shell-muted">
            {t.intentions.steps.notNeeded}
          </p>
        )}
      </div>
      <DecisionAside intention={intention} />
    </div>
  );
}

function Subtitle({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const me = useCurrentUser();
  const { format: locale } = useLocale();
  // Said inside a sentence: « Créée il y a 3 min », not « Créée Il y a ».
  const ago = timeAgo(t, intention.created_at);
  const when = ago.charAt(0).toLocaleLowerCase(locale) + ago.slice(1);
  const name = intention.created_by && intention.created_by === me?.id ? t.intentions.you : null;
  return (
    <span className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-shell-muted">
      <StatusPill status={intention.status} />
      {intention.archived_at ? <Pill tone="neutral">{t.intentions.archived}</Pill> : null}
      <span>
        {name ? fill(t.intentions.createdBy, { when, name }) : fill(t.intentions.created, { when })}
      </span>
    </span>
  );
}

function Actions({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.actions;
  const confirm = useConfirm();
  const change = useIntentionChange(intention.id);
  const cancellable = intention.moves.includes("cancelled");
  const archivable =
    !intention.archived_at && ["completed", "rejected", "cancelled"].includes(intention.status);

  async function run(kind: "cancel" | "archive" | "restore", reason?: string) {
    try {
      await change.mutateAsync({ change: kind, reason });
      notify.success({ title: w.done });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {cancellable ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-cancel"
          onClick={async () => {
            const reason = await confirm({
              title: w.cancelTitle,
              description: w.cancelBody,
              confirmLabel: w.cancelConfirm,
              destructive: true,
              reasonLabel: w.cancelReason,
            });
            if (reason !== null) await run("cancel", reason);
          }}
        >
          <XCircle className="size-4" aria-hidden="true" />
          {w.cancel}
        </Button>
      ) : null}
      {archivable ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-archive"
          onClick={() => void run("archive")}
        >
          <Archive className="size-4" aria-hidden="true" />
          {w.archive}
        </Button>
      ) : null}
      {intention.archived_at ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-restore"
          onClick={() => void run("restore")}
        >
          <ArchiveRestore className="size-4" aria-hidden="true" />
          {w.restore}
        </Button>
      ) : null}
    </div>
  );
}

// ── Vue d'ensemble ──────────────────────────────────────────────────────

function LinkLine({ link }: { link: IntentionLink }) {
  const t = useDictionary();
  const kind = t.intentions.linkKinds[link.kind];
  const type = typeof link.detail.type === "string" ? link.detail.type : null;
  const version = typeof link.detail.version === "number" ? link.detail.version : null;
  const label =
    link.kind === "context" && version !== null
      ? `${link.label} · v${version}`
      : linkedLabel(t, link.kind, link.label, link.detail);
  return (
    <li className="flex items-start gap-2 text-[0.8125rem]" data-testid="intention-link">
      <Pill tone="neutral">{kind}</Pill>
      {link.kind === "entity" && type ? (
        <Link
          href={entityHref({ id: link.ref_id, type })}
          className="min-w-0 font-medium text-brand-navy hover:underline"
        >
          {label}
        </Link>
      ) : (
        <span className="min-w-0 text-brand-navy">{label}</span>
      )}
    </li>
  );
}

function Overview({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.overview;
  const kind = kindOf(t, intention.kind);
  const scope = scopeLines(t, locale, intention.scope as Record<string, unknown>);
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        {/* What it asks to do, put to a decision (LEKA-390). */}
        <IntentionDecision intentionId={intention.id} />
        {intention.understanding ? (
          <UnderstandingPanel
            understanding={intention.understanding}
            intentionId={intention.status === "needs_clarification" ? intention.id : undefined}
          />
        ) : null}
        {/* What was asked is the banner above every step: here, what it is
            and where. */}
        <Card title={w.asked}>
          <dl className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
            <dt className="text-shell-muted">{w.kind}</dt>
            <dd className="text-brand-navy">{kind ?? "—"}</dd>
            <dt className="text-shell-muted">{w.scope}</dt>
            <dd className="text-brand-navy">
              {scope.length ? scope.map((line) => <span key={line} className="block">{line}</span>) : w.noScope}
            </dd>
          </dl>
        </Card>
        <Card title={w.summary}>
          <SummarySaid intention={intention} none={w.noSummary} />
        </Card>
      </div>
      <div className="flex flex-col gap-4">
        {/* Whether its context can ground its analysis (LEKA-387). */}
        {intention.readiness ? <ReadinessPanel readiness={intention.readiness} /> : null}
        {/* The capability it goes to, and why (LEKA-398). */}
        <RoutingPanel intentionId={intention.id} />
        <Card title={w.links} icon={<Link2 className="size-4 text-shell-muted" aria-hidden="true" />}>
          {intention.links.length ? (
            <ul className="space-y-2">
              {intention.links.map((link) => (
                <LinkLine key={link.id} link={link} />
              ))}
            </ul>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.noLinks}</p>
          )}
        </Card>
        <Card title={w.next}>
          <ul className="flex flex-wrap gap-2" data-testid="intention-moves">
            {intention.moves.length ? (
              intention.moves.map((status) => (
                <li key={status}>
                  <Pill tone="neutral">{t.intentions.statuses[status]}</Pill>
                </li>
              ))
            ) : (
              <li className="text-[0.8125rem] text-shell-muted">—</li>
            )}
          </ul>
        </Card>
      </div>
    </div>
  );
}
