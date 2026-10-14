"use client";

import { Bot, Check, ClipboardCopy, Download, ListChecks, Rocket, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { cn } from "cn";

import { Card, IconTile } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { AgentWork } from "@/components/intentions/agent-work";
import { useRights } from "@/components/intentions/journey";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type {
  AgentLaunch,
  AgentProposal,
  IntentionDetail,
  ProposedAgent,
} from "@/lib/intentions/api";
import { may } from "@/lib/intentions/journey";
import { useDecide, useIntentionAnalysis } from "@/lib/intentions/queries";
import { notify } from "@/lib/notify";
import { useSources } from "@/lib/sources-queries";

/**
 * What LEKA proposes to get a request done, and the person's decision
 * (2026-10-14, the product call: « il faut que j'aie la possibilité de
 * demander un agent après le résultat », « les 5 ronds doivent être
 * utilisés »):
 *
 * - Résultat: the plan, step by step, and the agents it takes — what each
 *   does, why here, what it would deliver, what a run costs, whether it can
 *   run here;
 * - Décision: « Lancer avec ces agents » — the person ticks them, completes
 *   what they lack, chooses the files to produce — or « Je le fais
 *   moi-même », the plan in hand. LEKA starts nothing on its own;
 * - Action: the agents at work, a failed one launched again; or the plan,
 *   ticked off as it is done, to download.
 */

const DRAWN = new Set(["pdf", "pptx"]);

function stepHref(id: string, step: "decision" | "actions") {
  return `${routes.intentions()}/${id}/${step}`;
}

/** What its current analysis proposed — none before one, or of an earlier
 * version. */
export function useProposal(intention: IntentionDetail): {
  proposal: AgentProposal | null;
  loading: boolean;
} {
  const analysis = useIntentionAnalysis(intention.id, () => false);
  const data = analysis.data;
  return {
    proposal: data?.current ? (data.result?.proposal ?? null) : null,
    loading: data === undefined,
  };
}

function DeliverableChips({ agent }: { agent: ProposedAgent }) {
  const w = useDictionary().intentions.agents;
  const said = w.deliverables as Record<string, string>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {agent.deliverables.map((d) => (
        <Pill key={d} tone="neutral">
          {said[d] ?? d}
        </Pill>
      ))}
    </span>
  );
}

function Cost({ agent }: { agent: ProposedAgent }) {
  const w = useDictionary().intentions.agents;
  return (
    <span className="text-xs text-shell-muted">
      {agent.credits !== null && agent.credits !== undefined
        ? fill(w.credits, { count: Math.ceil(agent.credits) })
        : w.creditsUnknown}
    </span>
  );
}

function Why({ agent }: { agent: ProposedAgent }) {
  const w = useDictionary().intentions.agents;
  const reasons = w.reasons as Record<string, string>;
  if (agent.available) return null;
  const said = [...new Set(agent.reasons.map((r) => reasons[r] ?? r))];
  return (
    <p className="text-xs text-state-warning" data-testid="proposed-agent-why-not">
      {said.join(" · ")}
    </p>
  );
}

function AgentLine({ agent }: { agent: ProposedAgent }) {
  const w = useDictionary().intentions.agents;
  return (
    <li
      className="flex gap-3 border-t border-shell-line py-3 first:border-t-0 first:pt-0 last:pb-0"
      data-testid="proposed-agent"
      data-key={agent.key}
    >
      <IconTile icon={Bot} tone="violet" className="size-10" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="text-[0.9375rem] font-semibold text-brand-navy">{agent.title}</span>
          <Pill tone={agent.available ? "success" : "warning"}>
            {agent.available ? w.ready : w.unavailable}
          </Pill>
        </p>
        <p className="text-[0.8125rem] text-shell-muted">{agent.summary}</p>
        {agent.why ? <p className="text-[0.8125rem] text-brand-navy">{agent.why}</p> : null}
        <Why agent={agent} />
        <div className="flex flex-wrap items-center gap-3 pt-0.5">
          <DeliverableChips agent={agent} />
          <Cost agent={agent} />
        </div>
      </div>
    </li>
  );
}

/** The plan, step by step: who does each — an agent, or the person. */
export function PlanSteps({ proposal }: { proposal: AgentProposal }) {
  const w = useDictionary().intentions.agents;
  const titles = new Map(proposal.agents.map((a) => [a.key, a.title]));
  return (
    <ol className="space-y-3" data-testid="plan-steps">
      {proposal.steps.map((step, i) => (
        <li key={`${i}-${step.title}`} className="flex gap-3" data-testid="plan-step">
          <span
            className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-violet-soft text-[0.8125rem] font-semibold text-brand-violet"
            aria-hidden="true"
          >
            {i + 1}
          </span>
          <div className="min-w-0">
            <p className="text-[0.9375rem] font-medium text-brand-navy">{step.title}</p>
            {step.detail ? (
              <p className="text-[0.8125rem] text-shell-muted">{step.detail}</p>
            ) : null}
            <p className="mt-0.5 flex items-center gap-1 text-xs text-shell-muted">
              {step.agent ? (
                <Bot className="size-3.5" aria-hidden="true" />
              ) : (
                <UserRound className="size-3.5" aria-hidden="true" />
              )}
              {step.agent
                ? fill(w.byAgent, { agent: titles.get(step.agent) ?? step.agent })
                : w.byYou}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Résultat: the plan and the agents it takes, then the way to decide. */
export function ProposalView({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.agents;
  const rights = useRights(intention);
  const { proposal } = useProposal(intention);
  if (!proposal) return null;
  const deciding =
    may(intention.journey, "launch_agents", rights) || may(intention.journey, "by_hand", rights);
  return (
    <div className="grid gap-4 xl:grid-cols-2" data-testid="intention-proposal">
      <Card title={w.planTitle} icon={<ListChecks className="size-4 text-shell-muted" aria-hidden="true" />}>
        <PlanSteps proposal={proposal} />
      </Card>
      <Card title={w.agentsTitle} icon={<Bot className="size-4 text-shell-muted" aria-hidden="true" />}>
        {proposal.agents.length ? (
          <ul>
            {proposal.agents.map((agent) => (
              <AgentLine key={agent.key} agent={agent} />
            ))}
          </ul>
        ) : (
          <p className="text-[0.8125rem] text-shell-muted" data-testid="proposal-no-agent">
            {w.noAgent}
          </p>
        )}
        {deciding && intention.status === "awaiting_decision" ? (
          <Link
            href={stepHref(intention.id, "decision")}
            className={buttonVariants({ className: "mt-4 w-full" })}
            data-testid="results-to-decision"
          >
            {w.toDecision}
          </Link>
        ) : null}
      </Card>
    </div>
  );
}

type Choice = {
  on: boolean;
  inputs: Record<string, string>;
  formats: string[];
  sources: string[];
};
type Readable = { id: string; name: string };

function initial(agent: ProposedAgent): Choice {
  const inputs: Record<string, string> = {};
  for (const field of agent.fields ?? []) {
    const said = agent.inputs[field.name];
    if (typeof said === "string") inputs[field.name] = said;
  }
  return { on: agent.available, inputs, formats: [...agent.asked], sources: [] };
}

function ChosenAgent({
  agent,
  choice,
  onChange,
  readable,
}: {
  agent: ProposedAgent;
  choice: Choice;
  onChange: (next: Choice) => void;
  readable: Readable[];
}) {
  const w = useDictionary().intentions.agents;
  const said = w.deliverables as Record<string, string>;
  const drawn = agent.deliverables.filter((d) => DRAWN.has(d));
  const needed = (agent.fields ?? []).filter(
    (f) => f.required && f.type !== "boolean" && (agent.missing.includes(f.name) || choice.on),
  );
  return (
    <li className="space-y-2 rounded-lg border border-shell-line p-3" data-testid="decide-agent" data-key={agent.key}>
      <label className="flex items-start gap-2.5">
        <Checkbox
          checked={choice.on}
          disabled={!agent.available}
          onCheckedChange={(on) => onChange({ ...choice, on: Boolean(on) })}
          data-testid="decide-agent-on"
          className="mt-0.5"
        />
        <span className="min-w-0">
          <span className="block text-[0.9375rem] font-semibold text-brand-navy">{agent.title}</span>
          <span className="block text-[0.8125rem] text-shell-muted">{agent.summary}</span>
          <Why agent={agent} />
        </span>
      </label>
      {choice.on && needed.length ? (
        <div className="space-y-2 ps-6">
          {needed.map((field) => {
            const value = choice.inputs[field.name] ?? "";
            return (
              <label key={field.name} className="block space-y-1">
                <span className="flex items-center gap-2 text-xs font-medium text-brand-navy">
                  {field.description || field.name}
                  {!value.trim() ? <Pill tone="warning">{w.complete}</Pill> : null}
                </span>
                <Input
                  value={value}
                  onChange={(event) =>
                    onChange({ ...choice, inputs: { ...choice.inputs, [field.name]: event.target.value } })
                  }
                  data-testid={`decide-input-${field.name}`}
                />
              </label>
            );
          })}
        </div>
      ) : null}
      {choice.on && drawn.length ? (
        <fieldset className="space-y-1.5 ps-6">
          <legend className="text-xs font-medium text-brand-navy">{w.files}</legend>
          <div className="flex flex-wrap gap-4">
            {drawn.map((format) => (
              <label key={format} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                <Checkbox
                  checked={choice.formats.includes(format)}
                  onCheckedChange={(on) =>
                    onChange({
                      ...choice,
                      formats: on
                        ? [...choice.formats, format]
                        : choice.formats.filter((f) => f !== format),
                    })
                  }
                  data-testid={`decide-format-${format}`}
                />
                {said[format] ?? format}
              </label>
            ))}
          </div>
          <p className="text-xs text-shell-muted">{w.filesHint}</p>
        </fieldset>
      ) : null}
      {/* Kept to some sources — « l'Architecte sur Confluence seul »
          (2026-10-14): none ticked, every one. */}
      {choice.on && readable.length > 1 ? (
        <fieldset className="space-y-1.5 ps-6" data-testid="decide-sources">
          <legend className="text-xs font-medium text-brand-navy">{w.sourcesTitle}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {readable.map((source) => (
              <label key={source.id} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                <Checkbox
                  checked={choice.sources.includes(source.id)}
                  onCheckedChange={(on) =>
                    onChange({
                      ...choice,
                      sources: on
                        ? [...choice.sources, source.id]
                        : choice.sources.filter((id) => id !== source.id),
                    })
                  }
                />
                {source.name}
              </label>
            ))}
          </div>
          <p className="text-xs text-shell-muted">{w.sourcesHint}</p>
        </fieldset>
      ) : null}
    </li>
  );
}

function launchError(t: ReturnType<typeof useDictionary>, error: unknown): string {
  const said = t.intentions.agents.errors as Record<string, string>;
  if (error instanceof ApiError && error.code && said[error.code]) return said[error.code];
  return said.default;
}

/** Décision: « Lancer avec ces agents », or « Je le fais moi-même ». */
export function AgentsDecision({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.agents;
  const router = useRouter();
  const rights = useRights(intention);
  const decide = useDecide(intention.id);
  const { proposal, loading } = useProposal(intention);
  const sources = useSources();
  const readable: Readable[] = (sources.data ?? [])
    .filter((source) => source.status === "active" || source.status === "degraded")
    .map((source) => ({ id: source.id, name: source.display_name }));
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  useEffect(() => {
    if (!proposal) return;
    setChoices(Object.fromEntries(proposal.agents.map((a) => [a.key, initial(a)])));
  }, [proposal]);

  const launchable = may(intention.journey, "launch_agents", rights);
  const handable = may(intention.journey, "by_hand", rights);
  if (!launchable && !handable) {
    const path = intention.journey.path;
    if (!path) return null;
    return (
      <p className="rounded-xl border border-shell-line bg-white px-5 py-4 text-[0.875rem] text-brand-navy" data-testid="decided">
        {fill(w.decided, { way: path === "agents" ? w.wayAgents : w.waySelf })}
      </p>
    );
  }
  if (loading) return <div className="h-40 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  const agents = proposal?.agents ?? [];
  const informative = proposal?.informative ?? false;
  const chosen = agents.filter((a) => choices[a.key]?.on);
  const incomplete = chosen.some((a) =>
    (a.fields ?? []).some(
      (f) => f.required && f.type !== "boolean" && !(choices[a.key]?.inputs[f.name] ?? "").trim(),
    ),
  );
  const pending = decide.launch.isPending || decide.byHand.isPending;

  function launch() {
    const list: AgentLaunch[] = chosen.map((a) => {
      const choice = choices[a.key];
      const inputs: Record<string, string | boolean> = { ...a.inputs };
      for (const [name, value] of Object.entries(choice.inputs)) {
        if (value.trim()) inputs[name] = value.trim();
      }
      return {
        key: a.key,
        inputs,
        formats: choice.formats as AgentLaunch["formats"],
        sources: choice.sources,
      };
    });
    decide.launch.mutate(list, {
      onSuccess: () => {
        notify.success({ title: w.launched });
        router.push(stepHref(intention.id, "actions"));
      },
      onError: (error) => notify.error({ title: launchError(t, error) }),
    });
  }

  function byHand() {
    decide.byHand.mutate(undefined, {
      onSuccess: () => {
        notify.success({ title: w.selfDone });
        router.push(stepHref(intention.id, "actions"));
      },
      onError: (error) =>
        notify.error({ title: error instanceof ApiError ? error.message : String(error) }),
    });
  }

  return (
    <section className="space-y-3" aria-labelledby="agents-decision-title" data-testid="agents-decision">
      <div>
        <h2 id="agents-decision-title" className="text-[1.0625rem] font-semibold text-brand-navy">
          {w.decideTitle}
        </h2>
        <p className="text-[0.8125rem] text-shell-muted">{w.decideLead}</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div
          className={cn(
            "flex flex-col gap-3 rounded-xl border bg-white p-4",
            agents.length ? "border-brand-violet/40" : "border-shell-line",
          )}
          data-testid="decide-agents"
        >
          <div className="flex items-center gap-3">
            <IconTile icon={Rocket} tone="violet" className="size-10" />
            <div>
              <h3 className="text-[1rem] font-semibold text-brand-navy">
                {informative ? w.furtherTitle : w.launchTitle}
              </h3>
              <p className="text-[0.8125rem] text-shell-muted">
                {informative ? w.furtherBody : w.launchBody}
              </p>
            </div>
          </div>
          {agents.length ? (
            <ul className="space-y-2">
              {agents.map((agent) => (
                <ChosenAgent
                  key={agent.key}
                  agent={agent}
                  choice={choices[agent.key] ?? initial(agent)}
                  onChange={(next) => setChoices((all) => ({ ...all, [agent.key]: next }))}
                  readable={readable}
                />
              ))}
            </ul>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.noAgent}</p>
          )}
          <div className="mt-auto space-y-1.5">
            <Button
              type="button"
              className="w-full"
              disabled={!launchable || !chosen.length || incomplete || pending}
              onClick={launch}
              data-testid="decide-launch"
            >
              <Rocket className="size-4" aria-hidden="true" />
              {w.launch}
            </Button>
            {agents.length && !chosen.length ? (
              <p className="text-xs text-shell-muted">{w.chooseOne}</p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4" data-testid="decide-self">
          <div className="flex items-center gap-3">
            <IconTile icon={UserRound} tone="neutral" className="size-10" />
            <div>
              <h3 className="text-[1rem] font-semibold text-brand-navy">
                {informative ? w.stopTitle : w.selfTitle}
              </h3>
              <p className="text-[0.8125rem] text-shell-muted">
                {informative ? w.stopBody : w.selfBody}
              </p>
            </div>
          </div>
          {proposal?.steps.length ? <PlanSteps proposal={proposal} /> : null}
          <Button
            type="button"
            variant="outline"
            className="mt-auto w-full"
            disabled={!handable || pending}
            onClick={byHand}
            data-testid="decide-by-hand"
          >
            {informative ? w.stop : w.self}
          </Button>
        </div>
      </div>
    </section>
  );
}

const KEPT = "leka.plan.";

function markdownOf(intention: IntentionDetail, proposal: AgentProposal, byYou: string): string {
  const titles = new Map(proposal.agents.map((a) => [a.key, a.title]));
  return [
    `# ${intention.title}`,
    "",
    ...(intention.summary ? [intention.summary, ""] : []),
    ...proposal.steps.map(
      (s, i) =>
        `${i + 1}. **${s.title}**${s.detail ? ` — ${s.detail}` : ""} (${
          s.agent ? (titles.get(s.agent) ?? s.agent) : byYou
        })`,
    ),
    "",
  ].join("\n");
}

/** Action, done by hand: the plan, ticked off as it is done — kept in this
 * browser — to download or copy. */
export function PlanChecklist({ intention }: { intention: IntentionDetail }) {
  const w = useDictionary().intentions.agents;
  const { proposal } = useProposal(intention);
  const [done, setDone] = useState<number[]>([]);
  useEffect(() => {
    try {
      const kept = window.localStorage.getItem(KEPT + intention.id);
      if (kept) setDone(JSON.parse(kept) as number[]);
    } catch {
      // Private window, storage refused: ticked for this visit only.
    }
  }, [intention.id]);
  const text = useMemo(
    () => (proposal ? markdownOf(intention, proposal, w.byYou) : ""),
    [intention, proposal, w.byYou],
  );
  if (!proposal) return null;

  function tick(i: number, on: boolean) {
    const next = on ? [...new Set([...done, i])] : done.filter((d) => d !== i);
    setDone(next);
    try {
      window.localStorage.setItem(KEPT + intention.id, JSON.stringify(next));
    } catch {
      // Kept for this visit only.
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `plan-${intention.id.slice(0, 8)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      notify.success({ title: w.copied });
    } catch {
      // The clipboard refused: the download stays.
    }
  }

  return (
    <Card
      title={w.checklistTitle}
      icon={<ListChecks className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" onClick={download} data-testid="plan-download">
            <Download className="size-3.5" aria-hidden="true" />
            {w.download}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => void copy()} data-testid="plan-copy">
            <ClipboardCopy className="size-3.5" aria-hidden="true" />
            {w.copy}
          </Button>
        </div>
      }
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.checklistLead}</p>
      <ol className="space-y-2" data-testid="plan-checklist">
        {proposal.steps.map((step, i) => (
          <li key={`${i}-${step.title}`}>
            <label className="flex items-start gap-2.5">
              <Checkbox
                checked={done.includes(i)}
                onCheckedChange={(on) => tick(i, Boolean(on))}
                className="mt-0.5"
                data-testid="plan-check"
              />
              <span className={cn("min-w-0", done.includes(i) && "text-shell-muted line-through")}>
                <span className="block text-[0.9375rem] font-medium">{step.title}</span>
                {step.detail ? <span className="block text-[0.8125rem]">{step.detail}</span> : null}
              </span>
              {done.includes(i) ? <Check className="ms-auto size-4 text-state-success" aria-hidden="true" /> : null}
            </label>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Action, by its agents: their work as it goes, a failed one launched
 * again. */
export function AgentsAction({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.agentWork;
  const rights = useRights(intention);
  const decide = useDecide(intention.id);
  const retryable = may(intention.journey, "retry_agents", rights);
  return (
    <div className="space-y-3" data-testid="agents-action">
      <AgentWork intentionId={intention.id} live={intention.journey.by === "leka"} />
      {retryable ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-state-danger/30 bg-white px-4 py-3">
          <p className="min-w-0 flex-1 text-[0.8125rem] text-brand-navy">{w.failedSaid}</p>
          <Button
            type="button"
            disabled={decide.retry.isPending}
            onClick={() =>
              decide.retry.mutate(undefined, {
                onSuccess: () => notify.success({ title: w.retried }),
                onError: (error) => notify.error({ title: launchError(t, error) }),
              })
            }
            data-testid="agents-retry"
          >
            {w.retry}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
