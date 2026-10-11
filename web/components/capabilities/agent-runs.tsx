"use client";

import { Ban, Download, Play, Workflow } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { TileTone } from "@/components/environment/parts";
import {
  ACTIVE,
  type AgentRun,
  type AgentRunDetail,
  type AgentRunEvent,
  type RunInputs,
} from "@/lib/agent-runs";
import { useAgentRun, useAgentRunChange, useAgentRuns } from "@/lib/agent-runs-queries";
import { ApiError, apiAddress } from "@/lib/api";
import type { CapabilityDetail } from "@/lib/capabilities";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * An agent, run (LEKA-395): given what its contract takes, then followed —
 * queued, running, done or failed and why — what it delivered, every step
 * it took: its context, each tool it called and what came of it, what its
 * model calls cost. Its instructions stay on the server.
 */

const STATUS_TONE: Record<string, TileTone> = {
  awaiting_approval: "warning",
  queued: "neutral",
  running: "info",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};

type Field = CapabilityDetail["inputs"][number];
type Values = Record<string, string | boolean>;

/** A field as people read it: the dictionary's name for it, else its own,
 * made readable ("vue_applicative" → "Vue applicative"). */
export function fieldLabel(t: Dictionary, name: string): string {
  const known = (t.agentRuns.fields as Record<string, string>)[name];
  if (known) return known;
  const spaced = name.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const STOP = String.raw`(?=\s+(?:sur|pour|dans|avec|et)\s+(?:le|la|les|l')|[,.;:!?»"]|$)`;
const SAID: Record<string, RegExp> = {
  parcours: new RegExp(String.raw`parcours\s+(?:de\s+|du\s+|d'|«\s*)?(.+?)\s*` + STOP, "i"),
  perimetre: new RegExp(
    String.raw`p[ée]rim[èe]tre\s+(?:de\s+|du\s+|d'|«\s*)?(.+?)\s*` + STOP,
    "i",
  ),
};

/** What an intention already says of what an agent takes — « Construis
 * l'architecture du parcours Paiement CB sur le périmètre Digital » gives
 * the journey and the perimeter; the journey, at least, its title. Only a
 * suggestion: the person reads it and changes it before running. */
export function suggestedInputs(
  fields: Field[],
  intention: { title: string; text: string } | undefined,
): Values {
  if (!intention) return {};
  const said: Values = {};
  const words = `${intention.title}. ${intention.text}`;
  for (const field of fields) {
    if (field.type === "boolean") {
      if (field.name === "vue_applicative" && /vue\s+applicative/i.test(words)) said[field.name] = true;
      continue;
    }
    const found = SAID[field.name]?.exec(words);
    if (found?.[1]) said[field.name] = found[1].trim();
  }
  if (fields.some((f) => f.name === "parcours") && !said.parcours && intention.title.trim()) {
    said.parcours = intention.title.trim();
  }
  return said;
}

/** What the form holds, as the contract takes it: an empty optional left out. */
export function inputsOf(fields: Field[], values: Values): RunInputs {
  const said: RunInputs = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.type === "boolean") {
      if (value === true || field.required) said[field.name] = value === true;
      continue;
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (!text) continue;
    said[field.name] = field.type === "number" && !Number.isNaN(Number(text)) ? Number(text) : text;
  }
  return said;
}

export function RunAgent({
  capability,
  intentionId,
  prefill,
}: {
  capability: CapabilityDetail;
  /** Run for an intention: its context is the agent's (LEKA-398). */
  intentionId?: string;
  /** What the intention already says of its inputs: suggested, editable. */
  prefill?: Values;
}) {
  const t = useDictionary();
  const w = t.agentRuns;
  const { start } = useAgentRunChange();
  const [values, setValues] = useState<Values>(() => prefill ?? {});
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    try {
      const started = await start.mutateAsync({
        key: capability.key,
        inputs: inputsOf(capability.inputs, values),
        intention_id: intentionId ?? null,
      });
      // Held by an approval control (LEKA-406): it waits, said so.
      if (started.status === "awaiting_approval") {
        notify.success({ title: w.held, description: w.heldHint });
      } else {
        notify.success({ title: w.queued, description: w.queuedHint });
      }
      setValues(prefill ?? {});
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors) {
        setErrors(error.fieldErrors);
      }
      notify.error({ title: error instanceof ApiError ? error.message : w.failedToStart });
    }
  }

  const files = capability.formats.filter((f) => f === "pptx" || f === "pdf");
  return (
    <Card
      title={fill(w.runNamed, { title: capability.title })}
      icon={<Play className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <form className="flex flex-col gap-3" onSubmit={(e) => void run(e)} data-testid="agent-run-form">
        {prefill && Object.keys(prefill).length ? (
          <p className="text-xs text-shell-muted" data-testid="agent-run-prefilled">
            {w.prefilled}
          </p>
        ) : null}
        {capability.inputs.map((field) => {
          const id = `agent-input-${field.name}`;
          const error = errors[`inputs.${field.name}`];
          return (
            <div key={field.name} className="flex flex-col gap-1">
              {field.type === "boolean" ? (
                <label htmlFor={id} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                  <Checkbox
                    id={id}
                    checked={values[field.name] === true}
                    onCheckedChange={(checked) =>
                      setValues((was) => ({ ...was, [field.name]: checked === true }))
                    }
                  />
                  {fieldLabel(t, field.name)}
                </label>
              ) : (
                <>
                  <label htmlFor={id} className="text-[0.8125rem] font-medium text-brand-navy">
                    {fieldLabel(t, field.name)}
                    <span className="font-normal text-shell-muted">
                      {" · "}
                      {field.required ? t.catalogue.detail.required : t.catalogue.detail.optional}
                    </span>
                  </label>
                  {field.type === "choice" ? (
                    <select
                      id={id}
                      className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm"
                      value={String(values[field.name] ?? "")}
                      onChange={(e) => setValues((was) => ({ ...was, [field.name]: e.target.value }))}
                    >
                      <option value="">—</option>
                      {field.choices.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      id={id}
                      type={field.type === "number" ? "number" : "text"}
                      placeholder={field.description}
                      aria-invalid={Boolean(error)}
                      value={String(values[field.name] ?? "")}
                      onChange={(e) => setValues((was) => ({ ...was, [field.name]: e.target.value }))}
                    />
                  )}
                </>
              )}
              {field.description && field.type !== "boolean" ? (
                <p className="text-xs text-shell-muted">{field.description}</p>
              ) : null}
              {error ? (
                <p className="text-xs text-state-danger" role="alert">
                  {(w.inputErrors as Record<string, string>)[error] ?? error}
                </p>
              ) : null}
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!capability.available || start.isPending}>
            <Play className="size-4" aria-hidden="true" />
            {start.isPending ? w.starting : w.start}
          </Button>
          <span className="text-xs text-shell-muted">
            {capability.available
              ? files.length
                ? fill(w.readOnlyFiles, { formats: files.map((f) => f.toUpperCase()).join(" + ") })
                : w.readOnly
              : w.cannotRun}
          </span>
        </div>
      </form>
    </Card>
  );
}

/** Whether LEKA draws files of what it delivers (the architect's deck). */
function hasFiles(run: AgentRun): boolean {
  return run.key === "application-architecture";
}

function statusSaid(w: Dictionary["agentRuns"], run: AgentRun): string {
  const said = (w.statuses as Record<string, string>)[run.status] ?? run.status;
  if (run.status !== "failed" || !run.error) return said;
  return `${said} · ${(w.errors as Record<string, string>)[run.error] ?? run.error}`;
}

function stepSaid(w: Dictionary["agentRuns"], event: AgentRunEvent): string {
  const detail = event.detail as Record<string, unknown>;
  const template = (w.steps as Record<string, string>)[event.kind] ?? event.kind;
  return fill(template, {
    name: String(detail.name ?? ""),
    outcome: (w.outcomes as Record<string, string>)[String(detail.outcome)] ?? String(detail.outcome ?? ""),
    given: String(detail.given ?? 0),
    left: String(Number(detail.out_of_scope ?? 0) + Number(detail.beyond ?? 0)),
    why: (w.withheld as Record<string, string>)[String(detail.why)] ?? String(detail.why ?? ""),
    model: String(detail.model ?? ""),
    // What the provider answered when it refused, as it said it.
    said: detail.said ? ` (${String(detail.said)})` : "",
    // An AI control's refusal said as such (LEKA-406), else the code.
    code:
      (w.errors as Record<string, string>)[String(detail.reason)] ??
      (w.errors as Record<string, string>)[String(detail.code)] ??
      String(detail.code ?? ""),
    control: String(detail.control ?? ""),
    formats: Array.isArray(detail.formats)
      ? detail.formats.map((f) => String(f).toUpperCase()).join(" + ")
      : "",
    slides: String(detail.slides ?? 0),
  });
}

/** The files LEKA drew of what a run delivered: downloaded as they are,
 * the PDF first — the template's mandatory deliverable. */
export function Deliverables({ run }: { run: AgentRun }) {
  const t = useDictionary();
  const w = t.agentRuns;
  if (!run.deliverables.length) return null;
  const files = [...run.deliverables].sort((a, b) => (a.format === "pdf" ? -1 : b.format === "pdf" ? 1 : 0));
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="agent-run-deliverables">
      {files.map((file) => (
        <a
          key={file.format}
          className={buttonVariants({ size: "sm", variant: file.format === "pdf" ? "default" : "outline" })}
          href={apiAddress(`/agent-runs/${encodeURIComponent(run.id)}/deliverables/${file.format}`)}
          download={file.name}
          data-format={file.format}
        >
          <Download className="size-3.5" aria-hidden="true" />
          {file.format === "pdf" ? w.downloadPdf : w.downloadPptx}
        </a>
      ))}
      <span className="text-xs text-shell-muted">
        {fill(w.slides, { count: run.deliverables[0]?.slides ?? 0 })}
      </span>
    </div>
  );
}

function download(run: AgentRunDetail) {
  const type = run.format === "json" ? "application/json" : "text/markdown";
  const url = URL.createObjectURL(new Blob([run.output ?? ""], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${run.key}-${run.id.slice(0, 8)}.${run.format === "json" ? "json" : "md"}`;
  link.click();
  URL.revokeObjectURL(url);
}

function RunDetail({ id }: { id: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.agentRuns;
  const { data } = useAgentRun(id);
  if (!data) return <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  return (
    <div className="mt-2 flex flex-col gap-3 rounded-lg bg-shell-canvas p-3" data-testid="agent-run-detail">
      {data.output ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-shell-muted">{w.analysis}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => download(data)}>
              <Download className="size-3.5" aria-hidden="true" />
              {w.download}
            </Button>
          </div>
          <pre
            className="max-h-96 overflow-auto rounded-md bg-white p-3 text-xs whitespace-pre-wrap text-brand-navy"
            data-testid="agent-run-output"
          >
            {data.output}
          </pre>
          {data.pending.length ? (
            <p className="text-xs text-shell-muted">
              {fill(w.pending, { formats: data.pending.map((f) => f.toUpperCase()).join(", ") })}
            </p>
          ) : null}
        </div>
      ) : null}
      {data.reasons.length ? (
        <p className="text-xs text-state-warning">
          {data.reasons.map((r) => String((r as Record<string, unknown>).code)).join(", ")}
        </p>
      ) : null}
      <div>
        <p className="mb-1 text-xs font-semibold text-shell-muted">{w.stepsTitle}</p>
        <ol className="space-y-1 text-xs" data-testid="agent-run-steps">
          {data.events.map((event) => (
            <li key={`${event.seq}-${event.kind}-${event.at}`} className="text-brand-navy">
              {stepSaid(w, event)}{" "}
              <span className="text-shell-muted">· {exactDate(locale, event.at)}</span>
            </li>
          ))}
        </ol>
      </div>
      <p className="text-xs text-shell-muted" data-testid="agent-run-usage">
        {fill(w.usage, {
          calls: String(data.usage.calls),
          tokens: String(data.usage.tokens_in + data.usage.tokens_out),
        })}
        {data.usage.cost_usd !== null ? ` · ${data.usage.cost_usd.toFixed(4)} $` : ""}
      </p>
    </div>
  );
}

export function AgentRuns({ agentKey, intentionId }: { agentKey: string; intentionId?: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.agentRuns;
  const { data: all } = useAgentRuns(agentKey);
  // For an intention: its runs only.
  const data = intentionId ? all?.filter((run) => run.intention_id === intentionId) : all;
  const { cancel } = useAgentRunChange();
  const [open, setOpen] = useState<string | null>(null);

  async function stop(run: AgentRun) {
    try {
      await cancel.mutateAsync(run.id);
      notify.success({ title: w.cancelled });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.cancelFailed });
    }
  }

  return (
    <Card title={w.title} icon={<Workflow className="size-4 text-shell-muted" aria-hidden="true" />}>
      {!data?.length ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="agent-runs">
          {data.map((run) => (
            <li key={run.id} className="rounded-lg border border-shell-line p-3" data-testid="agent-run">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={STATUS_TONE[run.status] ?? "neutral"} dot={ACTIVE.has(run.status)}>
                  {statusSaid(w, run)}
                </Pill>
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left text-[0.8125rem] text-brand-navy hover:underline"
                  aria-expanded={open === run.id}
                  onClick={() => setOpen(open === run.id ? null : run.id)}
                >
                  {Object.values(run.inputs).filter((v) => typeof v === "string").join(" · ") ||
                    run.title}
                </button>
                {ACTIVE.has(run.status) && run.mine ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void stop(run)}>
                    <Ban className="size-3.5" aria-hidden="true" />
                    {w.cancel}
                  </Button>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-shell-muted">
                {exactDate(locale, run.queued_at)}
                {run.mine ? ` · ${w.byYou}` : ""}
                {run.model ? ` · ${run.model}` : ""}
                {run.tool_calls ? ` · ${fill(w.toolCalls, { count: run.tool_calls })}` : ""}
              </p>
              {run.deliverables.length ? (
                <div className="mt-2">
                  <Deliverables run={run} />
                </div>
              ) : run.status === "running" && run.pending.length === 0 && hasFiles(run) ? (
                <p className="mt-1 text-xs text-shell-muted">{w.drawing}</p>
              ) : null}
              {open === run.id ? <RunDetail id={run.id} /> : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
