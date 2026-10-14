"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ArrowUp, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { cn } from "cn";
import { Wordmark } from "@/components/brand/logo";
import { summaryOf } from "@/components/capabilities/catalogue";
import { SourceLogo } from "@/components/sources/source-logo";
import { buttonVariants } from "@/components/ui/button";
import { SAID, splitSaid } from "@/components/v2/said";
import { Thread } from "@/components/v2/thread";
import { routes } from "@/config/routes";
import { V2 } from "@/config/v2-routes";
import { ApiError } from "@/lib/api";
import { useAddOns } from "@/lib/billing-queries";
import { BUDGET } from "@/lib/context";
import type { Environment } from "@/lib/environment";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { intentions } from "@/lib/intentions/api";
import { intentionKeys, useIntention } from "@/lib/intentions/queries";
import type { SourceKind } from "@/lib/sources";

/**
 * The new home (2026-10-14, the product call's Lot 6): « Connecte tes
 * sources, puis demande ce que tu veux ». LEKA's logo, tied to the sources
 * it reads; one bar; the person's agents under it, a click away. What is
 * asked is answered under the bar, as a thread — no « Pour affiner », no
 * « Lancer l'analyse », no « Suivre l'analyse »: asked, it is analysed.
 */
export function Home() {
  const t = useDictionary();
  const w = t.v2;
  const router = useRouter();
  const search = useSearchParams();
  const open = search?.get("i") ?? "";
  const client = useQueryClient();
  const current = useIntention(open);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bar = useRef<HTMLTextAreaElement>(null);
  // One key per sentence (LEKA-443): sent twice, it is one intention.
  const requestKey = useRef<{ text: string; key: string } | null>(null);

  // A reply carries on the exchange while LEKA may take it again; once its
  // agents work on it, or it is closed, what is typed is a new request.
  const replying = Boolean(current.data?.journey.controls.includes("ask_again"));

  async function send() {
    const said = text.trim();
    if (!said || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (open && current.data && replying) {
        const made = await intentions.ask(open, {
          text: [...splitSaid(current.data.text), said].join(SAID),
          services: [],
          sources: [],
          limit: BUDGET,
        });
        client.setQueryData(intentionKeys.one(open), made.intention);
        void client.invalidateQueries({ queryKey: intentionKeys.all });
      } else {
        if (requestKey.current?.text !== said) {
          requestKey.current = { text: said, key: crypto.randomUUID() };
        }
        const made = await intentions.create(
          { text: said, services: [], sources: [], limit: BUDGET },
          requestKey.current.key,
        );
        client.setQueryData(intentionKeys.one(made.intention.id), made.intention);
        void client.invalidateQueries({ queryKey: intentionKeys.all });
        router.push(V2.thread(made.intention.id));
      }
      setText("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        setError(caught.code === "off_topic" ? t.intentions.brief.offTopic : t.intent.nothing);
      } else {
        setError(caught instanceof ApiError ? caught.message : String(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  /** « /architecte » put first in the bar, the rest of the request kept. */
  function insert(slash: string) {
    setText((was) => `${slash} ${was.replace(/^\/\S+\s*/, "")}`);
    bar.current?.focus();
  }

  return (
    <div className={cn("mx-auto flex w-full max-w-3xl flex-col items-center", open ? "pt-4" : "pt-[6vh]")}>
      <title>{`${w.home} · LEKA`}</title>
      {open ? null : <Constellation />}
      {open ? null : (
        <p className="mt-6 text-center text-[1.0625rem] text-shell-accent-muted">{w.promise}</p>
      )}
      <form
        className="mt-5 w-full"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor="v2-ask" className="sr-only">
          {w.askLabel}
        </label>
        <div className="flex items-end gap-2 rounded-2xl border border-shell-line bg-white p-2 shadow-sm focus-within:border-brand-violet focus-within:ring-3 focus-within:ring-brand-violet/20">
          <textarea
            id="v2-ask"
            ref={bar}
            rows={1}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder={open && replying ? w.replyPlaceholder : w.askPlaceholder}
            className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-[1rem] text-brand-navy outline-none placeholder:text-shell-muted"
            data-testid="v2-ask"
            dir="auto"
          />
          <button
            type="submit"
            disabled={busy || !text.trim()}
            aria-label={w.send}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-violet text-white outline-none hover:bg-brand-violet/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-40"
            data-testid="v2-send"
          >
            <ArrowUp className="size-5" aria-hidden="true" />
          </button>
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-[0.8125rem] text-state-danger" data-testid="v2-ask-error">
            {error}
          </p>
        ) : null}
      </form>
      <AgentChips onPick={insert} />
      {open ? (
        <div className="mt-6 w-full">
          <div className="mb-3 flex justify-end">
            <Link href={V2.home} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="v2-new">
              <Plus className="size-4" aria-hidden="true" />
              {w.newAsk}
            </Link>
          </div>
          <Thread id={open} />
        </div>
      ) : null}
    </div>
  );
}

// ── LEKA, tied to its sources ─────────────────────────────────────────────

const SIZE = 260;
const RADIUS = 104;
const MOST = 8;

/** The logo at the centre, each source connected around it, a line from
 * one to the other: what LEKA reads, seen. A source that needs a look is
 * drawn so. */
function Constellation() {
  const t = useDictionary();
  const w = t.v2;
  const environment = useEnvironment();
  const sources = environment.data?.sources ?? [];
  const shown = sources.slice(0, MOST);
  const more = sources.length - shown.length;
  const at = (index: number) => {
    const angle = (index / Math.max(shown.length, 1)) * 2 * Math.PI - Math.PI / 2;
    return { x: SIZE / 2 + RADIUS * Math.cos(angle), y: SIZE / 2 + RADIUS * Math.sin(angle) };
  };
  return (
    <div className="flex flex-col items-center" data-testid="v2-constellation">
      <div className="relative aspect-square w-[min(260px,70vw)]">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 size-full" aria-hidden="true">
          {shown.map((source, index) => {
            const { x, y } = at(index);
            return (
              <line
                key={source.id}
                x1={SIZE / 2}
                y1={SIZE / 2}
                x2={x}
                y2={y}
                className={troubled(source) ? "stroke-[#f59e0b]" : "stroke-brand-violet/30"}
                strokeWidth={1.5}
                strokeDasharray={source.state === "never" ? "4 4" : undefined}
              />
            );
          })}
        </svg>
        <div className="absolute top-1/2 left-1/2 flex w-[46%] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl bg-white px-3 py-3 shadow-sm ring-1 ring-shell-line">
          <Wordmark className="h-auto w-full" priority />
        </div>
        {shown.map((source, index) => {
          const { x, y } = at(index);
          return (
            <span
              key={source.id}
              title={source.name}
              className={cn(
                "absolute flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white shadow-sm ring-1",
                troubled(source) ? "ring-[#f59e0b]" : "ring-shell-line",
              )}
              style={{ left: `${(x / SIZE) * 100}%`, top: `${(y / SIZE) * 100}%` }}
              data-testid="v2-constellation-source"
            >
              <SourceLogo kind={source.kind as SourceKind} className="size-5" />
            </span>
          );
        })}
      </div>
      {environment.data ? (
        sources.length ? (
          <p className="text-[0.8125rem] text-shell-muted">
            {fill(w.connected, { count: sources.length })}
            {more > 0 ? ` (+${more})` : null}
          </p>
        ) : (
          <div className="flex flex-col items-center gap-2 text-center">
            <p className="text-[0.8125rem] text-shell-muted">{w.noSources}</p>
            <Link href={routes.sources()} className={buttonVariants({ size: "sm" })} data-testid="v2-connect">
              {w.connect}
            </Link>
          </div>
        )
      ) : null}
    </div>
  );
}

type TwinSource = NonNullable<Environment["sources"]>[number];

function troubled(source: TwinSource): boolean {
  return ["error", "degraded", "stale"].includes(source.state);
}

// ── The person's agents ──────────────────────────────────────────────────

/** « /architecte »: an agent's first word, plain — its whole name when two
 * agents share the first. */
export function slashes(titles: readonly string[]): string[] {
  const plain = (words: string) =>
    words
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  const first = titles.map((title) => plain(title.split(/\s+/)[0] ?? title));
  return titles.map((title, index) =>
    first.filter((one) => one === first[index]).length > 1
      ? `/${plain(title)}`
      : `/${first[index]}`,
  );
}

const MOST_CHIPS = 6;

function AgentChips({ onPick }: { onPick: (slash: string) => void }) {
  const t = useDictionary();
  const w = t.v2;
  const offers = useAddOns();
  const owned = (offers.data?.agents ?? []).filter((agent) => agent.owned);
  // Few buttons (2026-10-14): the first ones; the others behind « Voir tous ».
  const mine = owned.slice(0, MOST_CHIPS);
  const said = slashes(owned.map((agent) => agent.title));
  if (!offers.data) return <div className="mt-4 h-8" aria-hidden="true" />;
  return (
    <div className="mt-4 flex w-full flex-wrap items-center justify-center gap-2" data-testid="v2-agents">
      <span className="text-xs font-medium tracking-wide text-shell-muted uppercase">{w.agents}</span>
      {mine.length ? (
        mine.map((agent, index) => (
          <button
            key={agent.key}
            type="button"
            onClick={() => onPick(said[index])}
            title={summaryOf(t, agent)}
            aria-label={fill(w.insert, { slash: said[index] })}
            className="rounded-full border border-shell-line bg-white px-3 py-1 text-[0.8125rem] text-brand-navy outline-none hover:border-brand-violet hover:text-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/40"
            data-testid="v2-agent-chip"
            data-key={agent.key}
          >
            {said[index]}
          </button>
        ))
      ) : (
        <span className="text-[0.8125rem] text-shell-muted">{w.agentsNone}</span>
      )}
      <Link
        href={V2.agents}
        className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-brand-violet hover:underline"
        data-testid="v2-see-all"
      >
        {w.seeAll}
        <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
      </Link>
    </div>
  );
}
