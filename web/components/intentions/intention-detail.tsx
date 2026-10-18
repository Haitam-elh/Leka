"use client";

import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Bot,
  Check,
  CircleCheck,
  Code2,
  Database,
  FileText,
  FlaskConical,
  Gauge,
  Lock,
  type LucideIcon,
  Network,
  Paperclip,
  Server,
  ShieldCheck,
  Siren,
  Sparkles,
  Target,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { cn } from "cn";
import { summaryOf } from "@/components/capabilities/catalogue";
import { entityHref } from "@/components/environment/parts";
import { AgentsAction, useProposal } from "@/components/intentions/agents-decision";
import { AnalysisResults, EvidenceTab } from "@/components/intentions/analysis-tab";
import { sizeOf } from "@/components/intentions/attachments";
import { DeleteIntention } from "@/components/intentions/delete-intention";
import { JourneyNote } from "@/components/intentions/journey";
import { phaseOf, Working } from "@/components/intentions/working";
import { useConfirm } from "@/components/interactions/confirm";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { SourceLogo } from "@/components/sources/source-logo";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { useIntentionRuns } from "@/lib/agent-runs-queries";
import { billing, euros } from "@/lib/billing";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type {
  AgentLaunch,
  IntentionDetail,
  IntentionOffer,
  OfferAgent,
  ProposedAgent,
} from "@/lib/intentions/api";
import { attachmentAddress } from "@/lib/intentions/attachments";
import { intentionKeys, useDecide, useIntentionAnalysis, useIntentionOffer } from "@/lib/intentions/queries";
import { notify } from "@/lib/notify";
import { useSources } from "@/lib/sources-queries";
import { subscription } from "@/lib/subscription";
import type { SourceKind } from "@/lib/sources";
import { useQueryClient } from "@tanstack/react-query";

/**
 * An intention's page (LEKA-458), as « LEKA React Migration Analysis
 * Dashboard » draws it: what was asked and what LEKA answers; what it
 * understood and the sources it reads; the agents the work needs, each as
 * this workspace may run it; the AI capacity it will take; the least plan
 * that carries it, every line and the total — now, with the launch offer,
 * and after — before any consent. Beside it: the plan step by step, what it
 * reaches, what it delivers.
 *
 * Every figure is the server's (GET /intentions/{id}/offer, the catalogue
 * of LEKA-454): an estimate said as one, a measure as a measure. Nothing is
 * bought without a confirmation that says it all; rights come once Stripe
 * confirms the payment.
 */
export function IntentionDetailPage({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const search = useSearchParams();
  const client = useQueryClient();
  const { proposal } = useProposal(intention);
  const runs = useIntentionRuns(intention.id);
  const [chosen, setChosen] = useState<string[] | undefined>(undefined);
  // The files each agent draws, chosen before it runs (2026-10-16: without a
  // choice the architect delivered its report alone, never its deck). Ticked
  // by default: what the request named, else every file it draws.
  const [files, setFiles] = useState<Record<string, string[]>>({});
  const filesOf = (agent: ProposedAgent): string[] =>
    files[agent.key] ??
    (agent.asked.length ? agent.asked : agent.deliverables.filter((d) => DRAWN.has(d)));
  const bought = search?.get("bought");
  const activated = search?.get("activated");
  const confirming = Boolean((bought && bought !== "cancelled") || activated === "success");
  const offer = useIntentionOffer(intention.id, chosen, {
    enabled: Boolean(proposal),
    following: confirming,
  });

  // Back from Stripe: said once, then followed until the server says so.
  useEffect(() => {
    if (bought === "cancelled" || activated === "cancelled") notify.info({ title: w.cancelled });
    else if (bought) notify.success({ title: w.boughtSoon });
    else if (activated === "success") notify.success({ title: w.activatedSoon });
  }, [bought, activated, w]);
  useEffect(() => {
    if (!bought || bought === "cancelled" || intention.status === "executing") return;
    const every = window.setInterval(
      () => void client.invalidateQueries({ queryKey: intentionKeys.one(intention.id) }),
      3000,
    );
    return () => window.clearInterval(every);
  }, [bought, intention.status, intention.id, client]);

  const executing =
    intention.journey.path === "agents" || (runs.data?.length ?? 0) > 0 || intention.status === "executing";

  return (
    <div className="space-y-4" data-testid="intention-detail-page">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={routes.overview()}
          className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy shadow-sm ring-1 ring-shell-line hover:bg-shell-canvas"
        >
          <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden="true" />
          {w.back}
        </Link>
        <DeleteIntention intention={intention} />
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] xl:items-start">
        {/* Laid out by the room each column has, not the screen's (container
            queries): the same blocks read well beside a panel, on a phone. */}
        <div className="@container min-w-0 space-y-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-shell-line">
          <Exchange intention={intention} offer={offer.data} hasProposal={Boolean(proposal)} />
          {/* What LEKA is doing, now (LEKA-465): at once, read from the
              server — kept through a refresh — and only what happened. */}
          <Working intention={intention} />
          {NOTED.has(intention.journey.state) ? <JourneyNote intention={intention} /> : null}
          <UnderstandingCard
            intention={intention}
            offer={offer.data}
            chosen={chosen}
            onChoose={setChosen}
            filesOf={filesOf}
            onFiles={(key, list) => setFiles((now) => ({ ...now, [key]: list }))}
          />
          {executing ? (
            <section className="space-y-3" data-testid="detail-execution">
              <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.executionTitle}</h2>
              {/* At work, its steps are said above; ended, its deliverables
                  and a failed one to launch again. */}
              {phaseOf(intention, runs.data) === "agents" ? null : <AgentsAction intention={intention} />}
            </section>
          ) : offer.data && offer.data.agents.length ? (
            <>
              <CapacityCard offer={offer.data} />
              {offer.data.ready ? (
                // Everything covered (LEKA-464): launched as it is — no
                // price, no total, no checkout.
                <CoveredCard
                  intention={intention}
                  offer={offer.data}
                  proposal={proposal?.agents ?? []}
                  filesOf={filesOf}
                />
              ) : (
              <OfferCard
                intention={intention}
                offer={offer.data}
                proposal={proposal?.agents ?? []}
                filesOf={filesOf}
              />
              )}
            </>
          ) : null}
        </div>
        <SidePanel intention={intention} offer={offer.data} />
      </div>
    </div>
  );
}

// ── what was asked, what LEKA answers ──────────────────────────────────────

function initialsOf(name: string): string {
  return (
    name
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
}

function Exchange({
  intention,
  offer,
  hasProposal,
}: {
  intention: IntentionDetail;
  offer: IntentionOffer | undefined;
  hasProposal: boolean;
}) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const me = useCurrentUser();
  const { format } = useLocale();
  const at = (iso: string) =>
    new Intl.DateTimeFormat(format, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const name = [me?.first_name, me?.last_name].filter(Boolean).join(" ") || me?.email || "";
  const plan = offer ? planLabel(offer.plan_now) : "";
  const state = intention.journey.state;
  const said = (() => {
    if (state === "needs_clarification") return w.clarify;
    if (["draft", "ready", "analysing"].includes(state)) return w.reading;
    if (!hasProposal || !offer) return w.answered;
    if (offer.blocked) return fill(w.blocked, { plan });
    if (!offer.agents.length) return w.answered;
    if (offer.change_plan && offer.lines.some((l) => l.kind === "plan")) return fill(w.planChange, { plan });
    if (offer.lines.length) return fill(w.agentsToAdd, { plan });
    return fill(w.covered, { plan });
  })();
  return (
    <section className="space-y-4" aria-label={w.mine}>
      <div className="flex items-start gap-4" data-testid="detail-request">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-violet text-sm font-semibold text-white">
          {initialsOf(name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1 flex items-center gap-2 text-xs text-shell-muted">
            <span className="rounded-md bg-brand-violet-soft px-2 py-0.5 font-medium text-brand-violet">{w.mine}</span>
            {at(intention.created_at)}
          </p>
          <p
            className="rounded-xl bg-brand-violet-soft/60 px-4 py-3 text-[0.9375rem] leading-relaxed text-brand-navy"
            dir="auto"
          >
            {intention.text}
          </p>
          {intention.attachments?.length ? (
            // The files it was asked with, as kept — each to read.
            <ul
              className="mt-2 flex flex-wrap gap-2"
              aria-label={t.composer.files.label}
              data-testid="detail-attachments"
            >
              {intention.attachments.map((file) => (
                <li key={file.id}>
                  <a
                    href={attachmentAddress(intention.id, file.id)}
                    className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-shell-line bg-white px-2.5 py-1 text-xs text-brand-navy outline-none hover:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                    data-testid="detail-attachment"
                  >
                    <Paperclip className="size-3.5 shrink-0 text-shell-muted" aria-hidden="true" />
                    <span className="truncate font-medium">{file.name}</span>
                    <span className="shrink-0 text-shell-muted">
                      · {(t.composer.files.kinds as Record<string, string>)[file.content_type] ?? file.content_type} ·{" "}
                      {sizeOf(file.size_bytes, format)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      <div className="flex items-start gap-4" data-testid="detail-leka">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-shell-line">
          <Sparkles className="size-5 text-brand-violet" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1 flex items-center gap-2 text-xs text-shell-muted">
            <span className="text-[0.9375rem] font-semibold text-brand-navy">{w.leka}</span>
            {at(intention.updated_at)}
          </p>
          <p className="text-[0.9375rem] leading-relaxed text-shell-accent-muted">{said}</p>
        </div>
      </div>
    </section>
  );
}

// ── what LEKA understood, the agents it takes ─────────────────────────────

const CATEGORY_ICON: Record<string, LucideIcon> = {
  architecture: Network,
  development: Code2,
  testing: FlaskConical,
  incident: Siren,
  security: ShieldCheck,
  infrastructure: Server,
  data: Database,
  documentation: FileText,
  performance: BarChart3,
  operations: Activity,
  knowledge: FileText,
};

// Where the journey's word matters on its page (LEKA-465): working, stopped,
// failed — its since, its next, the controls it allows (stop, resume, retry).
const NOTED = new Set([
  "draft",
  "ready",
  "needs_clarification",
  "analysing",
  "analysis_partial",
  "analysis_failed",
  "action_running",
  "action_failed",
  "cancelled",
]);

// The files an agent draws besides its report (as the decision step offers).
const DRAWN = new Set(["pdf", "pptx"]);

/** Included — with the plan to take, when it is not the one it is on. */
function includedAs(offer: IntentionOffer | undefined, w: Dictionary["intentions"]["detail"]): string {
  return offer?.change_plan ? fill(w.includedWith, { plan: offer.plan.name }) : w.included;
}

function iconOf(category: string): LucideIcon {
  return CATEGORY_ICON[category] ?? Bot;
}

function planLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function UnderstandingCard({
  intention,
  offer,
  chosen,
  onChoose,
  filesOf,
  onFiles,
}: {
  intention: IntentionDetail;
  offer: IntentionOffer | undefined;
  chosen: string[] | undefined;
  onChoose: (keys: string[]) => void;
  filesOf: (agent: ProposedAgent) => string[];
  onFiles: (key: string, files: string[]) => void;
}) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const sources = useSources();
  const scoped = (intention.scope as { sources?: string[] } | null)?.sources ?? [];
  const shown = (sources.data ?? []).filter(
    (s) => (scoped.length ? scoped.includes(s.id) : true) && s.status !== "disabled",
  );
  // What LEKA understood was asked — never what its analysis concluded.
  const objective = intention.understanding?.restated || intention.title || intention.text;
  const agents = offer?.agents ?? [];
  const toggle = (key: string) => {
    const now = chosen ?? agents.filter((a) => a.chosen).map((a) => a.key);
    onChoose(now.includes(key) ? now.filter((k) => k !== key) : [...now, key]);
  };
  return (
    <section className="space-y-4 rounded-2xl p-4 ring-1 ring-shell-line" data-testid="detail-understanding">
      <h2 className="flex items-center gap-2.5 text-[1.0625rem] font-semibold text-brand-navy">
        <Target className="size-5 text-[#f97316]" aria-hidden="true" />
        {w.understanding}
      </h2>
      <div className="grid gap-3 @xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="rounded-xl bg-shell-canvas px-4 py-3">
          <p className="text-[0.8125rem] font-semibold text-brand-navy">{w.objective}</p>
          <p className="mt-1 text-[0.8125rem] text-shell-muted" dir="auto">
            {objective}
          </p>
        </div>
        <div className="rounded-xl bg-shell-canvas px-4 py-3" data-testid="detail-sources">
          <p className="text-[0.8125rem] font-semibold text-brand-navy">{w.sources}</p>
          {shown.length ? (
            <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
              {shown.slice(0, 6).map((source) => (
                <li key={source.id} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                  <SourceLogo kind={source.type as SourceKind} className="size-5" />
                  {source.display_name}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-[0.8125rem] text-shell-muted">{w.noSources}</p>
          )}
        </div>
      </div>
      {agents.length ? (
        <div className="space-y-3" data-testid="detail-agents">
          <div className="flex flex-wrap items-center gap-2.5">
            <Users className="size-5 text-brand-violet" aria-hidden="true" />
            <h3 className="text-[1.0625rem] font-semibold text-brand-navy">{w.agentsTitle}</h3>
            <span className="rounded-md bg-shell-canvas px-2 py-0.5 text-xs text-shell-muted">
              ({fill(w.agentsCount, { count: agents.length })})
            </span>
            {offer?.plan_now === "free" ? (
              <span className="flex items-center gap-1.5 rounded-md bg-brand-violet-soft px-2 py-0.5 text-xs text-brand-violet">
                <Lock className="size-3.5" aria-hidden="true" />
                {w.subscriptionOnly}
              </span>
            ) : null}
          </div>
          <ul className="grid gap-3 @lg:grid-cols-2 @6xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.key}
                agent={agent}
                intention={intention}
                // What the person ticks, at once; the totals follow from the server.
                checked={chosen ? chosen.includes(agent.key) : agent.chosen}
                onToggle={() => toggle(agent.key)}
                included={includedAs(offer, w)}
                filesOf={filesOf}
                onFiles={(list) => onFiles(agent.key, list)}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function AgentCard({
  agent,
  intention,
  checked,
  onToggle,
  included,
  filesOf,
  onFiles,
}: {
  agent: OfferAgent;
  intention: IntentionDetail;
  checked: boolean;
  onToggle: () => void;
  included: string;
  filesOf: (agent: ProposedAgent) => string[];
  onFiles: (files: string[]) => void;
}) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const { format } = useLocale();
  const { proposal } = useProposal(intention);
  const proposed = proposal?.agents.find((a) => a.key === agent.key);
  const drawn = proposed ? proposed.deliverables.filter((d) => DRAWN.has(d)) : [];
  const files = proposed ? filesOf(proposed) : [];
  const Icon = iconOf(agent.category);
  // What it does here: the plan's steps it takes, else what it delivers.
  const bullets = (proposal?.steps ?? []).filter((s) => s.agent === agent.key).map((s) => s.title);
  const shown = bullets.length ? bullets : proposed?.why ? [proposed.why] : [];
  const selectable = agent.status !== "unavailable";
  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-xl p-3 ring-1 ring-shell-line",
        !checked && "opacity-70",
      )}
      data-testid="detail-agent"
      data-key={agent.key}
      data-status={agent.status}
    >
      <div className="flex items-start gap-2.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-brand-violet">
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.875rem] font-semibold text-brand-navy">{agent.title}</p>
          <p className="text-[0.8125rem] text-brand-navy">
            {agent.status === "included" ? (
              <span className="text-state-success">{included}</span>
            ) : agent.status === "owned" ? (
              <span className="text-state-success">{w.owned}</span>
            ) : agent.status === "unavailable" ? (
              <span className="text-state-warning">{w.unavailable}</span>
            ) : agent.monthly_price !== null ? (
              fill(w.perMonth, { price: euros(agent.monthly_price, format) })
            ) : null}
          </p>
        </div>
        <input
          type="checkbox"
          checked={checked}
          disabled={!selectable}
          onChange={onToggle}
          aria-label={fill(w.choose, { name: agent.title })}
          className="mt-1 size-4 accent-brand-violet"
          data-testid="detail-agent-choose"
        />
      </div>
      <p className="text-[0.8125rem] text-shell-muted">
        {summaryOf(t, { key: agent.key, summary: proposed?.summary ?? "" })}
      </p>
      {shown.length ? (
        <ul className="space-y-1">
          {shown.slice(0, 3).map((line) => (
            <li key={line} className="flex items-start gap-1.5 text-[0.8125rem] text-brand-navy">
              <Check className="mt-0.5 size-3.5 shrink-0 text-brand-violet" aria-hidden="true" />
              {line}
            </li>
          ))}
        </ul>
      ) : null}
      {proposed && drawn.length ? (
        // The files it draws beside its report: chosen here, before it runs.
        <fieldset className="space-y-1" data-testid="detail-agent-files">
          <legend className="text-xs font-medium text-brand-navy">{t.intentions.agents.files}</legend>
          <div className="flex flex-wrap gap-4">
            {drawn.map((file) => (
              <label key={file} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                <input
                  type="checkbox"
                  checked={files.includes(file)}
                  disabled={!checked}
                  onChange={(event) =>
                    onFiles(
                      event.target.checked ? [...files, file] : files.filter((f) => f !== file),
                    )
                  }
                  className="size-4 accent-brand-violet"
                  data-testid={`detail-agent-file-${file}`}
                />
                {(t.intentions.agents.deliverables as Record<string, string>)[file] ?? file}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
    </li>
  );
}

// ── the capacity, the offer, the total ─────────────────────────────────────

function CapacityCard({ offer }: { offer: IntentionOffer }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const { format } = useLocale();
  const number = (n: number) => new Intl.NumberFormat(format, { maximumFractionDigits: 0 }).format(n);
  const allowance = offer.plan.credits ?? offer.allowance;
  const share = offer.estimate !== null && allowance ? Math.min(offer.estimate / allowance, 1) : 0;
  return (
    <section
      className="flex flex-wrap items-center gap-4 rounded-2xl bg-[#fff8eb] px-4 py-3 ring-1 ring-[#fde3b3]"
      data-testid="detail-capacity"
    >
      <Gauge className="size-6 text-[#f59e0b]" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[0.9375rem] font-semibold text-brand-navy">{w.capacityTitle}</p>
        <p className="text-[0.8125rem] text-shell-muted">
          {offer.estimate === null
            ? w.capacityUnknown
            : fill(w.capacity, { estimate: number(offer.estimate) })}
          {offer.estimate !== null && !offer.estimate_complete ? ` ${w.capacityPartial}` : ""}
        </p>
        <p className="mt-1 text-xs text-shell-muted" data-testid="detail-capacity-used">
          {fill(w.capacityUsed, { used: number(offer.used), allowance: number(offer.allowance) })}
        </p>
      </div>
      {offer.estimate !== null ? (
        <>
          <div className="h-2.5 w-40 overflow-hidden rounded-full bg-[#fde3b3]" aria-hidden="true">
            <div className="h-full rounded-full bg-brand-violet" style={{ width: `${Math.max(share * 100, 4)}%` }} />
          </div>
          <div className="rounded-xl bg-white px-3 py-2 text-end ring-1 ring-shell-line">
            <p className="text-[0.9375rem] font-semibold text-brand-navy">
              {fill(w.units, { estimate: number(offer.estimate) })}
            </p>
            <p className="text-xs text-shell-muted">{w.estimation}</p>
          </div>
        </>
      ) : null}
    </section>
  );
}

/** The plan and the agents cover it (LEKA-464): said, each agent as it is
 * had, and launched as it is — never a price, a total or a checkout. */
function CoveredCard({
  intention,
  offer,
  proposal,
  filesOf,
}: {
  intention: IntentionDetail;
  offer: IntentionOffer;
  proposal: ProposedAgent[];
  filesOf: (agent: ProposedAgent) => string[];
}) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const router = useRouter();
  const decide = useDecide(intention.id);
  const chosen = proposal.filter((a) => offer.agents.some((o) => o.key === a.key && o.chosen));
  const incomplete = chosen.some((a) => a.missing.length > 0);
  const agents = offer.agents.filter((a) => a.chosen);

  function launch() {
    decide.launch.mutate(
      chosen.map((a) => ({
        key: a.key,
        inputs: a.inputs,
        formats: filesOf(a) as AgentLaunch["formats"],
        sources: [],
      })),
      {
        onSuccess: () => notify.success({ title: w.launched }),
        onError: (error) => notify.error({ title: error instanceof ApiError ? error.message : w.failed }),
      },
    );
  }

  return (
    <section
      className="space-y-3 rounded-2xl bg-[#f0faf3] p-4 ring-1 ring-[#bfe5cb]"
      aria-labelledby="detail-covered-title"
      data-testid="detail-covered"
    >
      <h2 id="detail-covered-title" className="flex items-center gap-2.5 text-[1.0625rem] font-semibold text-brand-navy">
        <CircleCheck className="size-5 text-[#15803d]" aria-hidden="true" />
        {w.coveredBox.title}
      </h2>
      <p className="text-[0.875rem] text-brand-navy">
        {fill(w.coveredBox.body, { plan: planLabel(offer.plan_now) })}
      </p>
      {agents.length ? (
        <ul className="space-y-1" data-testid="detail-covered-agents">
          {agents.map((agent) => (
            <li key={agent.key} className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-brand-navy">
              <Check className="size-3.5 text-[#15803d]" aria-hidden="true" />
              <span className="font-medium">{agent.title}</span>
              <span className="text-shell-muted">
                — {agent.status === "owned" ? w.coveredBox.owned : w.coveredBox.included}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.coveredBox.leka}</p>
      )}
      {incomplete ? (
        <Button
          type="button"
          className="w-full"
          onClick={() => router.push(`${routes.intentions()}/${intention.id}/decision`)}
          data-testid="detail-complete"
        >
          {w.complete}
        </Button>
      ) : (
        <Button
          type="button"
          className="w-full"
          disabled={decide.launch.isPending || !agents.length}
          onClick={launch}
          data-testid="detail-launch"
        >
          {w.launch}
          <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden="true" />
        </Button>
      )}
    </section>
  );
}

function OfferCard({
  intention,
  offer,
  proposal,
  filesOf,
}: {
  intention: IntentionDetail;
  offer: IntentionOffer;
  proposal: ProposedAgent[];
  filesOf: (agent: ProposedAgent) => string[];
}) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const { format } = useLocale();
  const confirm = useConfirm();
  const router = useRouter();
  const decide = useDecide(intention.id);
  const payer = usePermissions()?.includes("workspace:update") ?? false;
  const [busy, setBusy] = useState(false);
  const plan = offer.plan;
  const planLine = offer.lines.find((l) => l.kind === "plan");
  const options = offer.lines.filter((l) => l.kind !== "plan");
  const optionsTotal = options.reduce((sum, l) => sum + l.monthly_price, 0);
  const chosen = proposal.filter((a) => offer.agents.some((o) => o.key === a.key && o.chosen));
  const incomplete = chosen.some((a) => a.missing.length > 0);
  const agentCount = offer.agents.filter((a) => a.chosen).length;
  // What the total pays for: the agents bought, never those the plan includes.
  const paidAgents = options.reduce((n, l) => n + (l.kind === "bundle" ? (l.agents ?? []).length : 1), 0);
  const launchOf = (agents: ProposedAgent[]): AgentLaunch[] =>
    agents.map((a) => ({
      key: a.key,
      inputs: a.inputs,
      formats: filesOf(a) as AgentLaunch["formats"],
      sources: [],
    }));

  async function activate() {
    const steps = [
      planLine
        ? fill(w.confirmPlan, { plan: plan.name, price: euros(planLine.monthly_price, format) })
        : null,
      options.length
        ? fill(w.confirmAgents, {
            step: planLine ? w.confirmStep2 : w.confirmStep1,
            count: options.reduce((n, l) => n + Math.max((l.agents ?? []).length, 1), 0),
            price: euros(optionsTotal, format),
          })
        : null,
    ].filter((s): s is string => Boolean(s));
    const ok = await confirm({
      title: w.confirmTitle,
      description: fill(w.confirmBody, { total: euros(offer.total_monthly, format) }),
      impact: steps,
      confirmLabel: w.confirm,
    });
    if (!ok) return;
    setBusy(true);
    try {
      if (planLine) {
        const opened = await subscription.checkout(plan.key, "month", intention.id);
        window.location.assign(opened.url);
        return;
      }
      const agents = options.flatMap((l) => l.agents ?? []);
      const bundle = options.find((l) => l.kind === "bundle");
      const opened = await billing.buy(
        bundle
          ? { kind: "bundle", key: bundle.key, intention_id: intention.id, launch: launchOf(chosen) }
          : agents.length > 1
            ? { kind: "agents", key: agents.join(","), intention_id: intention.id, launch: launchOf(chosen) }
            : { kind: "agent", key: agents[0] ?? "", intention_id: intention.id, launch: launchOf(chosen) },
      );
      window.location.assign(opened.url);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
      setBusy(false);
    }
  }

  function launch() {
    decide.launch.mutate(launchOf(chosen), {
      onSuccess: () => notify.success({ title: w.launched }),
      onError: (error) => notify.error({ title: error instanceof ApiError ? error.message : w.failed }),
    });
  }

  const features = plan.contractual
    ? [w.contract]
    : [
        plan.users ? fill(w.users, { count: plan.users }) : null,
        plan.sources ? fill(w.sourcesQuota, { count: plan.sources }) : null,
        plan.credits ? fill(w.credits, { count: new Intl.NumberFormat(format).format(plan.credits) }) : null,
        plan.analyses ? fill(w.analyses, { count: new Intl.NumberFormat(format).format(plan.analyses) }) : null,
        plan.runs_agents ? w.specialised : null,
      ].filter((f): f is string => Boolean(f));
  const parts = [
    planLine ? w.partPlan : null,
    paidAgents ? fill(w.partAgents, { count: paidAgents }) : null,
  ].filter(Boolean);

  return (
    <section
      className="space-y-4 rounded-2xl p-4 ring-2 ring-brand-violet/25"
      aria-labelledby="detail-offer-title"
      data-testid="detail-offer"
    >
      <h2 id="detail-offer-title" className="flex items-center gap-2.5 text-[1.0625rem] font-semibold text-brand-navy">
        <Sparkles className="size-5 text-brand-violet" aria-hidden="true" />
        {offer.change_plan ? w.offerTitle : w.offerCurrent}
        {offer.provisional ? (
          <span className="rounded-md bg-shell-canvas px-2 py-0.5 text-xs font-normal text-shell-muted">
            {w.provisional}
          </span>
        ) : null}
      </h2>
      <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="relative rounded-xl px-4 pt-6 pb-4 ring-1 ring-brand-violet/40" data-testid="detail-plan">
          {offer.change_plan ? (
            <span className="absolute -top-3 left-4 rounded-md bg-brand-violet px-2.5 py-0.5 text-xs font-semibold text-white">
              {w.recommended}
            </span>
          ) : null}
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[1.5rem] font-bold text-brand-navy">{plan.name}</p>
              <p className="text-[0.8125rem] text-shell-muted">{w.fits}</p>
            </div>
            {plan.monthly_price !== null ? (
              <p className="text-end">
                <span className="text-[1.75rem] font-bold text-brand-navy">{euros(plan.monthly_price, format)}</span>
                <span className="text-[0.9375rem] text-brand-navy"> / mois</span>
                <span className="block text-xs text-shell-muted">{w.ht}</span>
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <ul className="space-y-1">
            {features.map((feature) => (
              <li key={feature} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                <Check className="size-3.5 text-brand-violet" aria-hidden="true" />
                {feature}
              </li>
            ))}
          </ul>
          <Link
            href={routes.billingPlans()}
            className={buttonVariants({ variant: "outline", size: "sm" })}
            data-testid="detail-all-plans"
          >
            {w.allPlans}
            <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
          </Link>
        </div>
      </div>
      <div className="grid gap-4 @5xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="rounded-xl p-4 ring-1 ring-shell-line" data-testid="detail-summary">
          <p className="mb-2 text-[0.875rem] font-semibold text-brand-navy">{w.summary}</p>
          <ul className="grid gap-x-8 gap-y-1.5 @2xl:grid-cols-2">
            {offer.lines.map((line) => (
              <li key={`${line.kind}:${line.key}`} className="text-[0.8125rem]" data-testid="detail-line">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-brand-navy">
                    {line.kind === "plan" ? fill(w.subscriptionLine, { plan: line.label }) : line.label}
                  </span>
                  <span className="font-semibold whitespace-nowrap text-brand-navy">
                    {fill(w.perMonth, { price: euros(line.monthly_price, format) })}
                  </span>
                </div>
                {/* Which right is missing, said beside what it costs (LEKA-464). */}
                <p className="text-xs text-shell-muted" data-testid="detail-line-why">
                  {line.kind === "plan"
                    ? fill(
                        offer.blocked === "credits_exhausted"
                          ? w.why.planCredits
                          : offer.plan_now === "free"
                            ? w.why.planAgents
                            : w.why.planCapacity,
                        { plan: planLabel(offer.plan_now) },
                      )
                    : fill(w.why.agent, { plan: plan.name })}
                </p>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl bg-brand-violet-soft/40 p-4" data-testid="detail-total">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-[0.875rem] font-semibold text-brand-navy">{w.totalTitle}</p>
              <p className="text-[1.75rem] font-bold text-brand-navy">
                {fill(w.totalNow, { price: euros(offer.total_monthly, format) })}
              </p>
              {parts.length ? <p className="text-xs text-shell-muted">{parts.join(" + ")}</p> : null}
            </div>
            {offer.lines.length ? (
              <span className="rounded-md bg-[#e6f6ec] px-2 py-1 text-xs font-medium text-[#15803d]">
                {w.allIncluded}
              </span>
            ) : null}
          </div>
          {planLine?.then_monthly && planLine.for_months ? (
            <p className="mt-1 text-xs text-shell-muted" data-testid="detail-then">
              {fill(w.then, {
                price: euros(offer.then_monthly ?? planLine.then_monthly, format),
                months: planLine.for_months,
                percent: Math.round(100 * (1 - planLine.monthly_price / planLine.then_monthly)),
              })}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-shell-muted">{w.renewal}</p>
          {planLine && plan.trial_days ? (
            <p className="text-xs text-shell-muted">{fill(w.trial, { days: plan.trial_days })}</p>
          ) : null}
          <div className="mt-3">
            {/* An agent still waiting on its information: completed first, at
                the decision — never paid for to be refused once paid. */}
            {incomplete ? (
              <Button
                type="button"
                className="w-full"
                onClick={() => router.push(`${routes.intentions()}/${intention.id}/decision`)}
                data-testid="detail-complete"
              >
                {w.complete}
              </Button>
            ) : offer.ready ? (
              <Button
                type="button"
                className="w-full"
                disabled={decide.launch.isPending || !agentCount}
                onClick={launch}
                data-testid="detail-launch"
              >
                {w.launch}
                <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden="true" />
              </Button>
            ) : payer && !(plan.contractual && offer.change_plan) ? (
              <Button
                type="button"
                className="h-auto min-h-10 w-full py-2.5 whitespace-normal"
                disabled={busy}
                onClick={() => void activate()}
                data-testid="detail-activate"
              >
                {w.activate}
                <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden="true" />
              </Button>
            ) : (
              <p className="text-[0.8125rem] text-shell-muted">{w.askAdmin}</p>
            )}
            <p className="mt-2 flex items-center justify-center gap-1.5 text-xs text-shell-muted">
              <Lock className="size-3" aria-hidden="true" />
              {w.secure}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── beside it: the plan, what it reaches, what it delivers ────────────────

type Tab = "plan" | "result" | "sources" | "technical";

function SidePanel({ intention, offer }: { intention: IntentionDetail; offer: IntentionOffer | undefined }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const [tab, setTab] = useState<Tab>("plan");
  const tabs: Tab[] = ["plan", "result", "sources", "technical"];
  return (
    <aside className="@container min-w-0 space-y-4" aria-label={w.tabs.plan}>
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-shell-line">
        {/* Narrow (a phone): the tabs go on two lines, never cut. */}
        <div role="tablist" className="mb-4 flex flex-wrap justify-between gap-x-2 border-b border-shell-line">
          {tabs.map((each) => (
            <button
              key={each}
              type="button"
              role="tab"
              aria-selected={tab === each}
              onClick={() => setTab(each)}
              className={cn(
                "-mb-px border-b-2 px-2 py-2 text-[0.8125rem] font-medium whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40",
                tab === each
                  ? "border-brand-violet text-brand-violet"
                  : "border-transparent text-shell-muted hover:text-brand-navy",
              )}
              data-testid={`detail-tab-${each}`}
            >
              {w.tabs[each]}
            </button>
          ))}
        </div>
        {tab === "plan" ? (
          <PlanSteps intention={intention} offer={offer} />
        ) : tab === "result" ? (
          <AnalysisResults intention={intention} />
        ) : tab === "sources" ? (
          <EvidenceTab intention={intention} />
        ) : (
          <TechnicalLinks intention={intention} />
        )}
      </div>
      <Dependencies intention={intention} onAll={() => setTab("result")} />
      <Expected intention={intention} />
    </aside>
  );
}

function PlanSteps({ intention, offer }: { intention: IntentionDetail; offer: IntentionOffer | undefined }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const { format } = useLocale();
  const { proposal } = useProposal(intention);
  const steps = proposal?.steps ?? [];
  if (!steps.length) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.planNone}</p>;
  }
  return (
    <section data-testid="detail-plan-steps">
      <h2 className="mb-3 flex items-center gap-2 text-[1rem] font-semibold text-brand-navy">
        <Workflow className="size-5 text-brand-navy" aria-hidden="true" />
        {w.planTitle}
      </h2>
      <ol className="space-y-4">
        {steps.map((step, index) => {
          const agent = step.agent ? offer?.agents.find((a) => a.key === step.agent) : undefined;
          const proposed = step.agent ? proposal?.agents.find((a) => a.key === step.agent) : undefined;
          const Icon = agent ? iconOf(agent.category) : Sparkles;
          const bullets = step.detail
            .split(/(?<=[.;])\s+|\n/)
            .map((b) => b.replace(/[.;]$/, "").trim())
            .filter(Boolean);
          return (
            <li key={`${index}:${step.title}`} className="flex gap-3" data-testid="detail-plan-step">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-[0.875rem] font-semibold text-brand-navy ring-1 ring-shell-line">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[0.875rem] font-semibold text-brand-navy">{step.title}</p>
                {bullets.length ? (
                  <ul className="mt-0.5 list-disc space-y-0.5 ps-4 text-[0.8125rem] text-shell-muted">
                    {bullets.slice(0, 3).map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div className="flex w-36 shrink-0 items-center gap-2 self-start rounded-lg bg-shell-canvas px-2.5 py-2">
                <Icon className="size-5 shrink-0 text-brand-violet" aria-hidden="true" />
                <div className="min-w-0 text-xs">
                  <p className="truncate font-medium text-brand-navy">
                    {agent?.title ?? proposed?.title ?? w.assistant}
                  </p>
                  <p className="text-shell-muted">
                    {agent
                      ? agent.status === "included"
                        ? includedAs(offer, w)
                        : agent.status === "owned"
                          ? w.owned
                          : agent.status !== "unavailable" && agent.monthly_price !== null
                            ? fill(w.perMonth, { price: euros(agent.monthly_price, format) })
                            : w.unavailable
                      : w.assistantIncluded}
                  </p>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Dependencies({ intention, onAll }: { intention: IntentionDetail; onAll: () => void }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const analysis = useIntentionAnalysis(intention.id, () => false);
  const result = analysis.data?.current ? analysis.data.result : null;
  const areas = t.intentions.analysis.areas as Record<string, string>;
  const items = useMemo(
    () =>
      (result?.impact ?? []).flatMap((area) =>
        area.items.map((item) => ({ ...item, area: areas[area.code] ?? area.code })),
      ),
    [result, areas],
  );
  if (!items.length) return null;
  const tone =
    result?.risk === "high" ? "text-state-danger" : result?.risk === "medium" ? "text-state-warning" : "text-state-success";
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-shell-line" data-testid="detail-dependencies">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[1rem] font-semibold text-brand-navy">
          <Network className="size-5" aria-hidden="true" />
          {w.dependencies} <span className="text-[0.8125rem] font-normal text-shell-muted">{w.extract}</span>
        </h2>
        <button type="button" onClick={onAll} className="text-[0.8125rem] font-medium text-brand-violet hover:underline">
          {fill(w.seeAll, { count: items.length })}
        </button>
      </div>
      <ul className="divide-y divide-shell-line/70">
        {items.slice(0, 5).map((item) => (
          <li key={`${item.area}:${item.ref_id}`} className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] items-center gap-2 py-2 text-[0.8125rem]">
            <Link href={entityHref({ id: item.ref_id, type: item.ref_type })} className="truncate font-medium text-brand-navy hover:underline">
              {item.name}
            </Link>
            <span className={cn("truncate text-xs", tone)}>{item.area}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Expected({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const deliverables = t.intentions.agents.deliverables as Record<string, string>;
  const { proposal } = useProposal(intention);
  const steps = proposal?.steps ?? [];
  const files = [...new Set((proposal?.agents ?? []).flatMap((a) => a.deliverables))];
  if (!steps.length && !files.length) return null;
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-shell-line" data-testid="detail-expected">
      <h2 className="mb-3 flex items-center gap-2 text-[1rem] font-semibold text-brand-navy">
        <FileText className="size-5" aria-hidden="true" />
        {w.expected}
      </h2>
      <div className="flex flex-wrap items-start gap-4">
        <ul className="min-w-0 flex-1 space-y-1.5">
          {steps.map((step) => (
            <li key={step.title} className="flex items-start gap-2 text-[0.8125rem] text-brand-navy">
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand-violet" aria-hidden="true" />
              {step.title}
            </li>
          ))}
        </ul>
        {files.length ? (
          <div className="w-44 rotate-[-3deg] rounded-xl bg-white p-3 shadow-md ring-1 ring-shell-line" aria-hidden="true">
            <p className="mb-2 text-xs font-semibold text-brand-navy">{w.report}</p>
            <ul className="space-y-1">
              {files.map((file) => (
                <li key={file} className="flex items-center gap-1.5 text-[0.6875rem] text-shell-muted">
                  <FileText className="size-3 text-brand-violet" />
                  {deliverables[file] ?? file}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function TechnicalLinks({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.detail;
  const views = ["overview", "analysis", "results", "decision", "actions", "history", "evidence"] as const;
  return (
    <section className="space-y-2" data-testid="detail-technical">
      <p className="text-[0.8125rem] text-shell-muted">{w.technicalLead}</p>
      <ul className="grid gap-1.5 @md:grid-cols-2">
        {views.map((view) => (
          <li key={view}>
            <Link
              href={`${routes.intentions()}/${intention.id}/${view}`}
              className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-[0.8125rem] font-medium text-brand-navy ring-1 ring-shell-line hover:bg-shell-canvas"
              data-testid={`tab-${view}`}
            >
              {w.steps[view]}
              <ArrowRight className="size-3.5 text-shell-muted rtl:-scale-x-100" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
