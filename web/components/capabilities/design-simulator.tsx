"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Camera, Columns2, Download, Loader2, Monitor, Pencil, Smartphone, Square, Tablet } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "cn";

import { Button } from "@/components/ui/button";
import type { Design, DesignMockup } from "@/lib/agent-runs";
import { ApiError } from "@/lib/api";
import { agentRunKeys, useAgentRun, useAgentRunDesign, useCorrectDesign } from "@/lib/agent-runs-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";

/**
 * The designer's simulator: the screen as its code draws it today, beside
 * what it proposes — drawn by LEKA from its review and the code it read
 * (api: capabilities/mockups.py).
 *
 * Each mock-up is a whole page, shown in a frame sandboxed with no
 * permission at all: it runs no script, submits nothing, opens nothing, and
 * its own policy lets it fetch nothing — what it shows, it holds. Drawn at a
 * real width (a desktop, a tablet, a phone) and scaled to the space it has.
 * A capture is drawn by the browser itself, from the page, with no library.
 */

export const VIEWPORTS = {
  desktop: { width: 1280, height: 800, icon: Monitor },
  tablet: { width: 768, height: 1024, icon: Tablet },
  phone: { width: 390, height: 844, icon: Smartphone },
} as const;
export type Viewport = keyof typeof VIEWPORTS;

/** One mock-up, at a viewport's width, scaled to the space it is given. */
function Frame({ mockup, viewport, label }: { mockup: DesignMockup; viewport: Viewport; label: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [space, setSpace] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (typeof ResizeObserver === "undefined") {
      setSpace(el.clientWidth);
      return;
    }
    const watch = new ResizeObserver(([entry]) => setSpace(entry.contentRect.width));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const { width, height } = VIEWPORTS[viewport];
  const scale = space ? Math.min(1, space / width) : 1;
  return (
    <div ref={box} className="min-w-0" data-testid="design-frame" data-viewport={viewport}>
      <div
        className="relative mx-auto overflow-hidden rounded-lg border border-shell-line bg-white shadow-sm"
        style={{ height: height * scale, width: width * scale }}
      >
        <iframe
          title={label}
          sandbox=""
          srcDoc={mockup.page}
          className="absolute top-0 left-0 border-0"
          style={{ width, height, transform: `scale(${scale})`, transformOrigin: "top left" }}
        />
      </div>
    </div>
  );
}

const XML_UNSAFE = /[&<>]/g;
const XML_SAID: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };

/** A page as an SVG picture of it, the browser's own way to draw HTML on a
 * canvas: its styles and body in a foreignObject — `body` and `html` read as
 * the box that holds them. Nothing in it runs, nothing is fetched. */
export function svgOf(page: string, width: number, height: number): string {
  const doc = new DOMParser().parseFromString(page, "text/html");
  const styles = Array.from(doc.querySelectorAll("style"))
    .map((style) => style.textContent ?? "")
    .join("\n")
    .replace(/(^|[^\w.#-])(html|body)(?=[\s,{:.[#>+~]|$)/g, "$1.leka-page");
  const holder = doc.createElement("div");
  holder.setAttribute("class", `leka-page ${doc.body.getAttribute("class") ?? ""}`.trim());
  holder.setAttribute("style", `width:${width}px;height:${height}px;overflow:hidden;background:#fff;`);
  holder.append(...Array.from(doc.body.childNodes));
  const body = new XMLSerializer().serializeToString(holder);
  const css = styles.replace(XML_UNSAFE, (c) => XML_SAID[c]);
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">` +
    `<foreignObject width="100%" height="100%">` +
    `<div xmlns="http://www.w3.org/1999/xhtml"><style>${css}</style>${body}</div>` +
    `</foreignObject></svg>`
  );
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function fileName(screen: string, mockup: string): string {
  return `${screen} - ${mockup}`.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim();
}

async function capture(mockup: DesignMockup, viewport: Viewport, name: string): Promise<void> {
  const { width, height } = VIEWPORTS[viewport];
  const picture = new Image();
  picture.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgOf(mockup.page, width, height))}`;
  await picture.decode();
  const ratio = 2;
  const canvas = document.createElement("canvas");
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const pen = canvas.getContext("2d");
  if (!pen) throw new Error("no canvas");
  pen.scale(ratio, ratio);
  pen.drawImage(picture, 0, 0);
  const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/png"));
  if (!blob) throw new Error("no capture");
  save(blob, `${name}.png`);
}

const PILL =
  "rounded-lg px-3 py-1.5 text-[0.8125rem] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand-violet/40";

export function DesignSimulator({ runId }: { runId: string }) {
  const t = useDictionary();
  const w = t.agentRuns.design;
  const { data, isError } = useAgentRunDesign(runId);
  const [chosen, setChosen] = useState<number | null>(null);
  const [compare, setCompare] = useState(true);
  const [showing, setShowing] = useState<"before" | "after">("after");
  const [viewport, setViewport] = useState<Viewport | null>(null);
  const [captureFailed, setCaptureFailed] = useState(false);

  if (isError) {
    return (
      <p className="text-[0.8125rem] text-state-danger" role="alert" data-testid="design-error">
        {w.error}
      </p>
    );
  }
  if (!data) {
    return (
      <div className="h-80 animate-pulse rounded-xl bg-shell-canvas" aria-busy="true" aria-label={w.loading} />
    );
  }
  const design: Design = data;
  const index = Math.min(chosen ?? design.recommended, design.after.length - 1);
  const proposal = design.after[index];
  const view: Viewport = viewport ?? (design.viewport === "mobile" ? "phone" : "desktop");
  const viewports = w.viewports as Record<Viewport, string>;
  const label = (mockup: DesignMockup) => fill(w.frame, { name: mockup.name, screen: design.screen });
  const shown = compare || showing === "after" ? proposal : design.before;

  return (
    <section
      className="flex flex-col gap-4 rounded-xl border border-shell-line bg-white px-5 py-5"
      data-testid="design-simulator"
    >
      <header className="flex flex-col gap-1">
        <p className="text-[1.0625rem] font-semibold text-brand-navy">
          {w.title} · {design.screen}
        </p>
        <p className="text-[0.8125rem] text-shell-muted">{w.lead}</p>
        <p className="text-xs text-shell-muted">{w.reconstruction}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label={w.after} data-testid="design-proposals">
          {design.after.map((mockup, i) => (
            <button
              key={`${i}-${mockup.name}`}
              type="button"
              aria-pressed={i === index}
              onClick={() => {
                setChosen(i);
                setShowing("after");
              }}
              data-testid="design-proposal"
              className={cn(PILL, i === index ? "bg-brand-violet-soft text-brand-violet" : "text-shell-nav hover:bg-shell-canvas")}
            >
              {mockup.name}
              {i === design.recommended ? (
                <span
                  className="ml-1.5 rounded-full bg-state-success/15 px-1.5 py-0.5 text-[0.6875rem] font-semibold text-state-success"
                  data-testid="design-recommended"
                >
                  {w.recommended}
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <span className="mx-1 h-5 w-px bg-shell-line" aria-hidden="true" />
        <div className="flex gap-1" role="group" aria-label={w.compare}>
          <button
            type="button"
            aria-pressed={compare}
            onClick={() => setCompare(true)}
            data-testid="design-compare"
            className={cn(PILL, compare ? "bg-shell-canvas text-brand-navy" : "text-shell-nav hover:bg-shell-canvas")}
          >
            <Columns2 className="mr-1 inline size-3.5" aria-hidden="true" />
            {w.compare}
          </button>
          <button
            type="button"
            aria-pressed={!compare}
            onClick={() => setCompare(false)}
            data-testid="design-single"
            className={cn(PILL, !compare ? "bg-shell-canvas text-brand-navy" : "text-shell-nav hover:bg-shell-canvas")}
          >
            <Square className="mr-1 inline size-3.5" aria-hidden="true" />
            {w.single}
          </button>
        </div>
        {!compare ? (
          <div className="flex gap-1" role="group" aria-label={w.single}>
            {(["before", "after"] as const).map((side) => (
              <button
                key={side}
                type="button"
                aria-pressed={showing === side}
                onClick={() => setShowing(side)}
                data-testid={`design-show-${side}`}
                className={cn(PILL, showing === side ? "bg-shell-canvas text-brand-navy" : "text-shell-nav hover:bg-shell-canvas")}
              >
                {side === "before" ? w.before : proposal.name}
              </button>
            ))}
          </div>
        ) : null}
        <span className="mx-1 h-5 w-px bg-shell-line" aria-hidden="true" />
        <div className="flex gap-1" role="group" aria-label={viewports[view]}>
          {(Object.keys(VIEWPORTS) as Viewport[]).map((each) => {
            const Icon = VIEWPORTS[each].icon;
            return (
              <button
                key={each}
                type="button"
                aria-pressed={view === each}
                aria-label={viewports[each]}
                title={viewports[each]}
                onClick={() => setViewport(each)}
                data-testid={`design-viewport-${each}`}
                className={cn(PILL, "px-2", view === each ? "bg-shell-canvas text-brand-navy" : "text-shell-nav hover:bg-shell-canvas")}
              >
                <Icon className="size-4" aria-hidden="true" />
              </button>
            );
          })}
        </div>
        <div className="ml-auto flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => save(new Blob([shown.page], { type: "text/html" }), `${fileName(design.screen, shown.name)}.html`)}
            data-testid="design-download"
          >
            <Download className="size-3.5" aria-hidden="true" />
            {w.downloadHtml}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setCaptureFailed(false);
              capture(shown, view, fileName(design.screen, shown.name)).catch(() => setCaptureFailed(true));
            }}
            data-testid="design-capture"
          >
            <Camera className="size-3.5" aria-hidden="true" />
            {w.capture}
          </Button>
        </div>
      </div>
      {captureFailed ? (
        <p className="text-xs text-state-warning" role="status">
          {w.captureFailed}
        </p>
      ) : null}

      {compare ? (
        <div className={cn("grid gap-4", view === "desktop" ? "xl:grid-cols-2" : "md:grid-cols-2")}>
          {[design.before, proposal].map((mockup, i) => (
            <figure key={i === 0 ? "before" : `after-${index}`} className="flex min-w-0 flex-col gap-2">
              <figcaption className="text-[0.8125rem] font-semibold text-brand-navy">
                {i === 0 ? w.before : `${w.after} · ${mockup.name}`}
              </figcaption>
              <Frame mockup={mockup} viewport={view} label={label(mockup)} />
            </figure>
          ))}
        </div>
      ) : (
        <figure className="flex min-w-0 flex-col gap-2">
          <figcaption className="text-[0.8125rem] font-semibold text-brand-navy">
            {showing === "before" ? w.before : `${w.after} · ${proposal.name}`}
          </figcaption>
          <Frame mockup={shown} viewport={view} label={label(shown)} />
        </figure>
      )}

      <Correction runId={runId} design={design} shown={showing === "before" && !compare ? "before" : String(index)} />

      <dl className="grid gap-3 text-[0.8125rem] md:grid-cols-3" data-testid="design-proposal-detail">
        {(
          [
            [w.axis, proposal.axis],
            [w.when, proposal.when],
            [w.cost, proposal.cost],
          ] as const
        ).map(([term, said]) =>
          said ? (
            <div key={term} className="rounded-lg bg-shell-canvas px-3 py-2">
              <dt className="text-xs font-semibold text-shell-muted">{term}</dt>
              <dd className="text-brand-navy">{said}</dd>
            </div>
          ) : null,
        )}
      </dl>
      {index === design.recommended && design.why ? (
        <p className="text-[0.875rem] text-brand-navy" data-testid="design-why">
          <span className="font-semibold">{w.why} : </span>
          {design.why}
        </p>
      ) : null}
      {index === design.recommended && design.changes.length ? (
        <div className="overflow-x-auto">
          <p className="mb-2 text-[0.8125rem] font-semibold text-brand-navy">{w.changes}</p>
          <table className="w-full min-w-[40rem] text-left text-[0.8125rem]" data-testid="design-changes">
            <thead className="text-xs text-shell-muted">
              <tr>
                <th className="py-1 pr-3 font-semibold">{w.where}</th>
                <th className="py-1 pr-3 font-semibold">{w.beforeCol}</th>
                <th className="py-1 pr-3 font-semibold">{w.afterCol}</th>
                <th className="py-1 font-semibold">{w.whyCol}</th>
              </tr>
            </thead>
            <tbody>
              {design.changes.map((change, i) => (
                <tr key={i} className="border-t border-shell-line align-top">
                  <td className="py-1.5 pr-3 font-mono text-xs text-shell-muted">{change.where}</td>
                  <td className="py-1.5 pr-3 text-brand-navy">{change.before}</td>
                  <td className="py-1.5 pr-3 text-brand-navy">{change.after}</td>
                  <td className="py-1.5 text-shell-muted">{change.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

/** A part of a mock-up to correct, asked in words — the logo, a menu, a
 * label —, LEKA drawing that mock-up again, the rest as it was (2026-10-19,
 * Karim: « lui demander de corriger certaines parties de l'écran depuis la
 * proposition »). */
function Correction({ runId, design, shown }: { runId: string; design: Design; shown: string }) {
  const t = useDictionary();
  const w = t.agentRuns.design;
  const client = useQueryClient();
  const run = useAgentRun(runId).data;
  const correct = useCorrectDesign(runId);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const correcting = run?.correcting ?? null;
  const was = useRef(correcting);
  // Corrected: the mock-ups read again, as they now are.
  useEffect(() => {
    if (was.current && !correcting) void client.invalidateQueries({ queryKey: agentRunKeys.design(runId) });
    was.current = correcting;
  }, [correcting, client, runId]);
  const named = (each: string) => (each === "before" ? w.before : (design.after[Number(each)]?.name ?? each));
  const chosen = target ?? shown;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (note.trim().length < 3) return;
    try {
      await correct.mutateAsync({ target: chosen, note: note.trim() });
      setNote("");
      setOpen(false);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.correctionFailed });
    }
  }

  const failed = run?.correction_failed ?? null;
  const errors = t.intentions.deliverable.changeErrors as Record<string, string>;
  return (
    <div className="flex flex-col gap-2" data-testid="design-correction">
      {correcting ? (
        <p className="flex items-center gap-2 text-[0.8125rem] text-shell-muted" role="status" data-testid="design-correcting">
          <Loader2 className={cn("size-4", SPINNING)} aria-hidden="true" />
          {fill(w.correcting, { name: named(correcting) })}
        </p>
      ) : open ? (
        <form className="flex flex-col gap-2 rounded-lg border border-shell-line bg-shell-canvas/50 p-3" onSubmit={(e) => void submit(e)}>
          <label className="flex flex-col gap-1 text-xs text-shell-muted">
            {w.correctionWhat}
            <textarea
              className="min-h-16 rounded-md border border-shell-line bg-white px-2 py-1.5 text-base text-brand-navy md:text-[0.8125rem]"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={w.correctionPlaceholder}
              maxLength={1000}
              required
            />
          </label>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-shell-muted">
              {w.correctionOn}
              <select
                className="h-8 rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy"
                value={chosen}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="before">{w.before}</option>
                {design.after.map((mockup, i) => (
                  <option key={i} value={String(i)}>
                    {mockup.name}
                  </option>
                ))}
              </select>
            </label>
            <Button type="submit" size="sm" disabled={correct.isPending || note.trim().length < 3} data-testid="design-correct">
              {correct.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
              {w.correct}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
              {w.correctionCancel}
            </Button>
          </div>
        </form>
      ) : (
        <div>
          <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="design-correction-open">
            <Pencil className="size-3.5" aria-hidden="true" />
            {w.correctionOpen}
          </Button>
        </div>
      )}
      {failed && !correcting ? (
        <p className="text-xs text-state-danger" role="alert" data-testid="design-correction-failed">
          {fill(w.correctionFailedWhy, { why: errors[failed] ?? failed })}
          {run?.correction_said ? <span className="block font-mono text-shell-muted">{run.correction_said}</span> : null}
        </p>
      ) : null}
      {run?.corrections?.length ? (
        <ul className="flex flex-col gap-0.5 text-xs text-shell-muted" data-testid="design-corrections">
          {run.corrections.map((each, i) => (
            <li key={i}>
              {fill(w.corrected, { name: named(each.target), note: each.note })}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

