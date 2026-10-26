"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Columns2,
  ExternalLink,
  FileCode2,
  GitPullRequest,
  Loader2,
  RefreshCw,
  Rows3,
  Undo2,
  Wrench,
  X,
} from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { useRewriteChange } from "@/lib/agent-runs-queries";
import {
  type CodeChange,
  type CodeChangeFile,
  type CodeChangeFollow,
  type CodeChangeRepair,
  MAX_REPAIRS,
} from "@/lib/code-changes";
import {
  codeChangeKeys,
  useCodeChangeDecision,
  useCodeChangeFollow,
  useCodeChangeRepair,
  useCodeChangeUndo,
  useCodeChanges,
  useRunCodeChanges,
} from "@/lib/code-changes-queries";
import { type Hunk, hunksOf, type SplitCell, splitRows } from "@/lib/diff";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { modelTitle } from "@/lib/models";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";
import { useAllowWrite } from "@/lib/sources-queries";

/**
 * What the code-change agent proposed for an intention: each file and its
 * diff, computed by LEKA from the branch it read — shown before and after,
 * side by side, or as one diff — for a person to accept, LEKA then opening
 * a pull request (never a merge), or to reject.
 */

const TONE: Record<CodeChange["status"], TileTone> = {
  proposed: "warning",
  applied: "success",
  rejected: "neutral",
  failed: "danger",
};

/** A diff's lines, each with what it is: added, removed, a hunk, the rest. */
export function diffLines(diff: string): { text: string; kind: "add" | "remove" | "hunk" | "meta" | "same" }[] {
  return diff
    .replace(/\n$/, "")
    .split("\n")
    .map((text) => ({
      text,
      kind: text.startsWith("+++") || text.startsWith("---")
        ? "meta"
        : text.startsWith("@@")
          ? "hunk"
          : text.startsWith("+")
            ? "add"
            : text.startsWith("-")
              ? "remove"
              : "same",
    }));
}

const CELL_CLASS = {
  same: "text-brand-navy",
  remove: "bg-[#fdecec] text-[#7f1d1d]",
  add: "bg-[#e6f6ea] text-[#14532d]",
} as const;

function Side({ cell }: { cell: SplitCell | null }) {
  if (!cell) return <td colSpan={2} className="bg-shell-canvas/60" aria-hidden="true" />;
  return (
    <>
      <td className={`w-10 select-none border-r border-shell-line px-2 text-right text-shell-muted ${CELL_CLASS[cell.change]}`}>
        {cell.number}
      </td>
      <td
        className={`px-2 font-mono whitespace-pre-wrap [overflow-wrap:anywhere] ${CELL_CLASS[cell.change]}`}
        data-change={cell.change}
      >
        {cell.text || " "}
      </td>
    </>
  );
}

function SplitDiff({ diff }: { diff: string }) {
  const t = useDictionary();
  const w = t.codeChanges;
  return (
    <div className="max-h-[32rem] overflow-auto border-t border-shell-line" data-testid="code-change-split">
      <table className="w-full min-w-[56rem] table-fixed border-collapse text-[0.75rem] leading-5">
        <colgroup>
          <col className="w-10" />
          <col />
          <col className="w-10" />
          <col />
        </colgroup>
        <thead className="sticky top-0 z-10 bg-white text-left text-xs text-shell-muted">
          <tr>
            <th colSpan={2} className="border-b border-r border-shell-line px-3 py-1.5 font-semibold">
              {w.before}
            </th>
            <th colSpan={2} className="border-b border-shell-line px-3 py-1.5 font-semibold text-[#15803d]">
              {w.after}
            </th>
          </tr>
        </thead>
        <tbody>
          {splitRows(diff).map((row, index) =>
            row.kind === "hunk" ? (
              <tr key={index} className="bg-[#eef3fb] text-[#1e3a8a]">
                <td colSpan={4} className="px-3 font-mono">
                  {row.text}
                </td>
              </tr>
            ) : (
              <tr key={index} className="align-top">
                <Side cell={row.left} />
                <Side cell={row.right} />
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

const LINE_CLASS = {
  add: "bg-[#e6f6ea] text-[#14532d]",
  remove: "bg-[#fdecec] text-[#7f1d1d]",
  hunk: "bg-[#eef3fb] text-[#1e3a8a]",
  meta: "text-shell-muted",
  same: "text-brand-navy",
} as const;

/** One modification, numbered across the change: where — the file and its
 * lines —, what it adds and removes, and its lines before and after. */
function Modification({
  n,
  file,
  hunk,
  open,
  view,
}: {
  n: number;
  file: CodeChangeFile;
  hunk: Hunk;
  open: boolean;
  view: "split" | "unified";
}) {
  const t = useDictionary();
  const w = t.codeChanges;
  const lines =
    hunk.from === hunk.to
      ? fill(w.line, { from: String(hunk.from) })
      : fill(w.lines, { from: String(hunk.from), to: String(hunk.to) });
  return (
    <details
      className="rounded-md border border-shell-line bg-white"
      data-testid="code-change-modification"
      data-path={file.path}
      open={open}
    >
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-[0.8125rem]">
        <span className="font-semibold text-brand-navy">{fill(w.modification, { n: String(n) })}</span>
        <FileCode2 className="size-3.5 text-shell-muted" aria-hidden="true" />
        <span className="min-w-0 font-mono break-all text-brand-navy">{file.path}</span>
        <span className="text-xs text-shell-muted">{lines}</span>
        <span className="text-xs text-[#15803d]">+{hunk.added}</span>
        <span className="text-xs text-[#b91c1c]">−{hunk.removed}</span>
        {file.why ? <span className="w-full text-xs text-shell-muted">{file.why}</span> : null}
      </summary>
      {view === "split" ? (
        <SplitDiff diff={hunk.text} />
      ) : (
        <pre className="max-h-[28rem] overflow-auto border-t border-shell-line text-[0.75rem] leading-5" data-testid="code-change-diff">
          {diffLines(hunk.text).map((line, index) => (
            <div key={index} className={`px-3 font-mono whitespace-pre ${LINE_CLASS[line.kind]}`} data-kind={line.kind}>
              {line.text || " "}
            </div>
          ))}
        </pre>
      )}
    </details>
  );
}

type StepState = "done" | "current" | "failed" | "warning" | "todo";

const STEP_ICON: Record<StepState, React.ReactNode> = {
  done: <CircleCheck className="size-4 text-state-success" aria-hidden="true" />,
  current: <Loader2 className={cn("size-4 text-brand-violet", SPINNING)} aria-hidden="true" />,
  failed: <CircleX className="size-4 text-state-danger" aria-hidden="true" />,
  warning: <CircleAlert className="size-4 text-state-warning" aria-hidden="true" />,
  todo: <CircleDashed className="size-4 text-shell-muted" aria-hidden="true" />,
};

const OPEN_STAGES: ReadonlySet<CodeChangeFollow["stage"]> = new Set([
  "checks",
  "no_checks",
  "checks_failed",
  "checks_unreadable",
  "conflict",
  "ready",
]);

/**
 * Its pull request, from LEKA to production (2026-10-20): opened, its CI,
 * a person's merge on GitHub — LEKA never merges — then the deployment
 * that took it, read on GitHub every minute until it is done.
 */
function PullRequestFollow({
  change,
  reverter,
  manager,
}: {
  change: CodeChange;
  reverter: CodeChange | null;
  manager: boolean;
}) {
  const t = useDictionary();
  const w = t.codeChanges.follow;
  const { format: locale } = useLocale();
  // Followed to the end before the version before it was kept (2026-10-21):
  // read once more, for « Revenir en arrière ».
  const unknownBefore = Boolean(change.follow?.merged_at) && !change.follow?.before_sha;
  // Being repaired (2026-10-24): read again until it ends, closed or not.
  const repairing = change.repairs?.at(-1)?.state === "running";
  const live = useCodeChangeFollow(change.id, !change.follow?.done || unknownBefore || repairing);
  const follow = live.data?.follow ?? change.follow ?? null;
  const stage = follow?.stage ?? "checks";
  const open = OPEN_STAGES.has(stage);
  const checks = follow?.checks ?? null;
  const environment = follow?.deployment?.environment || w.production;
  // Closed in red: said red, never « Passée » (2026-10-24).
  const red = stage === "checks_failed" || (stage === "closed" && checks?.state === "failure");

  let checksStep: [StepState, string];
  if (stage === "closed" && red) {
    checksStep = ["failed", fill(w.checks.failure, { names: (checks?.failed ?? []).join(", ") })];
  } else if (!open || stage === "ready") {
    checksStep = [
      "done",
      checks?.state === "success" ? fill(w.checks.success, { total: String(checks.total) }) : w.checks.passed,
    ];
  } else if (stage === "checks_failed") {
    checksStep = ["failed", fill(w.checks.failure, { names: (checks?.failed ?? []).join(", ") })];
  } else if (stage === "no_checks") {
    checksStep = ["warning", w.checks.none];
  } else if (stage === "checks_unreadable") {
    checksStep = ["warning", w.checks.unreadable];
  } else if (checks && checks.total > 0) {
    checksStep = [
      stage === "conflict" ? "done" : "current",
      fill(w.checks.running, { passed: String(checks.passed), total: String(checks.total) }),
    ];
  } else {
    checksStep = ["current", w.checks.waiting];
  }

  let mergeStep: [StepState, string];
  if (stage === "conflict") mergeStep = ["failed", fill(w.merge.conflict, { branch: change.base_branch })];
  else if (stage === "closed") mergeStep = ["failed", w.merge.closed];
  else if (stage === "checks_failed") mergeStep = ["todo", w.merge.fixFirst];
  else if (open && stage !== "checks") mergeStep = ["current", w.merge.ready];
  else if (open) mergeStep = ["todo", w.merge.waiting];
  else mergeStep = ["done", follow?.merged_at ? fill(w.merge.merged, { date: exactDate(locale, follow.merged_at) }) : w.merge.mergedNoDate];

  let deployStep: [StepState, string];
  if (stage === "deployed") {
    deployStep = [
      "done",
      fill(w.deploy.deployed, {
        environment,
        date: follow?.deployment?.at ? exactDate(locale, follow.deployment.at) : "—",
      }),
    ];
  } else if (stage === "deploy_failed") deployStep = ["failed", fill(w.deploy.failed, { environment })];
  else if (stage === "deploying") deployStep = ["current", fill(w.deploy.deploying, { environment })];
  else if (stage === "merged") deployStep = follow?.done ? ["warning", w.deploy.none] : ["current", w.deploy.merged];
  else if (stage === "rolling_back") deployStep = ["current", w.deploy.rollingBack];
  else if (stage === "rolled_back") deployStep = ["warning", w.deploy.rolledBack];
  else if (stage === "rollback_failed") deployStep = ["failed", w.deploy.rollbackFailed];
  else deployStep = ["todo", w.deploy.waiting];

  const steps: { key: string; title: string; state: StepState; text: string; href?: string | null; link?: string }[] = [
    {
      key: "opened",
      title: w.steps.opened,
      state: "done",
      text: fill(w.opened, { number: String(change.pull_request_number ?? "") }),
      href: change.pull_request_url,
      link: w.seeOnGitHub,
    },
    {
      key: "checks",
      title: w.steps.checks,
      state: checksStep[0],
      text: checksStep[1],
      href: red ? checks?.failed_url : null,
      link: w.checks.seeFailure,
    },
    { key: "merge", title: w.steps.merge, state: mergeStep[0], text: mergeStep[1] },
    {
      key: "deploy",
      title: w.steps.deploy,
      state: deployStep[0],
      text: deployStep[1],
      href: stage === "deployed" || stage === "deploy_failed" ? follow?.deployment?.url : null,
      link: w.deploy.see,
    },
  ];

  return (
    <section
      className="flex flex-col gap-2 rounded-lg border border-shell-line bg-shell-canvas/50 p-3"
      aria-label={w.title}
      data-testid="code-change-follow"
      data-stage={stage}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-[0.8125rem] font-semibold text-brand-navy">{w.title}</p>
        {follow?.checked_at ? (
          <span className="text-xs text-shell-muted">{fill(w.checkedAt, { time: exactDate(locale, follow.checked_at) })}</span>
        ) : null}
        {!follow?.done ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={live.isFetching}
            onClick={() => void live.refetch()}
            data-testid="code-change-follow-refresh"
          >
            <RefreshCw className={cn("size-3.5", live.isFetching && SPINNING)} aria-hidden="true" />
            {w.refresh}
          </Button>
        ) : null}
      </div>
      <ol className="flex flex-col gap-1.5">
        {steps.map((step) => (
          <li key={step.key} className="flex items-start gap-2" data-testid={`code-change-step-${step.key}`} data-state={step.state}>
            <span className="mt-0.5 shrink-0">{STEP_ICON[step.state]}</span>
            <p className="min-w-0 flex-1 text-[0.8125rem] text-brand-navy">
              <span className="font-medium">{step.title}</span>
              <span className="text-shell-muted"> — </span>
              {step.text}
              {step.href ? (
                <>
                  {" "}
                  <a
                    className="inline-flex items-center gap-0.5 font-medium underline"
                    href={step.href}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {step.link}
                    <ExternalLink className="size-3" aria-hidden="true" />
                  </a>
                </>
              ) : null}
            </p>
          </li>
        ))}
      </ol>
      {follow?.error ? (
        <p className="text-xs text-state-warning" role="status">
          {fill(w.readFailed, { error: follow.error })}
        </p>
      ) : null}
      <RepairPanel change={live.data ?? change} red={red} closed={stage === "closed"} />
      <GoBack
        change={live.data ?? change}
        reverter={reverter}
        manager={manager}
        refresh={() => void live.refetch()}
      />
    </section>
  );
}

const REPAIR_TONE: Record<CodeChangeRepair["state"], string> = {
  running: "text-brand-violet",
  pushed: "text-state-success",
  failed: "text-state-danger",
  outside: "text-state-warning",
  unneeded: "text-shell-muted",
};

/**
 * « Réparer le problème » (2026-10-24): its CI in red, LEKA reads what
 * failed on GitHub — the test, the error, the end of its log —, the
 * workspace's model writes the fix, and LEKA adds it to the pull request's
 * branch: the CI runs again. Closed in red, the pull request is reopened
 * first. Never a merge: a person still reviews and merges. Each repair
 * said after — what failed, why, what it changed, its commit.
 */
function RepairPanel({ change, red, closed }: { change: CodeChange; red: boolean; closed: boolean }) {
  const t = useDictionary();
  const w = t.codeChanges.repair;
  // Who may approve what an intention does — as the API holds it.
  const approver = usePermissions()?.includes("intention:approve") ?? false;
  const repair = useCodeChangeRepair(change.id);
  const repairs = change.repairs ?? [];
  const running = repairs.at(-1)?.state === "running";
  const left = MAX_REPAIRS - repairs.filter((r) => r.state === "pushed").length;
  if (!red && !repairs.length) return null;

  async function start() {
    try {
      await repair.mutateAsync();
      notify.success({ title: w.asked });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  return (
    <div
      className="flex flex-col gap-2 border-t border-shell-line pt-2"
      data-testid="code-change-repair"
      data-state={repairs.at(-1)?.state ?? "none"}
    >
      {running ? (
        <p className="flex items-center gap-2 text-[0.8125rem] text-brand-violet" role="status">
          <Loader2 className={cn("size-4 shrink-0", SPINNING)} aria-hidden="true" />
          {w.running}
        </p>
      ) : red ? (
        <div className="flex flex-col gap-2 rounded-md border border-state-danger/30 bg-white p-3">
          <p className="flex items-center gap-2 text-[0.8125rem] font-semibold text-brand-navy">
            <Wrench className="size-4 text-state-danger" aria-hidden="true" />
            {w.title}
          </p>
          <p className="text-[0.8125rem] text-shell-muted">{closed ? w.introClosed : w.intro}</p>
          {left <= 0 ? (
            <p className="text-xs text-state-warning">{fill(w.tooMany, { count: String(MAX_REPAIRS) })}</p>
          ) : approver ? (
            <div>
              <Button
                type="button"
                size="sm"
                disabled={repair.isPending}
                onClick={() => void start()}
                data-testid="code-change-repair-start"
              >
                {repair.isPending ? (
                  <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" />
                ) : (
                  <Wrench className="size-3.5" aria-hidden="true" />
                )}
                {closed ? w.startReopen : w.start}
              </Button>
            </div>
          ) : (
            <p className="text-xs text-shell-muted">{w.askApprover}</p>
          )}
        </div>
      ) : null}
      {repairs.length ? (
        <ol className="flex flex-col gap-2">
          {repairs.map((each, index) => (
            <RepairLine key={each.asked_at} repair={each} n={index + 1} />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

/** One repair, said: what failed, why, what it changed and where. */
function RepairLine({ repair, n }: { repair: CodeChangeRepair; n: number }) {
  const t = useDictionary();
  const w = t.codeChanges.repair;
  const failed = repair.failed ?? [];
  return (
    <li
      className="flex flex-col gap-1 rounded-md bg-white px-3 py-2 text-[0.8125rem] text-brand-navy"
      data-testid="code-change-repair-line"
      data-state={repair.state}
    >
      <p className="flex flex-wrap items-center gap-x-2">
        <span className="font-semibold">{fill(w.n, { n: String(n) })}</span>
        <span className={REPAIR_TONE[repair.state]}>{w.states[repair.state]}</span>
        {repair.commit ? (
          <span className="font-mono text-xs text-shell-muted">{fill(w.commit, { sha: short(repair.commit) })}</span>
        ) : null}
        {repair.model ? (
          <span className="text-xs text-shell-muted">{fill(w.by, { model: modelTitle(repair.model) })}</span>
        ) : null}
      </p>
      {failed.length ? (
        <p className="text-xs text-shell-muted">{fill(w.failed, { names: failed.join(", ") })}</p>
      ) : null}
      {repair.cause ? (
        <p>
          <span className="font-medium">{w.cause}</span> {repair.cause}
        </p>
      ) : null}
      {repair.state === "pushed" && repair.summary ? (
        <p>
          <span className="font-medium">{w.fix}</span> {repair.summary}
        </p>
      ) : null}
      {repair.said && repair.state !== "pushed" ? <p className="text-shell-muted">{repair.said}</p> : null}
      {repair.reopened ? <p className="text-xs text-shell-muted">{w.reopened}</p> : null}
      {(repair.files ?? []).map((file) => (
        <details key={file.path} className="rounded-md border border-shell-line" data-testid="code-change-repair-file">
          <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-2 py-1 text-xs">
            <FileCode2 className="size-3.5 text-shell-muted" aria-hidden="true" />
            <span className="min-w-0 font-mono break-all">{file.path}</span>
            <span className="text-[#15803d]">+{file.additions}</span>
            <span className="text-[#b91c1c]">−{file.deletions}</span>
          </summary>
          <pre className="max-h-80 overflow-auto border-t border-shell-line text-[0.75rem] leading-5">
            {diffLines(file.diff).map((line, index) => (
              <div key={index} className={`px-3 font-mono whitespace-pre ${LINE_CLASS[line.kind]}`}>
                {line.text || " "}
              </div>
            ))}
          </pre>
        </details>
      ))}
      {repair.state === "pushed" ? <p className="text-xs text-shell-muted">{w.checksAgain}</p> : null}
    </li>
  );
}

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : "—");

/**
 * Going back (2026-10-20): the versions kept — before it, with it, each
 * time a person went back, the change that undoes it — and the two ways
 * back. « Annuler ce changement »: not merged, its pull request closed;
 * merged, LEKA proposes the change that undoes it, to accept like any
 * other. « Revenir à la version précédente »: the repository's deployment
 * workflow started for the version before it, confirmed first.
 */
function GoBack({
  change,
  reverter,
  manager,
  refresh,
}: {
  change: CodeChange;
  reverter: CodeChange | null;
  manager: boolean;
  refresh: () => void;
}) {
  const t = useDictionary();
  const w = t.codeChanges.goBack;
  const { format: locale } = useLocale();
  const { undo, rollback } = useCodeChangeUndo();
  const [confirming, setConfirming] = useState(false);
  const follow = change.follow ?? null;
  const stage = follow?.stage ?? "checks";
  const merged = Boolean(follow?.merged_at);
  const commit = (sha: string) => `https://github.com/${change.repository}/commit/${sha}`;
  const rollbacks = change.rollbacks ?? [];
  const last = rollbacks.at(-1) ?? null;
  const running = last?.state === "queued" || last?.state === "in_progress";
  if (stage === "closed" && !merged) return null;

  async function act(kind: "undo" | "rollback") {
    try {
      await (kind === "undo" ? undo : rollback).mutateAsync(change.id);
      setConfirming(false);
      notify.success({ title: kind === "undo" ? (merged ? w.undoProposed : w.closed) : w.rollbackStarted });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  return (
    <div className="mt-1 flex flex-col gap-2 border-t border-shell-line pt-2" data-testid="code-change-go-back">
      <p className="text-[0.8125rem] font-semibold text-brand-navy">{w.title}</p>
      {merged ? (
        <ul className="flex flex-col gap-1 text-xs text-brand-navy" data-testid="code-change-versions">
          <li>
            <span className="text-shell-muted">{w.before} </span>
            {follow?.before_sha ? (
              <a className="font-mono underline" href={commit(follow.before_sha)} target="_blank" rel="noopener noreferrer">
                {short(follow.before_sha)}
              </a>
            ) : (
              "—"
            )}
          </li>
          <li>
            <span className="text-shell-muted">{w.with} </span>
            {follow?.merge_sha ? (
              <a className="font-mono underline" href={commit(follow.merge_sha)} target="_blank" rel="noopener noreferrer">
                {short(follow.merge_sha)}
              </a>
            ) : (
              "—"
            )}
            {follow?.merged_at ? ` · ${fill(w.mergedOn, { date: exactDate(locale, follow.merged_at) })}` : null}
          </li>
          {rollbacks.map((each) => (
            <li key={each.asked_at} data-testid="code-change-rollback">
              <span className="text-shell-muted">{fill(w.wentBack, { date: exactDate(locale, each.asked_at) })} </span>
              <span className="font-mono">{short(each.sha)}</span> — {w.runStates[each.state]}
              {each.url ? (
                <>
                  {" "}
                  <a className="underline" href={each.url} target="_blank" rel="noopener noreferrer">
                    {w.seeRun}
                  </a>
                </>
              ) : null}
            </li>
          ))}
          {reverter ? (
            <li data-testid="code-change-reverter">
              <span className="text-shell-muted">{w.undoneBy} </span>
              {reverter.pull_request_url ? (
                <a className="underline" href={reverter.pull_request_url} target="_blank" rel="noopener noreferrer">
                  {fill(w.pullRequest, { number: String(reverter.pull_request_number ?? "") })}
                </a>
              ) : (
                w.undoToAccept
              )}
            </li>
          ) : null}
        </ul>
      ) : null}
      {stage === "rolled_back" ? <p className="text-xs text-state-warning">{w.stillOnBranch}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        {!reverter ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={undo.isPending}
            onClick={() => void act("undo")}
            data-testid="code-change-undo"
          >
            <Undo2 className="size-3.5" aria-hidden="true" />
            {w.undo}
          </Button>
        ) : null}
        {merged && follow?.before_sha && change.deploys_allowed && !confirming ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={running || rollback.isPending}
            onClick={() => {
              // What its branch took since, read now: said before confirming.
              refresh();
              setConfirming(true);
            }}
            data-testid="code-change-rollback-open"
          >
            <RefreshCw className="size-3.5" aria-hidden="true" />
            {running ? w.rollingBack : w.rollback}
          </Button>
        ) : null}
      </div>
      <p className="text-xs text-shell-muted">{reverter ? null : merged ? w.undoHint : w.closeHint}</p>
      {confirming ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded-md border border-state-warning/40 bg-state-warning-soft p-2"
          role="group"
          aria-label={w.confirmTitle}
          data-testid="code-change-rollback-confirm"
        >
          <div className="min-w-0 flex-1 text-xs text-brand-navy">
            <p>{fill(w.confirm, { version: short(follow?.before_sha), branch: change.base_branch })}</p>
            {follow?.newer ? (
              <p className="mt-1 font-semibold text-state-danger" data-testid="code-change-rollback-newer">
                {fill(w.newer, { count: String(follow.newer), branch: change.base_branch })}
              </p>
            ) : null}
          </div>
          <Button type="button" size="sm" disabled={rollback.isPending} onClick={() => void act("rollback")}>
            {w.confirmYes}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
            {w.confirmNo}
          </Button>
        </div>
      ) : null}
      {merged && !change.deploys_allowed ? (
        <p className="text-xs text-shell-muted" data-testid="code-change-rollback-off">
          {manager ? w.rollbackOffAdmin : w.rollbackOff}
        </p>
      ) : null}
    </div>
  );
}

/** A change refused because its branch moved where it changes: written
 * again from its analysis, on the branch as it is now. */
function RewriteMoved({ runId }: { runId: string }) {
  const t = useDictionary();
  const w = t.codeChanges;
  const again = useRewriteChange(runId);
  const client = useQueryClient();

  async function rewrite() {
    try {
      await again.mutateAsync();
      await client.invalidateQueries({ queryKey: codeChangeKeys.all });
      notify.success({ title: w.rewriting });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={again.isPending}
      onClick={() => void rewrite()}
      data-testid="code-change-rewrite"
    >
      <RefreshCw className="size-3.5" aria-hidden="true" />
      {w.rewrite}
    </Button>
  );
}

function ChangeCard({ change, reverter, reverted }: { change: CodeChange; reverter: CodeChange | null; reverted: CodeChange | null }) {
  const t = useDictionary();
  const w = t.codeChanges;
  const { accept, reject } = useCodeChangeDecision();
  // Who manages the sources allows LEKA to open pull requests, in one click.
  const manager = usePermissions()?.includes("source:manage") ?? false;
  const allow = useAllowWrite();
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const [view, setView] = useState<"split" | "unified">("split");
  const busy = accept.isPending || reject.isPending;
  // Every modification, numbered across its files — each to unfold and read
  // before deciding; few, all open.
  const modifications = change.files.flatMap((file) => hunksOf(file.diff).map((hunk) => ({ file, hunk })));
  const [unfolded, setUnfolded] = useState<{ open: boolean; round: number }>({
    open: modifications.length <= 3,
    round: 0,
  });

  async function decide(approve: boolean) {
    try {
      const done = await (approve ? accept : reject).mutateAsync({ id: change.id, note: note.trim() || undefined });
      if (approve) {
        notify.success({
          title: w.opened,
          description: fill(w.openedHint, { number: String(done.pull_request_number ?? "") }),
        });
      } else {
        notify.success({ title: w.rejectedDone });
      }
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  async function allowPullRequests() {
    if (!change.source_id) return;
    try {
      await allow.mutateAsync({ sourceId: change.source_id, flag: "pull_requests" });
      await client.invalidateQueries({ queryKey: codeChangeKeys.all });
      notify.success({ title: w.allowedDone });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  const added = change.files.reduce((sum, f) => sum + f.additions, 0);
  const removed = change.files.reduce((sum, f) => sum + f.deletions, 0);
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-shell-line p-3" data-testid="code-change">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={TONE[change.status]}>{w.changeStatuses[change.status]}</Pill>
        {change.reverts ? <Pill tone="neutral">{w.goBack.undoing}</Pill> : null}
        <span className="text-[0.875rem] font-semibold text-brand-navy">{change.title}</span>
      </div>
      {reverted ? (
        <p className="text-xs text-shell-muted" data-testid="code-change-undoes">
          {fill(w.goBack.undoes, {
            title: reverted.title,
            number: String(reverted.pull_request_number ?? ""),
          })}
        </p>
      ) : null}
      <p className="text-xs text-shell-muted">
        {fill(w.where, {
          repository: change.repository,
          branch: change.base_branch,
          files: String(change.files.length),
          added: String(added),
          removed: String(removed),
        })}
      </p>
      {change.summary ? <p className="text-[0.8125rem] whitespace-pre-wrap text-brand-navy">{change.summary}</p> : null}
      <div className="flex gap-1" role="group" aria-label={w.view}>
        {(["split", "unified"] as const).map((each) => (
          <button
            key={each}
            type="button"
            aria-pressed={view === each}
            onClick={() => setView(each)}
            data-testid={`code-change-view-${each}`}
            className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40 ${
              view === each ? "bg-brand-violet-soft text-brand-violet" : "text-shell-nav hover:bg-shell-canvas"
            }`}
          >
            {each === "split" ? (
              <Columns2 className="size-3.5" aria-hidden="true" />
            ) : (
              <Rows3 className="size-3.5" aria-hidden="true" />
            )}
            {each === "split" ? w.split : w.unified}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2" data-testid="code-change-modifications">
        <p className="min-w-0 flex-1 text-[0.8125rem] font-medium text-brand-navy">
          {fill(w.modifications, {
            count: String(modifications.length),
            files: String(change.files.length),
            added: String(added),
            removed: String(removed),
          })}
        </p>
        <button
          type="button"
          className="text-xs font-medium text-shell-nav-active hover:underline"
          onClick={() => setUnfolded(({ round }) => ({ open: true, round: round + 1 }))}
        >
          {w.unfoldAll}
        </button>
        <button
          type="button"
          className="text-xs font-medium text-shell-nav-active hover:underline"
          onClick={() => setUnfolded(({ round }) => ({ open: false, round: round + 1 }))}
        >
          {w.foldAll}
        </button>
      </div>
      <ol className="flex flex-col gap-2">
        {modifications.map(({ file, hunk }, index) => (
          <li key={`${unfolded.round}-${file.path}-${index}`}>
            <Modification n={index + 1} file={file} hunk={hunk} open={unfolded.open} view={view} />
          </li>
        ))}
      </ol>
      {change.error ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="min-w-0 flex-1 text-xs text-state-danger" role="alert" data-testid="code-change-error">
            {(w.errors as Record<string, string>)[change.error] ?? change.error_detail ?? change.error}
          </p>
          {change.error === "changed_since" && change.status === "proposed" && change.run_id ? (
            <RewriteMoved runId={change.run_id} />
          ) : null}
        </div>
      ) : null}
      {change.status === "proposed" ? (
        <div className="flex flex-col gap-2">
          {!change.pull_requests_allowed ? (
            <div className="flex flex-wrap items-center gap-2" data-testid="code-change-not-allowed">
              <p className="min-w-0 flex-1 text-xs text-state-warning">
                {manager && change.source_id ? w.notAllowedAdmin : w.notAllowed}
              </p>
              {manager && change.source_id ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={allow.isPending}
                  onClick={() => void allowPullRequests()}
                  data-testid="code-change-allow"
                >
                  {w.allow}
                </Button>
              ) : null}
            </div>
          ) : null}
          <label className="flex flex-col gap-1 text-xs text-shell-muted">
            {w.note}
            <input
              className="h-8 rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
            />
          </label>
          <p className="text-xs text-shell-muted">{w.acceptHint}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" disabled={busy || !change.pull_requests_allowed} onClick={() => void decide(true)}>
              <Check className="size-3.5" aria-hidden="true" />
              {accept.isPending ? w.opening : w.accept}
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void decide(false)}>
              <X className="size-3.5" aria-hidden="true" />
              {w.reject}
            </Button>
          </div>
        </div>
      ) : null}
      {change.status === "applied" && change.pull_request_url ? (
        <>
          <a
            className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-brand-navy underline"
            href={change.pull_request_url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="code-change-pull-request"
          >
            <ExternalLink className="size-3.5" aria-hidden="true" />
            {fill(w.seePullRequest, { number: String(change.pull_request_number ?? "") })}
          </a>
          <PullRequestFollow change={change} reverter={reverter} manager={manager} />
        </>
      ) : null}
      {change.status === "rejected" && change.note ? (
        <p className="text-xs text-shell-muted">{fill(w.rejectedBecause, { note: change.note })}</p>
      ) : null}
    </li>
  );
}

export function CodeChanges({ intentionId }: { intentionId: string }) {
  const { data } = useCodeChanges(intentionId, true);
  return <ChangeList changes={data} />;
}

/** What one run proposed — the code-change agent's deliverable. */
export function RunCodeChanges({ runId }: { runId: string }) {
  const { data } = useRunCodeChanges(runId);
  return <ChangeList changes={data} />;
}

function ChangeList({ changes: data }: { changes: CodeChange[] | undefined }) {
  const t = useDictionary();
  const w = t.codeChanges;
  return (
    <Card title={w.title} icon={<GitPullRequest className="size-4 text-shell-muted" aria-hidden="true" />}>
      {!data?.length ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="flex flex-col gap-3" data-testid="code-changes">
          {data.map((change) => (
            <ChangeCard
              key={change.id}
              change={change}
              reverter={
                data.find(
                  (other) => other.reverts === change.id && (other.status === "proposed" || other.status === "applied"),
                ) ?? null
              }
              reverted={change.reverts ? (data.find((other) => other.id === change.reverts) ?? null) : null}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}
