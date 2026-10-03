"use client";

import {
  Activity,
  AppWindow,
  Archive,
  Boxes,
  Braces,
  ChartColumn,
  Clock,
  Cloud,
  Cog,
  CreditCard,
  Database,
  ExternalLink,
  Inbox,
  LayoutGrid,
  type LucideIcon,
  Mail,
  Maximize2,
  MessageSquare,
  Minus,
  Network,
  Play,
  Plus,
  Search,
  Server,
  Shuffle,
  Sparkles,
  Split,
  Users,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";

import { cn } from "cn";

import {
  Card,
  CardLink,
  EventList,
  type EventRow,
  entityHref,
  eventRows,
  IconTile,
  Logo,
  type TileTone,
} from "@/components/environment/parts";
import { TONES } from "@/components/knowledge/status";
import { hasSourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { routes } from "@/config/routes";
import { useEntitySheet } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type {
  Architecture,
  ArchitectureCard,
  ArchitectureColumn,
  ArchitectureGroup,
  ArchitectureLink,
} from "@/lib/knowledge-graph";
import type { SourceKind } from "@/lib/sources";

/**
 * "Mon environnement", Architecture (LEKA-369): what the company runs, in
 * columns — its code, its applications and services, its data and storage,
 * its cloud, the services outside it relies on — as GET
 * /knowledge/architecture lays it out. Every card, figure and named link is
 * the API's: this file draws them.
 *
 * At rest, one arrow a column — what a card's links there mostly are, or
 * what many cards share, from their column — and the chosen card's own
 * links over it, each named. Below a large screen the columns stack and the
 * arrows go: the chosen card's relations are said in its panel, and every
 * link in words for screen readers.
 */

type Dict = ReturnType<typeof useDictionary>;
type Words = Dict["environment"]["architecture"];

/** Many cards sharing one arrow are drawn from their column: past this. */
const SHARED = 3;
/** The column's own links drawn at rest: a few, else only the chosen card's. */
const SAME_COLUMN_AT_REST = 24;
const ZOOMS = [0.7, 0.85, 1, 1.15, 1.3] as const;
/** Several links' names, in one order: what is stored before what is sent. */
const ROLE_ORDER = [
  "source_code",
  "routes",
  "calls",
  "deployed_on",
  "hosted_on",
  "stores",
  "queue",
  "cache",
  "files",
  "email",
  "uses",
  "depends",
  "monitored_by",
  "part_of",
];

const KIND_ICONS: Record<string, LucideIcon> = {
  api: Server,
  web: AppWindow,
  worker: Cog,
  scheduler: Clock,
  job: Play,
  proxy: Shuffle,
  application: LayoutGrid,
  service: Server,
  repository: Boxes,
  database: Database,
  cache: Zap,
  queue: Inbox,
  search: Search,
  storage: Archive,
  instance: Server,
  cluster: Boxes,
  function: Braces,
  bucket: Archive,
  load_balancer: Split,
  network: Network,
  resource: Cloud,
  email: Mail,
  payments: CreditCard,
  ai: Sparkles,
  messaging: MessageSquare,
  monitoring: Activity,
  analytics: ChartColumn,
};

const KIND_TONES: Record<string, TileTone> = {
  services: "success",
  data: "violet",
  cloud: "warning",
  external: "info",
};

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  operational: "success",
  attention: "warning",
  incident: "danger",
  unmonitored: "neutral",
};

/** An engine, by the name its card says, as a source's logo. */
const ENGINE_LOGOS: Record<string, SourceKind> = {
  postgresql: "postgresql",
  "aurora postgresql": "postgresql",
  mysql: "mysql",
  "aurora mysql": "mysql",
  mariadb: "mariadb",
  mongodb: "mongodb",
  oracle: "oracle",
  "sql server": "sqlserver",
};

function kindIcon(kind: string): LucideIcon {
  return KIND_ICONS[kind] ?? Server;
}

function kindLabel(w: Words, card: Pick<ArchitectureCard, "kind" | "column" | "group">): string {
  const kind = (w.kinds as Record<string, string>)[card.kind] ?? card.kind;
  if (card.column !== "cloud") return kind;
  const product = (w.products as Record<string, Record<string, string>>)[card.group]?.[card.kind];
  return product ? `${product} · ${kind}` : kind;
}

function roleWords(w: Words, role: string) {
  return (
    (w.roles as Record<string, { label: string; out: string; in: string; sentence: string }>)[
      role
    ] ?? { label: role, out: role, in: role, sentence: role }
  );
}

function engineLogo(card: ArchitectureCard): SourceKind | null {
  const engine = card.technology[0]?.toLowerCase().replace(/\s+[\d.]+$/, "");
  const kind = engine ? ENGINE_LOGOS[engine] : undefined;
  return kind && hasSourceLogo(kind) ? kind : null;
}

function cardName(card: ArchitectureCard): string {
  if (card.type === "tool" && hasSourceLogo(card.name)) return sourceTitle(card.name as SourceKind);
  // A repository by its own name — Leka of Haitam-elh/Leka — the owner under it.
  if (card.column === "code") return card.name.split("/").at(-1) ?? card.name;
  return card.name;
}

function bytes(w: Words, value: number, number: Intl.NumberFormat): string {
  const units = [
    [1024 ** 3, w.stats.bytes.gb],
    [1024 ** 2, w.stats.bytes.mb],
    [1024, w.stats.bytes.kb],
  ] as const;
  for (const [size, words] of units) {
    if (value >= size) {
      return fill(words, { n: number.format(Math.round((value / size) * 10) / 10) });
    }
  }
  return fill(w.stats.bytes.b, { n: number.format(value) });
}

function statsLine(w: Words, card: ArchitectureCard, number: Intl.NumberFormat): string[] {
  const said: string[] = [];
  for (const [name, value] of Object.entries(card.stats)) {
    if (name === "size_bytes") said.push(bytes(w, value, number));
    else {
      const words = (w.stats as Record<string, unknown>)[name];
      if (typeof words === "string") said.push(fill(words, { count: value }));
    }
  }
  return said;
}

// ── the figures above ───────────────────────────────────────────────────────

/** The mockup's tiles: how many of each kind, and how they are doing. */
export function ArchitectureFigures({ data }: { data: Architecture | undefined }) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const { locale } = useLocale();
  const value = (n: number | undefined) => (n === undefined ? "—" : String(n));
  const figures = data?.figures;
  const providers = Object.keys(figures?.providers ?? {});
  const provider = providers.length === 1 ? providers[0] : null;
  const tiles: { id: string; icon: React.ReactNode; value: string; label: string }[] = [
    {
      id: "services",
      icon: <IconTile icon={Boxes} tone="info" />,
      value: value(figures ? figures.services + figures.applications : undefined),
      label: w.figures.services,
    },
    {
      id: "repositories",
      icon: (
        <span className="flex size-10 items-center justify-center rounded-lg bg-shell-canvas">
          <Logo kind="github" className="size-6" />
        </span>
      ),
      value: value(figures?.repositories),
      label: w.figures.repositories,
    },
    {
      id: "databases",
      icon: <IconTile icon={Database} tone="violet" />,
      value: value(figures ? figures.databases + figures.stores : undefined),
      label: w.figures.databases,
    },
    {
      id: "cloud",
      icon:
        provider && hasSourceLogo(provider) ? (
          <span className="flex size-10 items-center justify-center rounded-lg bg-state-warning-soft">
            <Logo kind={provider} className="size-6" />
          </span>
        ) : (
          <IconTile icon={Cloud} tone="warning" />
        ),
      value: value(figures?.cloud_resources),
      label: provider
        ? fill(w.figures.cloud, {
            provider: (w.providers as Record<string, string>)[provider] ?? provider,
          })
        : w.figures.cloudMixed,
    },
    {
      id: "teams",
      icon: <IconTile icon={Users} tone="violet" />,
      value: value(figures?.teams),
      label: w.figures.teams,
    },
  ];
  const health = data?.health;
  const total = health
    ? health.operational + health.attention + health.incident + (health.unmonitored ?? 0)
    : 0;
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 });
  const lines = (["operational", "attention", "incident", "unmonitored"] as const).filter(
    (state) => state !== "unmonitored" || (health?.unmonitored ?? 0) > 0,
  );

  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {tiles.map((tile) => (
        <li
          key={tile.id}
          className="flex items-center gap-3 rounded-xl border border-shell-line bg-white p-4"
          data-testid={`arch-figure-${tile.id}`}
        >
          {tile.icon}
          <span className="min-w-0">
            <span className="block text-[1.5rem] leading-7 font-bold text-brand-navy tabular-nums">
              {tile.value}
            </span>
            <span className="block text-[0.8125rem] leading-4 text-brand-navy">{tile.label}</span>
          </span>
        </li>
      ))}
      <li
        className="rounded-xl border border-shell-line bg-white px-4 py-3"
        data-testid="arch-figure-health"
        aria-label={w.health.title}
      >
        {health && total > 0 ? (
          <ul className="flex flex-col gap-1">
            {lines.map((state) => (
              <li key={state} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                <span
                  aria-hidden="true"
                  className={cn("size-2.5 rounded-full", TONES[STATUS_TONE[state]].dot)}
                />
                <span className="flex-1">{w.health[state]}</span>
                <span className="font-semibold tabular-nums">
                  {percent.format((health[state] ?? 0) / total)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-2 text-[0.8125rem] text-shell-muted">
            {health ? w.health.none : "—"}
          </p>
        )}
      </li>
    </ul>
  );
}

// ── the board: the canvas, the chosen card, the widgets ────────────────────

/**
 * The architecture: its canvas, the chosen card's panel beside it, and —
 * on the screen's tab — the four widgets under them. `detailed`: every
 * card's own arrows, none shared, as the detailed map draws them.
 */
export function ArchitectureBoard({
  data,
  events,
  detailed = false,
}: {
  data: Architecture;
  /** Recent activity, from the environment screen (GET /ingestion/enrichment/environment). */
  events?: readonly EventRow[];
  detailed?: boolean;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const byId = useMemo(() => new Map(data.cards.map((card) => [card.id, card])), [data.cards]);
  const first = useMemo(
    () =>
      data.cards.find((card) => card.column === "services" && card.kind === "api") ??
      data.cards.find((card) => card.column === "services") ??
      null,
    [data.cards],
  );
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);
  // Nothing chosen yet: the API, as the mockup opens on it. Closed: none.
  const selected = chosen === undefined ? (first?.id ?? null) : chosen;
  const card = selected ? (byId.get(selected) ?? null) : null;

  if (data.cards.length === 0) {
    return (
      <section className="rounded-xl border border-dashed border-shell-line bg-white p-8 text-center">
        <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.empty.title}</h2>
        <p className="mx-auto mt-2 max-w-xl text-[0.875rem] text-shell-muted">{w.empty.body}</p>
        <Link
          href={routes.sources()}
          className="mt-4 inline-flex rounded-lg bg-brand-navy px-4 py-2 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {t.environment.map.connect}
        </Link>
      </section>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div
        className={cn(
          "grid gap-4",
          card ? "xl:grid-cols-[minmax(0,1fr)_20rem]" : "grid-cols-1",
        )}
      >
        <Canvas
          data={data}
          byId={byId}
          selected={selected}
          onSelect={setChosen}
          detailed={detailed}
        />
        {card ? (
          <DetailPanel
            key={card.id}
            card={card}
            data={data}
            byId={byId}
            onSelect={setChosen}
            onClose={() => setChosen(null)}
          />
        ) : null}
      </div>
      {detailed ? null : (
        <Widgets data={data} byId={byId} events={events ?? []} onSelect={setChosen} />
      )}
    </div>
  );
}

// ── the canvas ─────────────────────────────────────────────────────────────

type End = { card: string } | { panel: ArchitectureColumn };

interface Arrow {
  id: string;
  from: End;
  to: End;
  role: string;
  /** What it says, when it is several links together: each role once. */
  roles?: readonly string[];
  status: string | null;
  inferred: boolean;
  /** The chosen card's own: drawn over the rest, named. */
  own: boolean;
}

interface Drawn {
  id: string;
  /** The SVG path; a line that would cross a column goes round it. */
  d: string;
  tone: "neutral" | "violet" | "warning" | "danger";
  dashed: boolean;
  faded: boolean;
  label: string | null;
  x: number;
  y: number;
}

function endKey(end: End): string {
  return "card" in end ? `card:${end.card}` : `panel:${end.panel}`;
}

/** What the canvas draws: at rest, a card's links to a column together —
 * many cards' alike from their column — and the column's own links; the
 * chosen card's own links over them. */
export function arrowsOf(
  data: Architecture,
  byId: ReadonlyMap<string, ArchitectureCard>,
  selected: string | null,
  detailed: boolean,
): Arrow[] {
  const arrows = new Map<string, Arrow>();
  const add = (arrow: Arrow) => {
    const key = `${endKey(arrow.from)}->${endKey(arrow.to)}`;
    const there = arrows.get(key);
    if (!there || (arrow.own && !there.own)) arrows.set(key, { ...arrow, id: key });
  };
  const same = data.links.filter(
    (link) => byId.get(link.from_id)?.column === byId.get(link.to_id)?.column,
  );
  if (same.length <= SAME_COLUMN_AT_REST || detailed) {
    for (const link of same) {
      add({
        id: "",
        from: { card: link.from_id },
        to: { card: link.to_id },
        role: link.role,
        status: link.status,
        inferred: link.origin === "inferred",
        own: false,
      });
    }
  }
  const shared = new Map<string, typeof data.bundles>();
  for (const bundle of data.bundles) {
    const source = byId.get(bundle.from_id);
    if (!source) continue;
    const key = `${source.column}|${bundle.column}|${bundle.role}|${bundle.targets.join(",")}`;
    shared.set(key, [...(shared.get(key) ?? []), bundle]);
  }
  for (const [key, bundles] of shared) {
    const [fromColumn, toColumn] = key.split("|") as [ArchitectureColumn, ArchitectureColumn];
    const { role, targets } = bundles[0];
    const to: End = targets.length === 1 ? { card: targets[0] } : { panel: toColumn };
    const status = worst(
      targets.map((id) => byId.get(id)?.status ?? null),
    );
    if (bundles.length >= SHARED && !detailed) {
      add({ id: "", from: { panel: fromColumn }, to, role, status, inferred: false, own: false });
      continue;
    }
    for (const bundle of bundles) {
      add({
        id: "",
        from: { card: bundle.from_id },
        to,
        role: bundle.role,
        status,
        inferred: false,
        own: false,
      });
    }
  }
  if (selected) {
    // Its links to another column, together — the API storing, queueing and
    // keeping files in the data: one arrow to it, its names joined; four
    // services storing in it: one arrow from theirs. In its own column, each.
    const column = byId.get(selected)?.column;
    const alike = new Map<string, ArchitectureLink[]>();
    for (const link of data.links) {
      const out = link.from_id === selected;
      if (!out && link.to_id !== selected) continue;
      const other = byId.get(out ? link.to_id : link.from_id);
      if (!other) continue;
      const key =
        other.column === column
          ? `one|${link.from_id}|${link.to_id}|${link.role}`
          : `${out ? "out" : "in"}|${other.column}`;
      alike.set(key, [...(alike.get(key) ?? []), link]);
    }
    for (const [key, links] of alike) {
      const [way, other] = key.split("|") as ["out" | "in" | "one", ArchitectureColumn];
      const ends = new Set(links.map((link) => (way === "out" ? link.to_id : link.from_id)));
      const [first] = links;
      if (way === "one" || ends.size === 1) {
        add({
          id: "",
          from: { card: first.from_id },
          to: { card: first.to_id },
          role: first.role,
          roles: [...new Set(links.map((link) => link.role))],
          status: first.status,
          inferred: links.every((link) => link.origin === "inferred"),
          own: true,
        });
        continue;
      }
      const panel: End = { panel: other };
      add({
        id: "",
        from: way === "in" ? panel : { card: selected },
        to: way === "out" ? panel : { card: selected },
        role: first.role,
        roles: [...new Set(links.map((link) => link.role))],
        status: worst(links.map((link) => link.status)),
        inferred: links.every((link) => link.origin === "inferred"),
        own: true,
      });
    }
  }
  return [...arrows.values()];
}

function worst(states: readonly (string | null)[]): string | null {
  const order = ["incident", "attention", "operational", "unmonitored"];
  return states.reduce<string | null>((found, state) => {
    if (!state) return found;
    if (!found) return state;
    return order.indexOf(state) < order.indexOf(found) ? state : found;
  }, null);
}

interface Point {
  x: number;
  y: number;
}

/** Where a line leaves one box and reaches the other: the sides that face
 * each other — beside, else above or below. */
function sides(
  a: DOMRect,
  b: DOMRect,
  aPanel: boolean,
  bPanel: boolean,
): [Point, Point, "h" | "v"] {
  const midY = (r: DOMRect) => r.top + r.height / 2;
  const midX = (r: DOMRect) => r.left + r.width / 2;
  // A column's side faces the card it reaches: level with it, within reach.
  const clampX = (r: DOMRect, x: number) => Math.min(Math.max(x, r.left + 16), r.right - 16);
  const clampY = (r: DOMRect, y: number) => Math.min(Math.max(y, r.top + 16), r.bottom - 16);
  if (b.left >= a.right - 2 || b.right <= a.left + 2) {
    const right = b.left >= a.right - 2;
    let y1 = midY(a);
    let y2 = midY(b);
    if (aPanel) y1 = clampY(a, y2);
    if (bPanel) y2 = clampY(b, y1);
    return [
      { x: right ? a.right : a.left, y: y1 },
      { x: right ? b.left : b.right, y: y2 },
      "h",
    ];
  }
  const down = b.top >= a.bottom - 2;
  let x1 = midX(a);
  let x2 = midX(b);
  if (aPanel) x1 = clampX(a, x2);
  if (bPanel) x2 = clampX(b, x1);
  return [
    { x: x1, y: down ? a.bottom : a.top },
    { x: x2, y: down ? b.top : b.bottom },
    "v",
  ];
}

/** A point of a cubic curve, `at` of the way along. */
function along(p0: Point, p1: Point, p2: Point, p3: Point, at: number): Point {
  const u = 1 - at;
  const mix = (a: number, b: number, c: number, d: number) =>
    u * u * u * a + 3 * u * u * at * b + 3 * u * at * at * c + at * at * at * d;
  return { x: mix(p0.x, p1.x, p2.x, p3.x), y: mix(p0.y, p1.y, p2.y, p3.y) };
}

function Canvas({
  data,
  byId,
  selected,
  onSelect,
  detailed,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
  selected: string | null;
  onSelect: (id: string) => void;
  detailed: boolean;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const frame = useRef<HTMLDivElement>(null);
  const outer = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [drawn, setDrawn] = useState<Drawn[]>([]);
  const arrows = useMemo(
    () => arrowsOf(data, byId, selected, detailed),
    [data, byId, selected, detailed],
  );

  const measure = useCallback(() => {
    const root = frame.current;
    if (!root) return;
    const origin = root.getBoundingClientRect();
    if (origin.width === 0) return;
    // The frame is zoomed: its own coordinates are the screen's over the zoom.
    const scale = zoom;
    const rect = (end: End) =>
      root
        .querySelector<HTMLElement>(
          "card" in end
            ? `[data-card="${CSS.escape(end.card)}"]`
            : `[data-panel="${end.panel}"]`,
        )
        ?.getBoundingClientRect();
    const local = (p: Point): Point => ({
      x: (p.x - origin.left) / scale,
      y: (p.y - origin.top) / scale,
    });
    const panels = [...root.querySelectorAll<HTMLElement>("[data-panel]")].map((el) =>
      el.getBoundingClientRect(),
    );
    const inside = (r: DOMRect, x: number, y: number) =>
      x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    const next: Drawn[] = [];
    for (const arrow of arrows) {
      const a = rect(arrow.from);
      const b = rect(arrow.to);
      if (!a || !b) continue;
      const [p1, p2, way] = sides(a, b, "panel" in arrow.from, "panel" in arrow.to);
      const faded = selected !== null && !arrow.own;
      const tone: Drawn["tone"] = arrow.own
        ? "violet"
        : arrow.status === "incident"
          ? "danger"
          : arrow.status === "attention"
            ? "warning"
            : "neutral";
      const label = faded
        ? null
        : [...(arrow.roles ?? [arrow.role])]
            .sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))
            .map((role) => roleWords(w, role).label)
            .join(" · ");
      // A column between the two ends, on the way down: round it, on the left.
      const between =
        way === "v"
          ? panels.find(
              (r) =>
                !inside(r, a.left + a.width / 2, a.top + a.height / 2) &&
                !inside(r, b.left + b.width / 2, b.top + b.height / 2) &&
                r.top > Math.min(p1.y, p2.y) &&
                r.bottom < Math.max(p1.y, p2.y) &&
                Math.max(p1.x, p2.x) >= r.left &&
                Math.min(p1.x, p2.x) <= r.right,
            )
          : undefined;
      if (between) {
        const yA = "panel" in arrow.from ? a.bottom - 24 : a.top + a.height / 2;
        const yB = "panel" in arrow.to ? b.top + 24 : b.top + b.height / 2;
        const start = local({ x: a.left, y: yA });
        const end = local({ x: b.left, y: yB });
        const gutter = local({ x: Math.min(a.left, b.left, between.left) - 18, y: 0 }).x;
        next.push({
          id: arrow.id,
          d: `M ${start.x} ${start.y} H ${gutter} V ${end.y} H ${end.x}`,
          tone,
          dashed: arrow.inferred,
          faded,
          label,
          x: gutter,
          y: (start.y + end.y) / 2,
        });
        continue;
      }
      const s = local(p1);
      const e = local(p2);
      const pull =
        way === "h"
          ? Math.max(24, Math.abs(e.x - s.x) / 2) * Math.sign(e.x - s.x || 1)
          : Math.max(20, Math.abs(e.y - s.y) / 2) * Math.sign(e.y - s.y || 1);
      const c1 = way === "h" ? { x: s.x + pull, y: s.y } : { x: s.x, y: s.y + pull };
      const c2 = way === "h" ? { x: e.x - pull, y: e.y } : { x: e.x, y: e.y - pull };
      next.push({
        id: arrow.id,
        d: `M ${s.x} ${s.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${e.x} ${e.y}`,
        tone,
        dashed: arrow.inferred,
        faded,
        label,
        // Where its name goes: the curve's middle — the chosen card's, near
        // what it reaches, out of the way of the cards it passes.
        ...along(s, c1, c2, e, arrow.own ? 0.8 : 0.5),
      });
    }
    setDrawn(next);
  }, [arrows, selected, w, zoom]);

  useLayoutEffect(() => {
    measure();
    const root = frame.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(root);
    return () => observer.disconnect();
  }, [measure]);

  const fit = () => {
    const room = outer.current?.clientWidth ?? 0;
    const need = frame.current?.scrollWidth ?? 0;
    if (!room || !need) return;
    setZoom(Math.max(ZOOMS[0], Math.min(1, room / (need / zoom))));
  };
  const step = (by: 1 | -1) => {
    const at = ZOOMS.findIndex((z) => z >= zoom - 0.001);
    const next = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, (at < 0 ? 2 : at) + by))];
    setZoom(next);
  };

  const groups = (column: ArchitectureColumn) => data.groups.filter((g) => g.column === column);
  const cards = (group: ArchitectureGroup) =>
    data.cards.filter((card) => card.column === group.column && card.group === group.name);
  const panel = (column: ArchitectureColumn, className?: string) => (
    <Panel
      column={column}
      groups={groups(column)}
      className={cn(className, (column === "code" || column === "cloud") && "self-start")}
      cards={cards}
      selected={selected}
      onSelect={onSelect}
    />
  );

  return (
    <section
      aria-label={w.label}
      className="relative min-w-0 rounded-xl border border-shell-line bg-shell-canvas/40 p-3"
      data-testid="architecture"
    >
      <div ref={outer} className="overflow-auto">
        <div ref={frame} className="relative p-1" style={{ zoom }}>
          <svg
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 z-10 hidden size-full overflow-visible lg:block"
          >
            <defs>
              {(["neutral", "violet", "warning", "danger"] as const).map((tone) => (
                <marker
                  key={tone}
                  id={`arch-head-${tone}`}
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill={stroke(tone)} />
                </marker>
              ))}
            </defs>
            {drawn.map((line) => (
              <path
                key={line.id}
                d={line.d}
                fill="none"
                stroke={stroke(line.tone)}
                strokeWidth={line.tone === "violet" ? 1.75 : 1.25}
                strokeOpacity={line.faded ? 0.25 : 0.85}
                strokeDasharray={line.dashed ? "4 3" : undefined}
                markerEnd={`url(#arch-head-${line.tone})`}
                data-testid="architecture-arrow"
              />
            ))}
          </svg>
          <div className="grid gap-x-12 gap-y-6 lg:grid-cols-[minmax(11rem,13rem)_minmax(0,1fr)_minmax(12rem,15rem)]">
            {panel("code")}
            <div className="flex min-w-0 flex-col gap-y-10">
              {panel("services")}
              {panel("data")}
              {panel("external")}
            </div>
            {panel("cloud")}
          </div>
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-30 hidden lg:block">
            {drawn
              .filter((line) => line.label)
              .map((line) => (
                <span
                  key={line.id}
                  className={cn(
                    "absolute -translate-x-1/2 -translate-y-1/2 rounded-md border bg-white px-1.5 py-px text-[0.6875rem] leading-4 whitespace-nowrap",
                    line.tone === "violet"
                      ? "border-brand-violet/30 text-shell-nav-active"
                      : "border-shell-line text-shell-muted",
                  )}
                  style={{ left: line.x, top: line.y }}
                >
                  {line.label}
                </span>
              ))}
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1" role="group" aria-label={w.zoom.fit}>
        {(
          [
            [Plus, w.zoom.in, () => step(1)],
            [Minus, w.zoom.out, () => step(-1)],
            [Maximize2, w.zoom.fit, fit],
          ] as const
        ).map(([Icon, label, act]) => (
          <button
            key={label}
            type="button"
            onClick={act}
            aria-label={label}
            title={label}
            className="flex size-8 items-center justify-center rounded-lg border border-shell-line bg-white text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <Icon className="size-4" aria-hidden="true" />
          </button>
        ))}
      </div>
      <Sentences data={data} byId={byId} />
    </section>
  );
}

function stroke(tone: Drawn["tone"]): string {
  if (tone === "violet") return "var(--brand-violet)";
  return TONES[tone === "neutral" ? "neutral" : tone].stroke;
}

/** Every link, in words: what the arrows say, for whoever cannot see them. */
function Sentences({
  data,
  byId,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  return (
    <details className="mt-2 text-[0.8125rem] text-brand-navy">
      <summary className="cursor-pointer text-xs text-shell-muted outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40">
        {w.text}
      </summary>
      <ul className="mt-2 flex flex-col gap-0.5" data-testid="architecture-text">
        {data.links.map((link) => {
          const from = byId.get(link.from_id);
          const to = byId.get(link.to_id);
          if (!from || !to) return null;
          return (
            <li key={`${link.from_id}:${link.role}:${link.to_id}`}>
              {`${cardName(from)} ${roleWords(w, link.role).sentence} ${cardName(to)}`}
              {link.origin === "inferred" ? (
                <span className="text-shell-muted">{` (${w.inferred})`}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function Panel({
  column,
  groups,
  cards,
  selected,
  onSelect,
  className,
}: {
  column: ArchitectureColumn;
  groups: readonly ArchitectureGroup[];
  cards: (group: ArchitectureGroup) => ArchitectureCard[];
  selected: string | null;
  onSelect: (id: string) => void;
  className?: string;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const total = groups.reduce((n, g) => n + g.total, 0);
  const wide = column === "services" || column === "data";
  return (
    <section
      aria-label={w.columns[column]}
      data-panel={column}
      className={cn("min-w-0 rounded-xl border border-shell-line bg-white p-3", className)}
      data-testid={`arch-column-${column}`}
    >
      {groups.length === 0 ? (
        <>
          <PanelHeader column={column} group={null} total={0} />
          <p className="mt-2 rounded-lg border border-dashed border-shell-line px-3 py-2 text-xs text-shell-muted">
            {w.columnEmpty[column]}
          </p>
        </>
      ) : (
        groups.map((group, index) => {
          const members = cards(group);
          const hidden = group.total - members.length;
          return (
            <div key={group.id} className={cn(index > 0 && "mt-4 border-t border-shell-line pt-3")}>
              <PanelHeader
                column={column}
                group={group}
                total={groups.length === 1 ? total : group.total}
              />
              <ul
                className={cn(
                  "mt-3",
                  column === "external"
                    ? "flex flex-wrap gap-3"
                    : wide
                      ? "grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-x-6 gap-y-8"
                      : "flex flex-col gap-3",
                )}
              >
                {members.map((card) => (
                  <li key={card.id} className="min-w-0">
                    <CardBox card={card} selected={card.id === selected} onSelect={onSelect} />
                  </li>
                ))}
              </ul>
              {hidden > 0 ? (
                <p className="mt-2 text-xs text-shell-muted">{fill(w.more, { count: hidden })}</p>
              ) : null}
            </div>
          );
        })
      )}
    </section>
  );
}

function PanelHeader({
  column,
  group,
  total,
}: {
  column: ArchitectureColumn;
  group: ArchitectureGroup | null;
  total: number;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  let title: string = w.columns[column];
  let logo: React.ReactNode = (
    <IconTile
      icon={column === "data" ? Database : column === "external" ? Network : Boxes}
      tone={KIND_TONES[column] ?? "violet"}
      className="size-9"
    />
  );
  if (group && column === "code") {
    title = (w.hosts as Record<string, string>)[group.name] ?? group.name;
    logo = hasSourceLogo(group.name) ? (
      <span className="flex size-9 items-center justify-center rounded-lg bg-shell-canvas">
        <Logo kind={group.name} className="size-5" />
      </span>
    ) : (
      logo
    );
  }
  if (group && column === "cloud") {
    const name = (w.providers as Record<string, string>)[group.name] ?? group.name;
    title = group.regions.length === 1 ? `${name} (${group.regions[0]})` : name;
    logo = hasSourceLogo(group.name) ? (
      <span className="flex size-9 items-center justify-center rounded-lg bg-state-warning-soft">
        <Logo kind={group.name} className="size-5" />
      </span>
    ) : (
      <IconTile icon={Cloud} tone="warning" className="size-9" />
    );
  }
  return (
    <div className="flex items-center gap-2.5">
      {logo}
      <div className="min-w-0">
        <h2 className="truncate text-[0.9375rem] font-semibold text-brand-navy">{title}</h2>
        <p className="text-xs text-shell-muted">{fill(w.counts[column], { count: total })}</p>
      </div>
    </div>
  );
}

function StatusDot({ card }: { card: ArchitectureCard }) {
  const t = useDictionary();
  if (!card.status) return null;
  const label =
    t.environment.architecture.health[card.status as keyof Words["health"]] ?? card.status;
  return (
    <span
      title={card.deduced ? `${label} · ${t.environment.architecture.panel.deduced}` : label}
      className={cn(
        "size-2.5 shrink-0 rounded-full",
        TONES[STATUS_TONE[card.status] ?? "neutral"].dot,
        card.deduced && "opacity-70",
      )}
    />
  );
}

function CardBox({
  card,
  selected,
  onSelect,
}: {
  card: ArchitectureCard;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const { locale } = useLocale();
  const number = new Intl.NumberFormat(locale);
  const kind = kindLabel(w, card);
  const health = card.status
    ? (w.health[card.status as keyof Words["health"]] ?? card.status)
    : null;
  const state = health && card.deduced ? `${health} (${w.panel.deduced})` : health;
  const label = [cardName(card), kind, state].filter(Boolean).join(", ");
  const logo =
    card.column === "code" ? (
      hasSourceLogo(card.group) ? (
        <Logo kind={card.group} className="size-5" />
      ) : null
    ) : card.type === "tool" && hasSourceLogo(card.name) ? (
      <Logo kind={card.name} className="size-5" />
    ) : card.column === "data" ? (
      (() => {
        const engine = engineLogo(card);
        return engine ? <Logo kind={engine} className="size-5" /> : null;
      })()
    ) : null;
  const icon = logo ? (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-shell-canvas">
      {logo}
    </span>
  ) : (
    <IconTile
      icon={kindIcon(card.kind)}
      tone={KIND_TONES[card.column] ?? "neutral"}
      className="size-8 [&>svg]:size-4"
    />
  );
  const stats = statsLine(w, card, number);
  const compact = card.column === "external";

  return (
    <button
      type="button"
      data-card={card.id}
      aria-pressed={selected}
      aria-label={label}
      onClick={() => onSelect(card.id)}
      className={cn(
        "relative z-20 flex w-full min-w-0 flex-col gap-1.5 rounded-lg border bg-white text-left outline-none transition focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        compact ? "px-2.5 py-2" : "p-2.5",
        selected
          ? "border-brand-violet/60 ring-2 ring-brand-violet/30"
          : card.status === "incident"
            ? "border-state-danger/40"
            : card.status === "attention"
              ? "border-state-warning/40"
              : "border-shell-line hover:border-brand-violet/40",
      )}
    >
      <span className="flex min-w-0 items-start gap-2">
        {icon}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.8125rem] font-semibold text-brand-navy" title={card.name}>
            {cardName(card)}
          </span>
          <span className="block truncate text-[0.6875rem] text-shell-muted">
            {card.column === "code" && card.name.includes("/")
              ? card.name.split("/")[0]
              : kind}
          </span>
        </span>
        <StatusDot card={card} />
      </span>
      {!compact && card.technology.length > 0 ? (
        <span className="flex flex-wrap gap-1">
          {card.technology.slice(0, 3).map((name) => (
            <span
              key={name}
              className="rounded bg-shell-canvas px-1.5 py-px text-[0.625rem] font-medium text-brand-navy"
            >
              {name}
            </span>
          ))}
        </span>
      ) : null}
      {!compact && stats.length > 0 ? (
        <span className="flex flex-wrap gap-x-2 text-[0.6875rem] text-shell-muted tabular-nums">
          {stats.map((said) => (
            <span key={said}>{said}</span>
          ))}
        </span>
      ) : null}
    </button>
  );
}

// ── the chosen card ───────────────────────────────────────────────────────

const PANEL_TABS = ["overview", "relations", "events"] as const;
type PanelTab = (typeof PANEL_TABS)[number];

function DetailPanel({
  card,
  data,
  byId,
  onSelect,
  onClose,
}: {
  card: ArchitectureCard;
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const p = w.panel;
  const [tab, setTab] = useState<PanelTab>("overview");
  const relations = useMemo(() => relationsOf(data.links, card.id), [data.links, card.id]);
  const href = card.entity_id ? entityHref({ id: card.entity_id, type: card.type }) : null;

  return (
    <section
      aria-label={p.label}
      className="flex min-w-0 flex-col gap-3 self-start rounded-xl border border-shell-line bg-white p-4"
      data-testid="architecture-panel"
    >
      <div className="flex items-center gap-3">
        <IconTile
          icon={kindIcon(card.kind)}
          tone={KIND_TONES[card.column] ?? "violet"}
          className="size-9"
        />
        <h2 className="min-w-0 flex-1 truncate text-[1.0625rem] font-semibold text-brand-navy">
          {cardName(card)}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={p.close}
          title={p.close}
          className="flex size-8 items-center justify-center rounded-lg text-shell-muted outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div role="tablist" aria-label={p.label} className="flex gap-1 border-b border-shell-line">
        {PANEL_TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            data-testid={`architecture-panel-${key}`}
            className={cn(
              "-mb-px border-b-2 px-2 py-1.5 text-[0.8125rem] font-medium whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40",
              tab === key
                ? "border-shell-nav-active text-shell-nav-active"
                : "border-transparent text-shell-muted hover:text-brand-navy",
            )}
          >
            {key === "relations"
              ? fill(p.relationsTitle, { count: relations.length })
              : p.tabs[key]}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <Overview card={card} byId={byId} onSelect={onSelect} href={href} />
      ) : tab === "relations" ? (
        <Relations relations={relations} byId={byId} onSelect={onSelect} href={href} />
      ) : (
        <Events card={card} />
      )}
    </section>
  );
}

interface Relation {
  link: ArchitectureLink;
  other: string;
  out: boolean;
}

function relationsOf(links: readonly ArchitectureLink[], id: string): Relation[] {
  const found: Relation[] = [];
  for (const link of links) {
    if (link.from_id === id) found.push({ link, other: link.to_id, out: true });
    else if (link.to_id === id) found.push({ link, other: link.from_id, out: false });
  }
  return found;
}

function Overview({
  card,
  byId,
  onSelect,
  href,
}: {
  card: ArchitectureCard;
  byId: ReadonlyMap<string, ArchitectureCard>;
  onSelect: (id: string) => void;
  href: string | null;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const p = w.panel;
  const { locale } = useLocale();
  const number = new Intl.NumberFormat(locale);
  const repository = card.repository_id ? byId.get(card.repository_id) : undefined;
  const stats = statsLine(w, card, number);
  const status = card.status as keyof Words["health"] | null;
  const tone = status ? STATUS_TONE[status] : null;
  const host = card.host_id ? byId.get(card.host_id) : undefined;
  const deployment = card.deployment
    ? ((p.deployments as Record<string, string>)[card.deployment] ?? card.deployment)
    : null;
  const why = [
    host
      ? fill(p.deducedFrom, {
          host: cardName(host),
          kind: kindLabel(w, host),
          state: host.status
            ? (w.health[host.status as keyof Words["health"]] ?? host.status)
            : w.health.none,
        })
      : p.deducedHint,
    deployment ? fill(p.lastDeployment, { state: deployment }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const isDatabase = card.type === "database";

  const rows: { label: string; value: React.ReactNode }[] = [
    { label: p.type, value: kindLabel(w, card) },
  ];
  if (card.technology.length) {
    rows.push({ label: p.technology, value: card.technology.join(" · ") });
  }
  if (repository) {
    rows.push({
      label: p.repository,
      value: (
        <span className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onSelect(repository.id)}
            className="truncate font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {repository.name}
          </button>
          {repository.url ? (
            <a
              href={repository.url}
              target="_blank"
              rel="noreferrer"
              aria-label={repository.url}
              className="text-shell-muted hover:text-shell-nav-active"
            >
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          ) : null}
        </span>
      ),
    });
  }
  if (card.environment) {
    rows.push({
      label: p.environment,
      value: (
        <span className="rounded-md bg-shell-canvas px-1.5 py-0.5 text-xs font-medium text-brand-navy capitalize">
          {card.environment}
        </span>
      ),
    });
  }
  if (card.region) rows.push({ label: p.region, value: card.region });
  if (card.url) {
    rows.push({
      label: p.url,
      value: (
        <a
          href={card.url}
          target="_blank"
          rel="noreferrer"
          className="flex min-w-0 items-center gap-1 text-shell-nav-active hover:underline"
        >
          <span className="truncate">{card.url}</span>
          <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
        </a>
      ),
    });
  }
  if (card.column === "services" || card.column === "data") {
    rows.push({
      label: p.team,
      value: card.team ? card.team.name : <span className="text-shell-muted">{p.noTeam}</span>,
    });
  }
  if (stats.length) rows.push({ label: p.figures, value: stats.join(" · ") });

  return (
    <div className="flex flex-col gap-3" data-testid="architecture-overview">
      {status && tone ? (
        <div className="rounded-lg bg-shell-canvas/70 px-3 py-2" data-testid="architecture-health">
          <div className="flex items-center gap-2 text-[0.8125rem]">
            <span aria-hidden="true" className={cn("size-2.5 rounded-full", TONES[tone].dot)} />
            <span className="font-semibold text-brand-navy">{w.health[status]}</span>
            {card.deduced ? (
              <span className="rounded bg-white px-1.5 py-px text-[0.6875rem] font-medium text-shell-muted">
                {p.deduced}
              </span>
            ) : null}
          </div>
          {card.deduced ? <p className="mt-1 text-xs text-shell-muted">{why}</p> : null}
          {card.column === "services" ? (
            <p className="mt-1 text-xs text-shell-muted">{`${p.uptime} : ${p.notMeasured}`}</p>
          ) : null}
        </div>
      ) : null}
      {card.description ? (
        <p className="text-[0.8125rem] leading-snug text-brand-navy">{card.description}</p>
      ) : null}
      <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-shell-muted">{row.label}</dt>
            <dd className="min-w-0 text-brand-navy">{row.value}</dd>
          </div>
        ))}
      </dl>
      {card.evidence.length ? (
        <div>
          <p className="text-xs font-medium text-shell-muted">{p.evidence}</p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {card.evidence.slice(0, 4).map((said, index) => (
              <li
                key={`${index}:${said}`}
                className="truncate font-mono text-[0.6875rem] text-brand-navy"
                title={said}
              >
                {said}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {href ? <CardLink href={href}>{p.open}</CardLink> : null}
        {isDatabase && card.entity_id ? (
          <CardLink href={`${routes.environmentGraph()}?entity=${card.entity_id}`}>
            {p.tables}
          </CardLink>
        ) : null}
      </div>
    </div>
  );
}

function Relations({
  relations,
  byId,
  onSelect,
  href,
}: {
  relations: readonly Relation[];
  byId: ReadonlyMap<string, ArchitectureCard>;
  onSelect: (id: string) => void;
  href: string | null;
}) {
  const t = useDictionary();
  const w = t.environment.architecture;
  if (relations.length === 0) {
    return <p className="py-3 text-[0.8125rem] text-shell-muted">{w.panel.noRelations}</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-2" data-testid="architecture-relations">
        {relations.map(({ link, other, out }) => {
          const card = byId.get(other);
          if (!card) return null;
          const words = roleWords(w, link.role);
          return (
            <li key={`${link.from_id}:${link.role}:${link.to_id}`} className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-xs text-shell-muted">
                {out ? words.out : words.in}
                {link.origin === "inferred" ? (
                  <span className="block text-[0.625rem]">{w.inferred}</span>
                ) : null}
              </span>
              <button
                type="button"
                onClick={() => onSelect(card.id)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-shell-line px-2 py-1.5 text-left outline-none hover:border-brand-violet/40 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
              >
                <IconTile
                  icon={kindIcon(card.kind)}
                  tone={KIND_TONES[card.column] ?? "neutral"}
                  className="size-7 [&>svg]:size-3.5"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.8125rem] font-medium text-brand-navy">
                    {cardName(card)}
                  </span>
                  <span className="block truncate text-[0.6875rem] text-shell-muted">
                    {kindLabel(w, card)}
                  </span>
                </span>
                <StatusDot card={card} />
              </button>
            </li>
          );
        })}
      </ul>
      {href ? <CardLink href={href}>{w.panel.seeAll}</CardLink> : null}
    </div>
  );
}

function Events({ card }: { card: ArchitectureCard }) {
  const t = useDictionary();
  const sheet = useEntitySheet(card.entity_id ?? "");
  const rows = useMemo(() => eventRows(t, sheet.data?.events ?? []), [sheet.data, t]);
  if (sheet.isLoading) {
    return <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  }
  return <EventList rows={rows} empty={t.environment.architecture.panel.eventsEmpty} />;
}

// ── the widgets ───────────────────────────────────────────────────────────

function Widgets({
  data,
  byId,
  events,
  onSelect,
}: {
  data: Architecture;
  byId: ReadonlyMap<string, ArchitectureCard>;
  events: readonly EventRow[];
  onSelect: (id: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment.architecture.widgets;
  const figures = data.figures;
  const types = [
    { id: "services", value: figures.services + figures.applications, bar: "bg-state-info" },
    { id: "cloud", value: figures.cloud_resources, bar: "bg-state-warning" },
    { id: "tables", value: figures.tables, bar: "bg-brand-violet" },
    { id: "repositories", value: figures.repositories, bar: "bg-shell-muted" },
  ] as const;
  const most = Math.max(1, ...types.map((row) => row.value));
  const top = Math.max(1, ...data.top_dependencies.map((row) => row.count));

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)]">
      <Card title={w.byStatus} className="min-w-0">
        <Donut counts={data.services_by_status} />
      </Card>
      <Card title={w.types} className="min-w-0">
        <ul className="flex flex-col gap-2.5" data-testid="architecture-types">
          {types.map((row) => (
            <li key={row.id} className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 text-[0.8125rem]">
              <span className="truncate text-brand-navy">{w.typeRows[row.id]}</span>
              <span className="h-2 overflow-hidden rounded-full bg-shell-canvas">
                <span
                  className={cn("block h-full rounded-full", row.bar)}
                  style={{ width: `${(row.value / most) * 100}%` }}
                />
              </span>
              <span className="text-right font-medium text-brand-navy tabular-nums">{row.value}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card
        title={w.activity}
        className="min-w-0"
        action={<CardLink href={routes.activity()}>{w.seeAll}</CardLink>}
      >
        <EventList rows={events.slice(0, 4)} empty={t.environment.events.empty} />
      </Card>
      <Card title={w.top} className="min-w-0">
        {data.top_dependencies.length === 0 ? (
          <p className="py-4 text-center text-[0.8125rem] text-shell-muted">{w.topEmpty}</p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="architecture-top">
            {data.top_dependencies.map((row) => {
              const card = byId.get(row.card_id);
              return (
                <li key={row.card_id} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_2rem] items-center gap-2 text-[0.8125rem]">
                  <button
                    type="button"
                    onClick={() => card && onSelect(card.id)}
                    disabled={!card}
                    className="flex min-w-0 items-center gap-1.5 text-left text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40 disabled:no-underline"
                  >
                    {(() => {
                      const Icon = kindIcon(row.kind);
                      return <Icon className="size-3.5 shrink-0 text-shell-muted" aria-hidden="true" />;
                    })()}
                    <span className="truncate">{card ? cardName(card) : row.name}</span>
                  </button>
                  <span className="h-2 overflow-hidden rounded-full bg-shell-canvas">
                    <span
                      className="block h-full rounded-full bg-state-info"
                      style={{ width: `${(row.count / top) * 100}%` }}
                    />
                  </span>
                  <span className="text-right font-medium text-brand-navy tabular-nums">{row.count}</span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Donut({ counts }: { counts: Record<string, number> }) {
  const t = useDictionary();
  const w = t.environment.architecture;
  const states = ["operational", "attention", "incident", "unmonitored"] as const;
  const total = states.reduce((n, state) => n + (counts[state] ?? 0), 0);
  const radius = 34;
  const length = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="flex items-center gap-4" data-testid="architecture-donut">
      <svg viewBox="0 0 88 88" className="size-24 shrink-0" role="img" aria-label={`${total} ${w.widgets.services}`}>
        <circle
          cx="44"
          cy="44"
          r={radius}
          fill="none"
          stroke="var(--shell-canvas)"
          strokeWidth="10"
        />
        {total > 0
          ? states.map((state) => {
              const share = (counts[state] ?? 0) / total;
              if (share === 0) return null;
              const arc = (
                <circle
                  key={state}
                  cx="44"
                  cy="44"
                  r={radius}
                  fill="none"
                  stroke={TONES[STATUS_TONE[state]].stroke}
                  strokeWidth="10"
                  strokeDasharray={`${share * length} ${length}`}
                  strokeDashoffset={-offset * length}
                  transform="rotate(-90 44 44)"
                />
              );
              offset += share;
              return arc;
            })
          : null}
        <text x="44" y="44" textAnchor="middle" className="fill-brand-navy text-[18px] font-bold">
          {total}
        </text>
        <text x="44" y="58" textAnchor="middle" className="fill-shell-muted text-[9px]">
          {w.widgets.services}
        </text>
      </svg>
      <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
        {states
          .filter((state) => state !== "unmonitored" || (counts[state] ?? 0) > 0)
          .map((state) => (
            <li key={state} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
              <span aria-hidden="true" className={cn("size-2.5 rounded-full", TONES[STATUS_TONE[state]].dot)} />
              <span className="min-w-0 flex-1 truncate">{w.health[state]}</span>
              <span className="font-semibold tabular-nums">{counts[state] ?? 0}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}
