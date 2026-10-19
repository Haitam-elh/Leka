"use client";

import {
  CircleAlert,
  CircleCheck,
  Download,
  ExternalLink,
  FileCode2,
  FileText,
  GitPullRequest,
  Lightbulb,
  Loader2,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { Deliverables } from "@/components/capabilities/agent-runs";
import { RunCodeChanges } from "@/components/capabilities/code-changes";
import { DesignSimulator } from "@/components/capabilities/design-simulator";
import { ProposeFix } from "@/components/capabilities/propose-fix";
import { RunPublications } from "@/components/capabilities/publications";
import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { Markdown } from "@/components/ui/markdown";
import { routes } from "@/config/routes";
import { agentTitle } from "@/lib/agent-title";
import type { components } from "@/lib/api-types";
import type { AgentRun, AgentRunDetail } from "@/lib/agent-runs";
import {
  useAgentRun,
  useDrawFiles,
  useIntentionRuns,
  useRedrawDesign,
  useRewriteChange,
} from "@/lib/agent-runs-queries";
import { useRunCodeChanges } from "@/lib/code-changes-queries";
import { type DiffRow, diffRows, rowOf } from "@/lib/diff";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { working } from "@/lib/intentions/journey";
import { SPINNING } from "@/lib/motion";

/**
 * What an agent delivered for an intention (2026-10-14: « l'agent a terminé,
 * mais où est son livrable ? »).
 *
 *     every agent      its report, as a page — and its files when it drew
 *                      some (the architect's PDF and PowerPoint)
 *     the code review  the repository as it read it: its pull requests, the
 *                      one it reviewed opened — each file's diff, its
 *                      comments on their lines: red for what is wrong, green
 *                      for what to do better or what is right — then its
 *                      report
 *     every one, too   what to send out of it: tickets LEKA drafts for a
 *                      Jira project, pages for a Confluence space, sent once
 *                      a person chose them (2026-10-18)
 *     a review         its fix, asked of the code-change agent from it: the
 *                      change shown before and after, applied on GitHub only
 *                      once a person accepts it (2026-10-18)
 *
 * Only what the API kept is drawn. A comment the agent wrote on a line it
 * did not read was dropped there, and is counted here.
 */

type Review = components["schemas"]["CodeReviewRead"];
type Comment = components["schemas"]["ReviewCommentRead"];
type PullFile = components["schemas"]["PullFileRead"];
type PullBrief = components["schemas"]["PullBriefRead"];

/** Where a run's deliverable is read. */
const CITED = String.raw`\[[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\]`;

/** A report as a person reads it: the ids it cites — kept in its download,
 *  its evidence one link away — never shown in its text (2026-10-19). */
export function readable(report: string): string {
  return report
    .replace(new RegExp(String.raw`\s*\((?:\s*${CITED}\s*,?)+\)`, "gi"), "")
    .replace(new RegExp(String.raw`\s*${CITED}`, "gi"), "");
}

export function deliverableHref(intentionId: string, runId: string): string {
  return `${routes.intention(intentionId)}/deliverable?run=${encodeURIComponent(runId)}`;
}

/** The run to show: the one asked for, else the latest delivered, else the
 * latest. */
function chosen(runs: readonly AgentRun[], asked: string | null): AgentRun | undefined {
  return (
    runs.find((run) => run.id === asked) ??
    runs.find((run) => run.status === "succeeded") ??
    runs[0]
  );
}

export function DeliverableView({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const search = useSearchParams();
  const runs = useIntentionRuns(intention.id, working(intention.journey));
  const run = chosen(runs.data ?? [], search?.get("run") ?? null);
  const detail = useAgentRun(run?.status === "succeeded" ? run.id : null);
  if (!runs.data) return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  if (!run) {
    return <StatePanel icon={FileText} title={w.none} description={w.noneBody} testId="deliverable-none" />;
  }
  const agent = agentTitle(t, run.key, run.title ?? run.key);
  if (run.status !== "succeeded") {
    const failed = run.status === "failed" || run.status === "cancelled";
    const errors = t.agentRuns.errors as Record<string, string>;
    return (
      <StatePanel
        icon={failed ? CircleAlert : FileText}
        title={
          failed
            ? fill(w.failed, { agent, why: (run.error && errors[run.error]) || run.error || "—" })
            : fill(w.working, { agent })
        }
        testId="deliverable-waiting"
      />
    );
  }
  if (!detail.data) return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  return <Delivered run={detail.data} others={(runs.data ?? []).filter((r) => r.id !== run.id)} intentionId={intention.id} />;
}

function Delivered({
  run,
  others,
  intentionId,
}: {
  run: AgentRunDetail;
  others: AgentRun[];
  intentionId: string;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const router = useRouter();
  const w = t.intentions.deliverable;
  const agent = agentTitle(t, run.key, run.title ?? run.key);
  const report = run.report ?? run.output ?? "";
  // The change it proposed to the code, when it proposed one — followed
  // while LEKA writes it again.
  const writing = (run.drawing ?? []).includes("change");
  const changes = useRunCodeChanges(run.id, writing);
  // What it delivered, the most telling first: the screen it redrew, the
  // change it proposed, its comments on the code, its report.
  const views = [
    ...(run.design ? (["design"] as const) : []),
    ...(changes.data?.length ? (["change"] as const) : []),
    ...(run.review ? (["code"] as const) : []),
    "report" as const,
  ];
  type View = (typeof views)[number];
  const [chosen, setView] = useState<View | null>(null);
  const view: View = chosen && views.includes(chosen) ? chosen : views[0];
  return (
    <div className="flex flex-col gap-4" data-testid="deliverable" data-agent={run.key}>
      <section className="flex flex-wrap items-center gap-3 rounded-xl border border-shell-line bg-white px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="text-[1.0625rem] font-semibold text-brand-navy">{agent}</p>
          <p className="text-[0.8125rem] text-shell-muted">
            {fill(w.by, {
              version: run.version,
              when: run.finished_at ? exactDate(locale, run.finished_at) : "—",
            })}
          </p>
        </div>
        <Deliverables run={run} />
        <DrawFiles run={run} />
        {report ? (
          <Button type="button" variant="outline" size="sm" onClick={() => download(run, report)}>
            <Download className="size-3.5" aria-hidden="true" />
            {w.download}
          </Button>
        ) : null}
        <ProposeFix
          run={run}
          intentionId={intentionId}
          onStarted={(id) => router.push(deliverableHref(intentionId, id))}
        />
      </section>
      {/* An agent that proposes code, its change not there: why, and again. */}
      {CHANGE_AGENTS.has(run.key) && changes.data && !changes.data.length ? (
        <ChangeMissing run={run} writing={writing} />
      ) : null}
      {/* The designer, its mock-ups not there: why, and again (2026-10-18). */}
      {DESIGN_AGENTS.has(run.key) && !run.design ? <DesignMissing run={run} /> : null}
      {/* What to send out of it: tickets for Jira, pages for Confluence. */}
      <RunPublications runId={run.id} />
      {views.length > 1 ? (
        <div className="flex gap-2" role="tablist" aria-label={w.title}>
          {views.map((each) => (
            <button
              key={each}
              type="button"
              role="tab"
              aria-selected={view === each}
              onClick={() => setView(each)}
              data-testid={`deliverable-tab-${each}`}
              className={cn(
                "rounded-lg px-3 py-1.5 text-[0.8125rem] font-medium outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40",
                view === each ? "bg-brand-violet-soft text-brand-violet" : "text-shell-nav hover:bg-shell-canvas",
              )}
            >
              {each === "design" ? w.design : each === "change" ? w.change : each === "code" ? w.onCode : w.report}
            </button>
          ))}
        </div>
      ) : null}
      {run.design && view === "design" ? (
        <DesignSimulator runId={run.id} />
      ) : view === "change" ? (
        <RunCodeChanges runId={run.id} />
      ) : run.review && view === "code" ? (
        <CodeReview review={run.review} />
      ) : report ? (
        <section className="rounded-xl border border-shell-line bg-white px-6 py-5" data-testid="deliverable-report">
          <Markdown source={readable(report)} />
        </section>
      ) : (
        <StatePanel icon={FileText} title={w.empty} />
      )}
      {others.length ? (
        <Card title={w.others}>
          <ul className="flex flex-col gap-1 text-[0.8125rem]">
            {others.map((other) => (
              <li key={other.id}>
                <Link href={deliverableHref(intentionId, other.id)} className="text-shell-nav-active hover:underline">
                  {other.title ?? other.key}
                </Link>{" "}
                <span className="text-shell-muted">· {(t.agentRuns.statuses as Record<string, string>)[other.status] ?? other.status}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

/** The agents whose deliverable is a change to the code, shown before and
 * after (`renders: code_change`). */
const CHANGE_AGENTS: ReadonlySet<string> = new Set(["code-change", "test-generation"]);
/** The agents whose deliverable is a screen redrawn, before and after
 * (`renders: design_mockups`). */
const DESIGN_AGENTS: ReadonlySet<string> = new Set(["design-review"]);

/** Its analysis delivered, its change not written (2026-10-18: the analysis
 * alone was shown, nothing said): why, and the way to write it again — from
 * what it delivered, never the run done again. */
function ChangeMissing({ run, writing }: { run: AgentRunDetail; writing: boolean }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const again = useRewriteChange(run.id);
  if (writing) {
    return (
      <p
        className="flex items-center gap-2 rounded-xl border border-shell-line bg-white px-5 py-3 text-[0.8125rem] text-shell-muted"
        role="status"
        data-testid="deliverable-change-writing"
      >
        <Loader2 className={cn("size-4", SPINNING)} aria-hidden="true" />
        {w.changeWriting}
      </p>
    );
  }
  const failed = run.draw_failed ?? null;
  if (!failed) return null;
  const why = (w.changeErrors as Record<string, string>)[failed] ?? failed;
  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-xl border border-state-warning/30 bg-state-warning-soft px-5 py-3"
      data-testid="deliverable-change-missing"
      data-error={failed}
    >
      <CircleAlert className="size-4 shrink-0 text-state-warning" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[0.8125rem] text-brand-navy">{fill(w.changeFailed, { why })}</p>
        {run.draw_said ? (
          // What the model's provider, or LEKA, said: to quote when asking why.
          <p className="mt-0.5 font-mono text-xs break-words text-shell-muted" data-testid="deliverable-change-said">
            {run.draw_said}
          </p>
        ) : null}
      </div>
      <Button
        type="button"
        size="sm"
        disabled={again.isPending}
        onClick={() => again.mutate()}
        data-testid="deliverable-change-again"
      >
        {again.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
        {w.changeAgain}
      </Button>
    </section>
  );
}

/** Its review delivered, its mock-ups not drawn: being drawn, or why not and
 * the way to draw them again — never the review done again. A review that
 * proposes no design says nothing here. */
function DesignMissing({ run }: { run: AgentRunDetail }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const again = useRedrawDesign(run.id);
  if ((run.drawing ?? []).includes("design")) {
    return (
      <p
        className="flex items-center gap-2 rounded-xl border border-shell-line bg-white px-5 py-3 text-[0.8125rem] text-shell-muted"
        role="status"
        data-testid="deliverable-design-drawing"
      >
        <Loader2 className={cn("size-4", SPINNING)} aria-hidden="true" />
        {w.designDrawing}
      </p>
    );
  }
  const failed = run.draw_failed ?? null;
  // Not drawn though its review proposes a design — its mark forgotten, or
  // drawn before mock-ups were drawn one at a time.
  const undrawn = (run.drawable ?? []).includes("design");
  if (!failed && !undrawn) return null;
  const why = failed ? ((w.changeErrors as Record<string, string>)[failed] ?? failed) : null;
  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-xl border border-state-warning/30 bg-state-warning-soft px-5 py-3"
      data-testid="deliverable-design-missing"
      data-error={failed ?? undefined}
    >
      <CircleAlert className="size-4 shrink-0 text-state-warning" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[0.8125rem] text-brand-navy">
          {why ? fill(w.designFailed, { why }) : w.designNotDrawn}
        </p>
        {run.draw_said ? (
          <p className="mt-0.5 font-mono text-xs break-words text-shell-muted" data-testid="deliverable-design-said">
            {run.draw_said}
          </p>
        ) : null}
      </div>
      <Button
        type="button"
        size="sm"
        disabled={again.isPending}
        onClick={() => again.mutate()}
        data-testid="deliverable-design-again"
      >
        {again.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
        {w.designAgain}
      </Button>
    </section>
  );
}

/** Delivered without its deck (launched asking for no file): drawn after it
 * on asking, from what it delivered — never run again (2026-10-16). */
function DrawFiles({ run }: { run: AgentRunDetail }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const draw = useDrawFiles(run.id);
  // Its files only: a change being written again is said elsewhere.
  const drawing = (run.drawing ?? []).filter((f) => f === "pdf" || f === "pptx");
  const drawable = (run.drawable ?? []).filter((f) => f === "pdf" || f === "pptx");
  if (drawing.length) {
    return (
      <span className="text-[0.8125rem] text-shell-muted" role="status" data-testid="deliverable-drawing">
        {w.drawing}
      </span>
    );
  }
  if (!drawable.length) return null;
  const errors = t.agentRuns.errors as Record<string, string>;
  const failed = run.draw_failed ?? null;
  return (
    <>
      {failed ? (
        // Never left waiting: why it did not come, and the way to ask again.
        <span className="text-[0.8125rem] text-state-warning" role="status" data-testid="deliverable-draw-failed">
          {fill(w.drawFailed, { why: errors[failed] ?? failed })}
        </span>
      ) : null}
      <Button
        type="button"
        size="sm"
        disabled={draw.isPending}
        onClick={() => draw.mutate(drawable)}
        data-testid="deliverable-draw"
      >
        <FileText className="size-3.5" aria-hidden="true" />
        {failed ? w.drawAgain : drawable.length > 1 ? w.drawBoth : drawable[0] === "pdf" ? w.drawPdf : w.drawPptx}
      </Button>
    </>
  );
}

function download(run: AgentRunDetail, report: string) {
  const url = URL.createObjectURL(new Blob([report], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${run.key}-${run.id.slice(0, 8)}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

// ── the code review: the repository as the agent read it ────────────────────

function stateOf(pull: PullBrief): "merged" | "open" | "closed" | "draft" {
  if (pull.merged) return "merged";
  if (pull.draft) return "draft";
  return pull.state === "open" ? "open" : "closed";
}

const STATE_TONE = { merged: "violet", open: "success", closed: "neutral", draft: "neutral" } as const;
const VERDICT_TONE = { favorable: "success", prudence: "warning", a_revoir: "danger" } as const;

function CodeReview({ review }: { review: Review }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const pull = review.pull;
  const count = (kind: Comment["kind"]) => review.comments.filter((c) => c.kind === kind).length;
  return (
    <div className="grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)] xl:items-start" data-testid="code-review">
      {/* The repository, as it listed its pull requests. */}
      <aside className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4" aria-label={w.repository}>
        <p className="flex items-center gap-2 text-[0.8125rem] font-semibold text-brand-navy">
          <GitPullRequest className="size-4 text-shell-muted" aria-hidden="true" />
          <span className="truncate font-mono">{review.repository}</span>
        </p>
        <p className="text-xs font-medium tracking-wide text-shell-nav uppercase">{w.pulls}</p>
        <ul className="flex flex-col gap-1" data-testid="code-review-pulls">
          {review.pulls.map((each) => {
            const reviewed = each.number === review.number;
            return (
              <li key={each.number}>
                <div
                  className={cn(
                    "flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-[0.8125rem]",
                    reviewed ? "bg-brand-violet-soft/60 shadow-[inset_3px_0_0_var(--brand-violet)]" : "opacity-70",
                  )}
                  aria-current={reviewed || undefined}
                  data-testid="code-review-pull"
                  data-number={each.number}
                >
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-shell-muted">#{each.number}</span>
                    <span className="min-w-0 flex-1 truncate font-medium text-brand-navy" title={each.title}>
                      {each.title}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5 text-xs text-shell-muted">
                    <Pill tone={STATE_TONE[stateOf(each)]}>{w.states[stateOf(each)]}</Pill>
                    {reviewed
                      ? fill(w.reviewed, { count: review.comments.length })
                      : each.url ? (
                          <a href={each.url} target="_blank" rel="noreferrer noopener" className="hover:underline">
                            {w.notReviewed}
                          </a>
                        ) : (
                          w.notReviewed
                        )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* The pull request it reviewed, as it read it. */}
      <section className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-2 rounded-xl border border-shell-line bg-white px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 flex-1 text-[1.0625rem] font-semibold text-brand-navy" dir="auto">
              {pull.title} <span className="font-normal text-shell-muted">#{pull.number}</span>
            </h3>
            {review.verdict ? (
              <Pill tone={VERDICT_TONE[review.verdict]} data-testid="code-review-verdict">
                {w.verdicts[review.verdict]}
              </Pill>
            ) : null}
            {pull.url ? (
              <a
                href={pull.url}
                target="_blank"
                rel="noreferrer noopener"
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                <ExternalLink className="size-3.5" aria-hidden="true" />
                {w.onGitHub}
              </a>
            ) : null}
          </div>
          <p className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-shell-muted">
            <Pill tone={STATE_TONE[stateOf(pull)]}>{w.states[stateOf(pull)]}</Pill>
            {pull.author ? <span>{fill(w.byAuthor, { author: pull.author })}</span> : null}
            {pull.base && pull.head ? (
              <span className="font-mono text-xs">
                {pull.base} ← {pull.head}
              </span>
            ) : null}
            <span className="text-[#15803d]">+{pull.additions}</span>
            <span className="text-[#b91c1c]">−{pull.deletions}</span>
            <span>{fill(w.files, { count: pull.files.length })}</span>
          </p>
          <p className="text-[0.8125rem] text-brand-navy" data-testid="code-review-counts">
            {fill(w.counts, { issues: count("issue"), suggestions: count("suggestion"), good: count("good") })}
          </p>
          {review.dropped ? (
            <p className="text-xs text-shell-muted">{fill(w.dropped, { count: review.dropped })}</p>
          ) : null}
        </div>
        {pull.files.map((file) => (
          <FileReview
            key={file.path}
            file={file}
            comments={review.comments.filter((c) => c.path === file.path)}
          />
        ))}
      </section>
    </div>
  );
}

const LINE = {
  add: "bg-[#e6f6ea] text-[#14532d]",
  remove: "bg-[#fdecec] text-[#7f1d1d]",
  hunk: "bg-[#eef3fb] text-[#1e3a8a]",
  same: "text-brand-navy",
} as const;

const SIGN = { add: "+", remove: "−", hunk: "", same: " " } as const;

function FileReview({ file, comments }: { file: PullFile; comments: Comment[] }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const rows = useMemo(() => diffRows(file.patch), [file.patch]);
  // Each comment under its line; one on the whole file, above the diff.
  const { under, above } = useMemo(() => {
    const placed = new Map<number, Comment[]>();
    const loose: Comment[] = [];
    for (const comment of comments) {
      const at = comment.line === null ? -1 : rowOf(rows, comment.line, comment.side);
      if (at < 0) loose.push(comment);
      else placed.set(at, [...(placed.get(at) ?? []), comment]);
    }
    return { under: placed, above: loose };
  }, [comments, rows]);
  return (
    <details
      open={comments.length > 0}
      className="rounded-xl border border-shell-line bg-white"
      data-testid="code-review-file"
      data-path={file.path}
    >
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-4 py-3 text-[0.8125rem]">
        <FileCode2 className="size-4 text-shell-muted" aria-hidden="true" />
        <span className="min-w-0 truncate font-mono text-brand-navy">{file.path}</span>
        <span className="text-xs text-[#15803d]">+{file.additions}</span>
        <span className="text-xs text-[#b91c1c]">−{file.deletions}</span>
        {comments.length ? (
          <Pill tone={comments.some((c) => c.kind === "issue") ? "danger" : "success"}>
            {fill(w.commentsOn, { count: comments.length })}
          </Pill>
        ) : (
          <span className="text-xs text-shell-muted">{w.noComment}</span>
        )}
      </summary>
      <div className="border-t border-shell-line">
        {above.length ? (
          <div className="flex flex-col gap-2 p-3">
            {above.map((comment, index) => (
              <CommentCard key={index} comment={comment} whole={comment.line === null} />
            ))}
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-[0.75rem] leading-5" data-testid="code-review-diff">
            <tbody>
              {rows.map((row, index) => (
                <DiffLine key={index} row={row} comments={under.get(index)} />
              ))}
            </tbody>
          </table>
        </div>
        {file.truncated ? <p className="px-4 py-2 text-xs text-shell-muted">{w.truncated}</p> : null}
      </div>
    </details>
  );
}

function DiffLine({ row, comments }: { row: DiffRow; comments?: Comment[] }) {
  return (
    <>
      <tr className={LINE[row.kind]} data-kind={row.kind} data-new={row.new ?? undefined}>
        {row.kind === "hunk" ? (
          <td colSpan={4} className="px-3 py-0.5 whitespace-pre">
            {row.text}
          </td>
        ) : (
          <>
            <td className="w-12 border-e border-shell-line/60 px-2 text-end text-shell-muted select-none">
              {row.old ?? ""}
            </td>
            <td className="w-12 border-e border-shell-line/60 px-2 text-end text-shell-muted select-none">
              {row.new ?? ""}
            </td>
            <td className="w-5 px-1 text-center select-none" aria-hidden="true">
              {SIGN[row.kind]}
            </td>
            <td className="px-2 whitespace-pre">{row.text || " "}</td>
          </>
        )}
      </tr>
      {comments?.length ? (
        <tr>
          <td colSpan={4} className="bg-white px-3 py-2">
            <div className="flex flex-col gap-2 font-sans">
              {comments.map((comment, index) => (
                <CommentCard key={index} comment={comment} />
              ))}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function CommentCard({ comment, whole = false }: { comment: Comment; whole?: boolean }) {
  const t = useDictionary();
  const w = t.intentions.deliverable;
  const issue = comment.kind === "issue";
  const Icon = issue ? CircleAlert : comment.kind === "suggestion" ? Lightbulb : CircleCheck;
  return (
    <article
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-[0.8125rem]",
        issue ? "border-state-danger/30 bg-state-danger-soft" : "border-state-success/30 bg-state-success-soft",
      )}
      data-testid="code-review-comment"
      data-kind={comment.kind}
      data-line={comment.line ?? undefined}
    >
      <p className="flex flex-wrap items-center gap-2">
        <Icon
          className={cn("size-4 shrink-0", issue ? "text-state-danger" : "text-state-success")}
          aria-hidden="true"
        />
        <span className={cn("font-semibold", issue ? "text-state-danger" : "text-state-success")}>
          {w.kinds[comment.kind]}
          {issue && comment.severity ? ` · ${w.severities[comment.severity]}` : ""}
        </span>
        {comment.title ? <span className="font-medium text-brand-navy">{comment.title}</span> : null}
        <span className="text-xs text-shell-muted">
          {whole || comment.line === null ? w.fileComment : fill(w.line, { line: comment.line })}
        </span>
      </p>
      <p className="text-brand-navy" dir="auto">
        {comment.comment}
      </p>
      {comment.suggestion ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-state-success">{w.proposed}</span>
          <pre className="overflow-x-auto rounded-md bg-white/80 p-2 font-mono text-[0.75rem] whitespace-pre text-[#14532d]">
            {comment.suggestion}
          </pre>
        </div>
      ) : null}
    </article>
  );
}
