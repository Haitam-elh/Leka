"use client";

import {
  Archive,
  ArchiveRestore,
  ArrowLeft,
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
import {
  AgentsAction,
  AgentsDecision,
  PlanChecklist,
  ProposalView,
} from "@/components/intentions/agents-decision";
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
} from "@/components/intentions/intention-stepper";
import { DeleteIntention } from "@/components/intentions/delete-intention";
import { JourneyNote, StopAnalysis, useRights } from "@/components/intentions/journey";
import { BriefView } from "@/components/intentions/brief";
import { DeliverableView } from "@/components/intentions/deliverable";
import { FeasibilityCard } from "@/components/intentions/feasibility";
import { IntentionDetailPage } from "@/components/intentions/intention-detail";
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
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useIntentionRuns } from "@/lib/agent-runs-queries";
import type { IntentionDetail, IntentionLink } from "@/lib/intentions/api";
import { may } from "@/lib/intentions/journey";
import { useAnswer, useIntention, useIntentionChange } from "@/lib/intentions/queries";
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

  // Where it stands is the API's (LEKA-443): never a state of the screen's.
  const where = data ? data.journey.step : null;
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
  } else if (shown === "deliverable") {
    body = <DeliverableView intention={data} />;
  } else if (shown === "evidence") {
    body = <EvidenceTab intention={data} />;
  } else if (shown === "analysis") {
    body = <AnalysisProgress intention={data} />;
  } else if (shown === "results") {
    body = <ResultsStep intention={data} />;
  } else if (shown === "decision") {
    body = <DecisionStep intention={data} />;
  } else if (shown === "actions") {
    body = <ActionStep intention={data} />;
  } else {
    body = <Overview intention={data} />;
  }

  // Its page (LEKA-458): what was asked, understood, the plan, the agents,
  // the capacity and the offer — each step's view a click away, in
  // « Détails techniques ».
  if (!segment && data && !missing) {
    return (
      <PageContainer>
        <IntentionDetailPage intention={data} />
      </PageContainer>
    );
  }

  const w = t.intentions.steps;
  // Step 2 says it is analysing while it is, and that it analysed after.
  const analysed =
    step === "analysis" &&
    data !== undefined &&
    !["ready", "analysing"].includes(data.journey.state);
  const heading = step
    ? analysed
      ? w.analysis.done
      : w[step].heading
    : shown === "history"
      ? t.tabs.history
      : shown === "deliverable"
        ? t.tabs.deliverable
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
            done={where.done}
            hrefOf={hrefOf}
            testIdOf={(each) => `tab-${SEGMENT_OF[each]}`}
            last={where.last < STEPS.length - 1 ? where.last : undefined}
          />
          <Asked intention={data} />
          {/* What happened, since when, what comes next and who (LEKA-443). */}
          <JourneyNote intention={data} />
        </>
      ) : null}
      {body}
      {data ? <MoreViews id={data.id} shown={shown} /> : null}
    </PageContainer>
  );
}

/** What the address may say, and the step each view is. */
type View =
  | "overview"
  | "analysis"
  | "results"
  | "decision"
  | "actions"
  | "evidence"
  | "history"
  | "deliverable";
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
  const w = { ...t.intentions.steps, deliverable: t.tabs.deliverable };
  // Its agents' deliverable, once one worked on it (2026-10-14).
  const runs = useIntentionRuns(id);
  const views = runs.data?.length
    ? (["deliverable", "evidence", "history"] as const)
    : (["evidence", "history"] as const);
  return (
    <nav className="mt-6 flex flex-wrap gap-2" aria-label={t.intentions.title}>
      {views.map((view) => (
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

/** Step 3, mockup 04: what LEKA concludes, what it found — then the plan
 * and the agents it takes (2026-10-14). */
function ResultsStep({ intention }: { intention: IntentionDetail }) {
  return (
    <div className="space-y-4">
      <AnalysisResults intention={intention} />
      <ProposalView intention={intention} />
    </div>
  );
}

/** Step 4, mockup 05: every request decided (2026-10-14) — its agents
 * launched, or done by hand; and, when it changes systems, the decision
 * on its actions (LEKA-390). */
function DecisionStep({ intention }: { intention: IntentionDetail }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
      <div className="min-w-0 space-y-4">
        <IntentionDecision intentionId={intention.id} />
        <AgentsDecision intention={intention} />
      </div>
      <DecisionAside intention={intention} />
    </div>
  );
}

/** Step 5: what is done — by its agents, by its asker with the plan, or the
 * actions a decision approved (LEKA-391). */
function ActionStep({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const runs = useIntentionRuns(intention.id);
  const path = intention.journey.path;
  if (path === "self") return <PlanChecklist intention={intention} />;
  if (path === "agents" || runs.data?.length) return <AgentsAction intention={intention} />;
  if (intention.status === "awaiting_decision") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-shell-line bg-white px-5 py-4" data-testid="action-nothing-yet">
        <p className="min-w-0 flex-1 text-[0.875rem] text-shell-muted">
          {t.intentions.agents.nothingYet}
        </p>
        <Link
          href={`${routes.intentions()}/${intention.id}/decision`}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          {t.intentions.agents.toDecision}
        </Link>
      </div>
    );
  }
  return <ActionsTab intention={intention} />;
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
      <StatusPill status={intention.status} journey={intention.journey} />
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
  const rights = useRights(intention);
  // What its state allows, to whoever may (LEKA-443): never a control the
  // API would refuse.
  const cancellable = may(intention.journey, "cancel", rights);
  const archivable = !intention.archived_at && intention.journey.controls.includes("archive");
  const modifiable = may(intention.journey, "modify_decision", rights);

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
      {/* Mockup 03: « Arrêter l'analyse », while it is analysed. */}
      <StopAnalysis intention={intention} />
      {/* Mockup 06: « Modifier la décision » — only while it is open. */}
      {modifiable ? (
        <Link
          href={`${routes.intentions()}/${intention.id}/decision`}
          className={buttonVariants({ variant: "outline" })}
          data-testid="intention-modify-decision"
        >
          <ArrowLeft className="rtl:-scale-x-100 size-4" aria-hidden="true" />
          {t.intentions.journey.controls.modify_decision}
        </Link>
      ) : null}
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
      <DeleteIntention intention={intention} />
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
        {/* What LEKA understood and still asks, answered here (LEKA-439);
            an intention kept before its brief: what LEKA understood. */}
        {intention.brief && intention.understanding ? (
          <BriefPanel intention={intention} />
        ) : intention.understanding ? (
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
            <dd className="text-brand-navy">{kind ?? "-"}</dd>
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
        {/* What it takes to carry it through here (LEKA-439). */}
        <FeasibilityCard intentionId={intention.id} />
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
      </div>
    </div>
  );
}

/** Its brief, its questions answered here by its asker or who may approve,
 * while it waits for them — answered, it is asked again (LEKA-439). */
function BriefPanel({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const me = useCurrentUser();
  const steward = usePermissions()?.includes("intention:approve") ?? false;
  const answer = useAnswer(intention.id);
  const yours = Boolean(me?.id) && intention.created_by === me?.id;
  const open =
    !intention.archived_at &&
    (intention.status === "needs_clarification" || intention.status === "analysing");
  if (!intention.brief || !intention.understanding) return null;
  return (
    <BriefView
      brief={intention.brief}
      understanding={intention.understanding}
      answers={intention.answers ?? []}
      pending={answer.isPending}
      onAnswer={
        (yours || steward) && open
          ? (given) =>
              answer.mutate([given], {
                onSuccess: () => notify.success({ title: t.intentions.brief.send }),
                onError: (error) =>
                  notify.error({
                    title: error instanceof ApiError ? error.message : String(error),
                  }),
              })
          : undefined
      }
    />
  );
}
