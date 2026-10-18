"use client";

import { Check, Columns2, ExternalLink, FileCode2, GitPullRequest, Rows3, X } from "lucide-react";
import { useState } from "react";

import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { CodeChange, CodeChangeFile } from "@/lib/code-changes";
import { useCodeChangeDecision, useCodeChanges, useRunCodeChanges } from "@/lib/code-changes-queries";
import { type SplitCell, splitRows } from "@/lib/diff";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

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

function FileDiff({ file, open, view }: { file: CodeChangeFile; open: boolean; view: "split" | "unified" }) {
  const t = useDictionary();
  const w = t.codeChanges;
  return (
    <details className="rounded-md border border-shell-line bg-white" data-testid="code-change-file" open={open}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-[0.8125rem]">
        <FileCode2 className="size-3.5 text-shell-muted" aria-hidden="true" />
        <span className="font-mono text-brand-navy">{file.path}</span>
        <span className="text-xs text-shell-muted">{w.statuses[file.status]}</span>
        <span className="text-xs text-[#15803d]">+{file.additions}</span>
        <span className="text-xs text-[#b91c1c]">−{file.deletions}</span>
        {file.why ? <span className="w-full text-xs text-shell-muted">{file.why}</span> : null}
      </summary>
      {view === "split" ? (
        <SplitDiff diff={file.diff} />
      ) : (
        <pre className="max-h-[28rem] overflow-auto border-t border-shell-line text-[0.75rem] leading-5" data-testid="code-change-diff">
          {diffLines(file.diff).map((line, index) => (
            <div key={index} className={`px-3 font-mono whitespace-pre ${LINE_CLASS[line.kind]}`} data-kind={line.kind}>
              {line.text || " "}
            </div>
          ))}
        </pre>
      )}
    </details>
  );
}

function ChangeCard({ change }: { change: CodeChange }) {
  const t = useDictionary();
  const w = t.codeChanges;
  const { accept, reject } = useCodeChangeDecision();
  const [note, setNote] = useState("");
  const [view, setView] = useState<"split" | "unified">("split");
  const busy = accept.isPending || reject.isPending;

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

  const added = change.files.reduce((sum, f) => sum + f.additions, 0);
  const removed = change.files.reduce((sum, f) => sum + f.deletions, 0);
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-shell-line p-3" data-testid="code-change">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={TONE[change.status]}>{w.changeStatuses[change.status]}</Pill>
        <span className="text-[0.875rem] font-semibold text-brand-navy">{change.title}</span>
      </div>
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
      <div className="flex flex-col gap-2">
        {change.files.map((file) => (
          <FileDiff key={file.path} file={file} open={change.files.length <= 3} view={view} />
        ))}
      </div>
      {change.error ? (
        <p className="text-xs text-state-danger" role="alert" data-testid="code-change-error">
          {(w.errors as Record<string, string>)[change.error] ?? change.error_detail ?? change.error}
        </p>
      ) : null}
      {change.status === "proposed" ? (
        <div className="flex flex-col gap-2">
          {!change.pull_requests_allowed ? (
            <p className="text-xs text-state-warning" data-testid="code-change-not-allowed">
              {w.notAllowed}
            </p>
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
            <ChangeCard key={change.id} change={change} />
          ))}
        </ul>
      )}
    </Card>
  );
}
