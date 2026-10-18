"use client";

import {
  Accessibility,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Bug,
  ChartColumn,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleHelp,
  Clock,
  Cloud,
  Code,
  Database,
  Eye,
  FileText,
  FlaskConical,
  GitPullRequest,
  Info,
  Layers,
  Lightbulb,
  Link2,
  List,
  ListChecks,
  Map as MapIcon,
  Move,
  Palette,
  Plug,
  Rocket,
  Route,
  Search,
  Settings2,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Tag,
  Target,
  TriangleAlert,
  Users,
  Wallet,
  Zap,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";

import { reasonSaid, summaryOf, titleOf } from "@/components/capabilities/catalogue";
import { MARKET_ICON } from "@/components/capabilities/market-mark";
import {
  AgentAdd,
  agentStateOf,
  AgentStateSaid,
  type AgentState,
  useAgentPurchase,
} from "@/components/capabilities/offers";
import { ExploreDemoButton } from "@/components/demo/demo";
import { useInDemo } from "@/components/demo/in-demo";
import { Pill } from "@/components/intelligence/pill";
import { hasSourceLogo, SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import {
  type AgentProduct,
  type ExampleResult,
  inLanguage,
  type Level,
  productOf,
  type ProductIcon,
  type Words,
} from "@/lib/agent-products";
import { agentTitle } from "@/lib/agent-title";
import { type AddOns, type AgentOffer, euros } from "@/lib/billing";
import { useAddOns } from "@/lib/billing-queries";
import type { CapabilityDetail } from "@/lib/capabilities";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { isConnected, KIND_CATEGORY, type SourceKind } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * An agent's page, written to convince a buyer (LEKA-471, its mockup): what
 * it brings, the problem it solves, what it does and how, four situations
 * and a request for each, the sources it reads, examples of results, its
 * price and what each plan makes of it, a short FAQ — and, beside it, how
 * to get it, the plans that include it, the facts, what one can count on.
 *
 * One structure for every agent. The words are its product's
 * (lib/agent-products, written from its SKILL.md); every fact that changes —
 * price, plans, state, rights, sources, formats — is the API's. An agent
 * with no product (a draft, one not on sale) shows only what the API says,
 * and is never offered for sale. The registry's details stay one click away,
 * under « Détails techniques ».
 */

const PLAN_ORDER = ["free", "starter", "growth", "business", "enterprise"] as const;

const ICONS: Record<ProductIcon, LucideIcon> = {
  accessibility: Accessibility,
  alert: TriangleAlert,
  book: BookOpen,
  bug: Bug,
  check: BadgeCheck,
  clock: Clock,
  cloud: Cloud,
  code: Code,
  database: Database,
  eye: Eye,
  file: FileText,
  flask: FlaskConical,
  git: GitPullRequest,
  layers: Layers,
  list: List,
  map: MapIcon,
  move: Move,
  palette: Palette,
  rocket: Rocket,
  route: Route,
  search: Search,
  shield: ShieldCheck,
  sparkles: Sparkles,
  target: Target,
  users: Users,
  zap: Zap,
};

/** The mockup's tiles, in turn: rose, violet, sky, emerald, amber. */
const TONES = [
  "bg-rose-100 text-rose-600",
  "bg-violet-100 text-violet-600",
  "bg-sky-100 text-sky-600",
  "bg-emerald-100 text-emerald-600",
  "bg-amber-100 text-amber-600",
];

const LEVEL_TONE: Record<Level, "danger" | "warning" | "info" | "success"> = {
  critical: "danger",
  high: "warning",
  medium: "info",
  low: "success",
};

const SECTIONS = ["overview", "features", "use-cases", "integrations", "results", "pricing", "faq"] as const;
type SectionId = (typeof SECTIONS)[number];

type Deliverable = "report" | "deck" | "diff" | "design" | "proposal";

function deliverableOf(capability: CapabilityDetail): Deliverable {
  if (capability.formats.includes("pptx") || capability.formats.includes("pdf")) return "deck";
  if (capability.formats.includes("diff")) return "diff";
  // The designer: its report, and the screen it proposes drawn before and after.
  if (capability.formats.includes("html")) return "design";
  if (capability.mode === "proposes_action") return "proposal";
  return "report";
}

/** The sources it reads, as kinds LEKA connects — its needs, unfolded. */
function kindsOf(capability: CapabilityDetail): SourceKind[] {
  const kinds = capability.sources.flatMap((need) => need.any_of);
  return [...new Set(kinds)].filter((kind): kind is SourceKind => hasSourceLogo(kind));
}

function planName(plan: string): string {
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

function rank(plan: string | null | undefined): number {
  return plan ? PLAN_ORDER.indexOf(plan as (typeof PLAN_ORDER)[number]) : -1;
}

function useSay() {
  const { locale } = useLocale();
  return (words: Words) => inLanguage(words, locale);
}

type Standing = {
  offers: AddOns | undefined;
  offer: AgentOffer | null;
  state: AgentState | null;
  /** It may run here now: its plan or a purchase lets it, and nothing else holds it back. */
  runnable: boolean;
};

export function AgentProductPage({
  capability,
  use,
  technical,
}: {
  capability: CapabilityDetail;
  /** Its run form and its runs, where it may run here. */
  use: React.ReactNode;
  /** The registry's details, kept below the page. */
  technical: React.ReactNode;
}) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const offers = useAddOns().data;
  const product = productOf(capability.key);
  const offer = offers?.agents.find((a) => a.key === capability.key) ?? null;
  const state = offers ? agentStateOf(offers, capability.key) : null;
  const standing: Standing = {
    offers,
    offer,
    state,
    runnable: capability.available && (state === "included" || state === "owned"),
  };

  // Opened on a section by its address: the section, once it is drawn.
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if ((SECTIONS as readonly string[]).includes(id) || id === "use") {
      document.getElementById(id)?.scrollIntoView({ block: "start" });
    }
  }, []);

  return (
    <div data-testid="capability" data-key={capability.key} data-page="product" data-state={state ?? undefined}>
      <Link
        href={routes.capabilities()}
        className="inline-flex items-center gap-2 rounded-lg border border-shell-line bg-white px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        data-testid="agent-back"
      >
        <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden="true" />
        {w.back}
      </Link>
      <div className="mt-5 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17rem] xl:grid-cols-[minmax(0,1fr)_20rem] 2xl:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Laid out by its own width, not the window's: the column beside
            it takes a third of a laptop. */}
        <div className="@container min-w-0 space-y-5">
          <Hero capability={capability} product={product} standing={standing} />
          <div className="lg:hidden">
            <ChooseCard capability={capability} standing={standing} where="top" />
          </div>
          <SectionTabs />
          <WhySection product={product} capability={capability} />
          <FeaturesSection product={product} capability={capability} />
          <UseCasesSection product={product} capability={capability} />
          <IntegrationsSection capability={capability} />
          <ResultsSection product={product} capability={capability} />
          <PricingSection capability={capability} standing={standing} />
          <FaqSection product={product} capability={capability} standing={standing} />
          {standing.runnable ? (
            <section
              id="use"
              aria-labelledby="use-title"
              className="scroll-mt-16 space-y-4"
              data-testid="agent-use"
            >
              <div>
                <h2 id="use-title" className="text-lg font-bold text-brand-navy">
                  {w.use}
                </h2>
                <p className="text-[0.8125rem] text-shell-muted">{w.useLead}</p>
              </div>
              {use}
            </section>
          ) : null}
          <SimilarSection capability={capability} offers={offers} />
          <details className="group rounded-2xl border border-shell-line bg-white" data-testid="agent-technical">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-5 py-4 text-[0.9375rem] font-semibold text-brand-navy outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40 [&::-webkit-details-marker]:hidden">
              <span className="flex items-center gap-2">
                <Settings2 className="size-4 text-shell-muted" aria-hidden="true" />
                {w.technical}
              </span>
              <ChevronDown className="size-4 text-shell-muted transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="border-t border-shell-line p-4">{technical}</div>
          </details>
        </div>
        <aside className="space-y-4" aria-label={w.choose}>
          <div className="hidden lg:block">
            <ChooseCard capability={capability} standing={standing} where="side" />
          </div>
          <PlansCard standing={standing} />
          <FactsCard capability={capability} standing={standing} />
          <TrustCard capability={capability} />
        </aside>
      </div>
    </div>
  );
}

// ── The hero ────────────────────────────────────────────────────────────────

function Hero({
  capability,
  product,
  standing,
}: {
  capability: CapabilityDetail;
  product: AgentProduct | null;
  standing: Standing;
}) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  const { format } = useLocale();
  const { offer, state } = standing;
  const Icon = (offer?.market && MARKET_ICON[offer.market]) || Sparkles;
  const tiers = t.catalogue.offers.tiers as Record<string, string>;
  return (
    <section aria-labelledby="agent-title" className="flex items-start gap-6" data-testid="agent-hero">
      <div className="flex min-w-0 flex-1 flex-col gap-5 @lg:flex-row @lg:items-start">
        <span className="flex size-20 shrink-0 items-center justify-center rounded-3xl bg-brand-violet-soft md:size-24">
          <Icon className="size-10 text-shell-nav-active md:size-12" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <Pill tone="violet">{w.badge}</Pill>
          <h1
            id="agent-title"
            className="mt-2 text-[1.75rem] leading-tight font-bold tracking-[-0.02em] text-balance text-brand-navy md:text-[2.25rem]"
          >
            {titleOf(t, capability)}
          </h1>
          <p className="mt-2 max-w-2xl text-[0.9375rem] text-shell-muted md:text-base" data-testid="agent-promise">
            {product ? say(product.promise) : summaryOf(t, capability)}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            {offer && state !== "unavailable" ? (
              <span className="text-[0.9375rem] font-semibold tabular-nums text-brand-navy" data-testid="agent-hero-price">
                {euros(offer.monthly_price, format)}{" "}
                <span className="text-[0.8125rem] font-normal text-shell-muted">{w.perMonth}</span>
              </span>
            ) : null}
            {offer?.included_from ? (
              <Pill tone="violet">{fill(w.includedFrom, { plan: planName(offer.included_from) })}</Pill>
            ) : null}
            {offer ? <Pill tone="neutral">{tiers[offer.tier] ?? offer.tier}</Pill> : null}
            <AgentStateSaid agentKey={capability.key} />
          </div>
        </div>
      </div>
      <HeroArt capability={capability} product={product} />
    </section>
  );
}

/** The mockup's illustration: the sources it reads, a map it draws, two
 * things it does — drawn, nothing to read here (said in the page). */
function HeroArt({ capability, product }: { capability: CapabilityDetail; product: AgentProduct | null }) {
  const say = useSay();
  const kinds = kindsOf(capability).slice(0, 3);
  const [first, second] = product?.features ?? [];
  return (
    <div className="relative hidden h-52 w-[19rem] shrink-0 @4xl:block" aria-hidden="true">
      <div className="absolute inset-4 rounded-[2rem] bg-linear-to-br from-brand-violet-soft/80 via-white to-sky-50" />
      <div className="absolute top-12 left-16 h-32 w-44 rounded-xl border border-shell-line bg-white p-2 shadow-md">
        <svg viewBox="0 0 160 100" className="size-full">
          <g className="stroke-brand-violet/40" strokeWidth="1.2" fill="none">
            <path d="M80 50 L30 22 M80 50 L130 22 M80 50 L30 80 M80 50 L130 80" />
          </g>
          {[
            [80, 50, 13],
            [30, 22, 9],
            [130, 22, 9],
            [30, 80, 9],
            [130, 80, 9],
          ].map(([cx, cy, r]) => (
            <g key={`${cx}-${cy}`}>
              <circle cx={cx} cy={cy} r={r} className="fill-brand-violet-soft stroke-brand-violet/60" strokeWidth="1.2" />
              <circle cx={cx} cy={cy} r={r / 3} className="fill-brand-violet/70" />
            </g>
          ))}
        </svg>
      </div>
      {kinds.map((kind, index) => (
        <span
          key={kind}
          className="absolute left-2 flex size-10 items-center justify-center rounded-xl border border-shell-line bg-white shadow-sm"
          style={{ top: `${1.5 + index * 3.6}rem` }}
        >
          <SourceLogo kind={kind} className="size-5" />
        </span>
      ))}
      {first ? (
        <span className="absolute top-0 right-0 line-clamp-2 max-w-[12.5rem] rounded-lg border border-shell-line bg-white px-2.5 py-1.5 text-[0.6875rem] leading-snug font-medium text-shell-nav-active shadow-sm">
          {say(first)}
        </span>
      ) : null}
      {second ? (
        <span className="absolute right-0 bottom-0 line-clamp-2 max-w-[12.5rem] rounded-lg border border-shell-line bg-white px-2.5 py-1.5 text-[0.6875rem] leading-snug font-medium text-shell-nav-active shadow-sm">
          {say(second)}
        </span>
      ) : null}
    </div>
  );
}

// ── The tabs: the page's sections, by their address ────────────────────────

function SectionTabs() {
  const t = useDictionary();
  const w = t.catalogue.product;
  const [active, setActive] = useState<SectionId>("overview");
  const labels: Record<SectionId, string> = {
    overview: w.tabs.overview,
    features: w.tabs.features,
    "use-cases": w.tabs.useCases,
    integrations: w.tabs.integrations,
    results: w.tabs.results,
    pricing: w.tabs.pricing,
    faq: w.tabs.faq,
  };

  // The one being read: the last whose top has passed under the tabs.
  useEffect(() => {
    const scroller = document.getElementById("main-content");
    const target: HTMLElement | Window = scroller ?? window;
    function read() {
      const top = (scroller?.getBoundingClientRect().top ?? 0) + 96;
      let seen: SectionId = "overview";
      for (const id of SECTIONS) {
        const element = document.getElementById(id);
        if (element && element.getBoundingClientRect().top <= top) seen = id;
      }
      setActive(seen);
    }
    read();
    target.addEventListener("scroll", read, { passive: true });
    return () => target.removeEventListener("scroll", read);
  }, []);

  return (
    <nav
      aria-label={w.pageNav}
      className="sticky top-0 z-10 -mx-1 overflow-x-auto border-b border-shell-line bg-white/95 px-1 backdrop-blur"
      data-testid="agent-tabs"
    >
      <ul className="flex gap-6 whitespace-nowrap">
        {SECTIONS.map((id) => (
          <li key={id}>
            <a
              href={`#${id}`}
              aria-current={active === id ? "location" : undefined}
              onClick={() => setActive(id)}
              className={cn(
                "inline-block border-b-2 py-3 text-[0.875rem] font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                active === id
                  ? "border-shell-nav-active text-shell-nav-active"
                  : "border-transparent text-shell-muted hover:text-brand-navy",
              )}
            >
              {labels[id]}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Section({
  id,
  icon: Icon,
  title,
  action,
  children,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="scroll-mt-16 rounded-2xl border border-shell-line bg-white p-5 md:p-6"
      data-testid={`agent-${id}`}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${id}-title`} className="flex items-center gap-3 text-[1.0625rem] font-bold text-brand-navy md:text-lg">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-violet-soft text-shell-nav-active">
            <Icon className="size-5" aria-hidden="true" />
          </span>
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Tile({ icon, index, className }: { icon: ProductIcon; index: number; className?: string }) {
  const Icon = ICONS[icon];
  return (
    <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl", TONES[index % TONES.length], className)}>
      <Icon className="size-5" aria-hidden="true" />
    </span>
  );
}

// ── The sections ────────────────────────────────────────────────────────────

function WhySection({ product, capability }: { product: AgentProduct | null; capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  return (
    <Section id="overview" icon={Target} title={w.why}>
      <p className="max-w-3xl text-[0.9375rem] text-shell-muted" data-testid="agent-problem">
        {product ? say(product.problem) : summaryOf(t, capability)}
      </p>
      {product ? (
        <ul className="mt-5 grid gap-5 @xl:grid-cols-3 @xl:gap-0 @xl:divide-x @xl:divide-shell-line rtl:@xl:divide-x-reverse">
          {product.benefits.map((benefit, index) => (
            <li key={benefit.title.fr} className="@xl:px-5 @xl:first:ps-0 @xl:last:pe-0" data-testid="agent-benefit">
              <Tile icon={benefit.icon} index={index} />
              <h3 className="mt-3 text-[1.0625rem] leading-snug font-bold text-brand-navy">{say(benefit.title)}</h3>
              <p className="mt-1 text-[0.875rem] text-shell-muted">{say(benefit.body)}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

function FeaturesSection({ product, capability }: { product: AgentProduct | null; capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  const kinds = kindsOf(capability);
  const deliverable = deliverableOf(capability);
  const features = product?.features ?? [];
  const half = Math.ceil(features.length / 2);
  const columns = [features.slice(0, half), features.slice(half)].filter((c) => c.length);
  const limits = [
    w.limitNothing,
    capability.mode === "read_only" ? w.limitReadOnly : w.limitDecide,
    ...(product?.limits ?? []).map(say),
  ];
  const steps = [
    { title: w.steps.askTitle, body: w.steps.ask },
    {
      title: w.steps.readTitle,
      body: kinds.length
        ? fill(w.steps.readSome, {
            sources:
              kinds.length > 4
                ? fill(w.steps.andOthers, {
                    list: kinds.slice(0, 3).map(sourceTitle).join(", "),
                    count: kinds.length - 3,
                  })
                : kinds.map(sourceTitle).join(", "),
          })
        : w.steps.readModel,
    },
    { title: w.steps.deliverTitle, body: w.steps[deliverable] },
  ];
  return (
    <Section id="features" icon={Settings2} title={w.does}>
      {product ? <p className="max-w-3xl text-[0.9375rem] text-brand-navy">{say(product.does)}</p> : null}
      {columns.length ? (
        <div className="mt-4 grid gap-3 @xl:grid-cols-2" data-testid="agent-feature-list">
          {columns.map((column, index) => (
            <ul key={index} className="space-y-3 rounded-xl border border-shell-line p-4">
              {column.map((feature) => (
                <li key={feature.fr} className="flex items-start gap-2.5 text-[0.875rem] text-brand-navy">
                  <CircleCheck className="mt-0.5 size-4.5 shrink-0 fill-state-success text-white" aria-hidden="true" />
                  {say(feature)}
                </li>
              ))}
            </ul>
          ))}
        </div>
      ) : null}
      <h3 className="mt-6 text-[0.9375rem] font-bold text-brand-navy">{w.how}</h3>
      <ol className="mt-3 grid gap-3 @xl:grid-cols-3" data-testid="agent-how">
        {steps.map((step, index) => (
          <li key={step.title} className="flex gap-3 rounded-xl bg-shell-canvas/70 p-4">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-violet text-[0.8125rem] font-bold text-white">
              {index + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[0.875rem] font-semibold text-brand-navy">{step.title}</span>
              <span className="mt-0.5 block text-[0.8125rem] text-shell-muted">{step.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <h3 className="mt-6 text-[0.9375rem] font-bold text-brand-navy">{w.limits}</h3>
      <ul className="mt-2 space-y-1.5" data-testid="agent-limits">
        {limits.map((limit) => (
          <li key={limit} className="flex items-start gap-2 text-[0.8125rem] text-shell-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-state-info" aria-hidden="true" />
            {limit}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function askHref(words: string): string {
  return `${routes.intentionNew()}?q=${encodeURIComponent(words)}`;
}

function UseCasesSection({ product, capability }: { product: AgentProduct | null; capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  return (
    <Section id="use-cases" icon={Lightbulb} title={w.useCases}>
      {product ? (
        <ul className="grid gap-3 @lg:grid-cols-2 @5xl:grid-cols-4">
          {product.useCases.map((useCase, index) => (
            <li
              key={useCase.title.fr}
              className="flex flex-col rounded-xl border border-shell-line p-4"
              data-testid="agent-use-case"
            >
              <Tile icon={useCase.icon} index={index + 1} className="size-10" />
              <h3 className="mt-3 text-[0.9375rem] font-bold text-brand-navy">{say(useCase.title)}</h3>
              <p className="mt-1 text-[0.8125rem] text-shell-muted">{say(useCase.body)}</p>
              <p className="mt-3 flex-1 text-[0.8125rem] text-brand-navy italic">« {say(useCase.ask)} »</p>
              <Link
                href={askHref(say(useCase.ask))}
                className="mt-3 inline-flex items-center gap-1.5 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                data-testid="agent-ask"
              >
                {w.askIt}
                <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="space-y-2">
          {capability.examples.map((example) => (
            <li key={example}>
              <Link
                href={askHref(example)}
                className="inline-flex items-center gap-1.5 text-[0.875rem] text-shell-nav-active hover:underline"
                data-testid="agent-ask"
              >
                « {example} »
                <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

const SHOWN_SOURCES = 8;

function IntegrationsSection({ capability }: { capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const [all, setAll] = useState(false);
  const sources = useSources().data ?? [];
  const connected = new Set(sources.filter(isConnected).map((s) => s.type));
  const needed = kindsOf(capability);
  // No source of its own: it reads the model all of them make.
  const kinds = needed.length ? needed : [...connected].filter((k): k is SourceKind => hasSourceLogo(k));
  const shown = all ? kinds : kinds.slice(0, SHOWN_SOURCES);
  const hidden = kinds.length - shown.length;
  return (
    <Section
      id="integrations"
      icon={Link2}
      title={w.integrations}
      action={
        <Link
          href={routes.sources()}
          className="inline-flex items-center gap-1.5 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {w.connectSource}
          <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
        </Link>
      }
    >
      <p className="mb-4 text-[0.875rem] text-shell-muted">
        {needed.length ? w.integrationsSome : w.integrationsModel}
      </p>
      {!needed.length && kinds.length ? (
        <p className="mb-2 text-xs font-semibold text-brand-navy">{w.yourSources}</p>
      ) : null}
      {kinds.length ? (
        <ul className="grid grid-cols-3 gap-2.5 @lg:grid-cols-4 @2xl:grid-cols-6 @5xl:grid-cols-9" data-testid="agent-sources">
          {shown.map((kind) => (
            <li
              key={kind}
              className="relative flex flex-col items-center gap-1 rounded-xl border border-shell-line px-2 py-3 text-center"
              data-testid="agent-source"
              data-kind={kind}
              data-connected={connected.has(kind) || undefined}
            >
              {connected.has(kind) ? (
                <span className="absolute top-1.5 right-1.5" title={w.connected}>
                  <CircleCheck className="size-3.5 fill-state-success text-white" aria-hidden="true" />
                  <span className="sr-only">{w.connected}</span>
                </span>
              ) : null}
              <SourceLogo kind={kind} className="size-7" />
              <span className="text-xs font-semibold text-brand-navy">{sourceTitle(kind)}</span>
              <span className="text-[0.6875rem] text-shell-muted">
                {(t.sources.categories as Record<string, string>)[KIND_CATEGORY[kind]] ?? ""}
              </span>
            </li>
          ))}
          {hidden > 0 || all ? (
            <li>
              <button
                type="button"
                onClick={() => setAll(!all)}
                aria-expanded={all}
                className="flex size-full min-h-24 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-shell-line px-2 py-3 text-xs font-semibold text-shell-nav-active outline-none hover:bg-brand-violet-soft/50 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
              >
                {all ? w.fewer : fill(w.more, { count: hidden })}
              </button>
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="text-[0.875rem] text-shell-muted">{w.noSource}</p>
      )}
    </Section>
  );
}

function ResultsSection({ product, capability }: { product: AgentProduct | null; capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  const deliverable = deliverableOf(capability);
  const formatWord = w.formats[deliverable === "proposal" ? "report" : deliverable];
  return (
    <Section id="results" icon={ChartColumn} title={w.results}>
      <ul className="grid gap-3 @xl:grid-cols-2 @3xl:grid-cols-3">
        {(product?.examples ?? []).map((example) => (
          <li
            key={example.title.fr}
            className="flex flex-col rounded-xl border border-shell-line p-4"
            data-testid="agent-example"
            data-kind={example.kind}
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-[0.875rem] font-bold text-brand-navy">{say(example.title)}</h3>
              <Pill tone="neutral">{w.example}</Pill>
            </div>
            <Example example={example} />
          </li>
        ))}
        <li className="flex flex-col rounded-xl border border-shell-line p-4" data-testid="agent-deliverable">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[0.875rem] font-bold text-brand-navy">{w.deliverable}</h3>
            <Pill tone="violet">{formatWord}</Pill>
          </div>
          {product ? (
            <ol className="space-y-1.5 text-[0.8125rem] text-brand-navy">
              {product.outline.map((part, index) => (
                <li key={part.fr} className="flex gap-2">
                  <span className="w-4 shrink-0 text-end font-semibold text-shell-nav-active tabular-nums">{index + 1}</span>
                  {say(part)}
                </li>
              ))}
            </ol>
          ) : null}
        </li>
      </ul>
      {product ? <p className="mt-3 text-xs text-shell-muted">{w.exampleNote}</p> : null}
    </Section>
  );
}

function Example({ example }: { example: ExampleResult }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const say = useSay();
  if (example.kind === "levels") {
    return (
      <ul className="space-y-2">
        {example.items.map((item) => (
          <li key={item.text.fr} className="flex items-start gap-2.5 text-[0.8125rem] text-brand-navy">
            <Pill tone={LEVEL_TONE[item.level]} dot className="w-20 shrink-0 justify-start">
              {w.levels[item.level]}
            </Pill>
            <span className="min-w-0">{say(item.text)}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (example.kind === "list") {
    return (
      <ul className="space-y-2">
        {example.items.map((item) => (
          <li key={item.fr} className="flex items-start gap-2 text-[0.8125rem] text-brand-navy">
            <ChevronRight className="mt-0.5 size-4 shrink-0 text-shell-nav-active rtl:-scale-x-100" aria-hidden="true" />
            {say(item)}
          </li>
        ))}
      </ul>
    );
  }
  // A small map: the first at the centre, the others around it.
  const [centre, ...around] = example.items.map(say);
  const spots = [
    [20, 18],
    [180, 18],
    [20, 102],
    [180, 102],
  ];
  return (
    <svg viewBox="0 0 260 120" className="w-full" role="img" aria-label={[centre, ...around].join(", ")}>
      <g className="stroke-brand-violet/35" strokeWidth="1.2" strokeDasharray="3 3" fill="none">
        {around.slice(0, 4).map((_, index) => (
          <path key={index} d={`M130 60 L${spots[index][0] + 30} ${spots[index][1]}`} />
        ))}
      </g>
      <rect x="85" y="46" width="90" height="28" rx="8" className="fill-brand-violet" />
      <text x="130" y="64" textAnchor="middle" className="fill-white text-[9px] font-semibold">
        {centre}
      </text>
      {around.slice(0, 4).map((label, index) => (
        <g key={label}>
          <rect
            x={spots[index][0] - 10}
            y={spots[index][1] - 12}
            width="80"
            height="22"
            rx="6"
            className="fill-white stroke-shell-line"
            strokeWidth="1"
          />
          <text x={spots[index][0] + 30} y={spots[index][1] + 3} textAnchor="middle" className="fill-brand-navy text-[8.5px]">
            {label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function PricingSection({ capability, standing }: { capability: CapabilityDetail; standing: Standing }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const { format } = useLocale();
  const { offers, offer, state } = standing;
  const tiers = t.catalogue.offers.tiers as Record<string, string>;
  const sold = offer && state !== "unavailable";
  return (
    <Section id="pricing" icon={Wallet} title={w.pricing}>
      {sold && offers ? (
        <div className="grid gap-5 @xl:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-3">
            <p className="flex items-baseline gap-1.5">
              <span className="text-[2rem] leading-none font-bold tabular-nums text-brand-navy">
                {euros(offer.monthly_price, format)}
              </span>
              <span className="text-[0.8125rem] text-shell-muted">{w.perMonth}</span>
            </p>
            <div className="flex flex-wrap gap-2">
              <Pill tone="neutral">{tiers[offer.tier] ?? offer.tier}</Pill>
              <AgentStateSaid agentKey={capability.key} />
            </div>
            <p className="text-xs text-shell-muted">{w.terms}</p>
            <AgentCta capability={capability} standing={standing} />
          </div>
          <table className="w-full text-[0.8125rem]" data-testid="agent-plans-table">
            <caption className="sr-only">{w.pricingLead}</caption>
            <tbody className="divide-y divide-shell-line">
              {PLAN_ORDER.map((plan) => {
                const none = rank(plan) < rank(offers.minimum_plan);
                const included = !none && offer.included_from !== null && rank(plan) >= rank(offer.included_from);
                return (
                  <tr key={plan} data-plan={plan} data-included={included || undefined}>
                    <th scope="row" className="py-2.5 pe-3 text-start font-semibold text-brand-navy">
                      {planName(plan)}
                      {offers.plan === plan ? (
                        <Pill tone="violet" className="ms-2">
                          {w.yourPlan}
                        </Pill>
                      ) : null}
                    </th>
                    <td className="py-2.5 text-end">
                      {none ? (
                        <span className="text-shell-muted">{w.planRow.none}</span>
                      ) : included ? (
                        <span className="inline-flex items-center gap-1.5 font-medium text-state-success">
                          <CircleCheck className="size-4" aria-hidden="true" />
                          {w.planRow.included}
                        </span>
                      ) : (
                        <span className="text-brand-navy">
                          {fill(w.planRow.option, { price: euros(offer.monthly_price, format) })}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-[0.875rem] text-shell-muted">{w.faqs.priceNotSold}</p>
      )}
    </Section>
  );
}

function FaqSection({
  product,
  capability,
  standing,
}: {
  product: AgentProduct | null;
  capability: CapabilityDetail;
  standing: Standing;
}) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const f = w.faqs;
  const say = useSay();
  const { format } = useLocale();
  const { offers, offer, state } = standing;
  const kinds = kindsOf(capability);
  const deliverable = deliverableOf(capability);
  const what = w.formats[deliverable === "proposal" ? "report" : deliverable];
  const price =
    offer && offers && state !== "unavailable"
      ? [
          fill(f.priceOption, {
            price: euros(offer.monthly_price, format),
            minimum: planName(offers.minimum_plan),
          }),
          offer.included_from
            ? fill(offer.included_from === PLAN_ORDER.at(-1) ? f.priceIncludedTop : f.priceIncluded, {
                plan: planName(offer.included_from),
              })
            : "",
        ]
          .filter(Boolean)
          .join(" ")
      : f.priceNotSold;
  const items: [string, string][] = [
    [f.needs, kinds.length ? fill(f.needsSome, { sources: kinds.map(sourceTitle).join(", ") }) : f.needsModel],
    [f.changes, capability.mode === "read_only" ? f.changesNo : f.changesPropose],
    [
      f.delivers,
      product
        ? fill(f.deliversSaid, { what, parts: product.outline.map(say).join(", ").toLowerCase() })
        : what,
    ],
    [f.price, price],
    [f.missing, f.missingAnswer],
    [
      f.who,
      fill(f.whoAnswer, {
        run: capability.permission === "intention:create" ? f.member : capability.permission,
      }),
    ],
  ];
  return (
    <Section id="faq" icon={CircleHelp} title={w.faq}>
      <ul className="divide-y divide-shell-line" data-testid="agent-faq-list">
        {items.map(([question, answer]) => (
          <li key={question}>
            <details className="group py-1">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded py-2.5 text-[0.9375rem] font-semibold text-brand-navy outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40 [&::-webkit-details-marker]:hidden">
                {question}
                <ChevronDown className="size-4 shrink-0 text-shell-muted transition-transform group-open:rotate-180" aria-hidden="true" />
              </summary>
              <p className="pb-3 text-[0.875rem] text-shell-muted">{answer}</p>
            </details>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function SimilarSection({ capability, offers }: { capability: CapabilityDetail; offers: AddOns | undefined }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const { format } = useLocale();
  if (!offers) return null;
  const self = offers.agents.find((a) => a.key === capability.key);
  const others = offers.agents.filter((a) => a.key !== capability.key);
  // Its own category first, then its level, then the rest — as listed.
  const score = (a: AgentOffer) => (a.market === self?.market ? 0 : a.tier === self?.tier ? 1 : 2);
  const similar = [...others].sort((a, b) => score(a) - score(b)).slice(0, 4);
  if (!similar.length) return null;
  const summaries = t.catalogue.summaries as Record<string, string>;
  return (
    <section aria-labelledby="similar-title" data-testid="agent-similar">
      <h2 id="similar-title" className="mb-3 flex items-center gap-3 text-lg font-bold text-brand-navy">
        <span className="flex size-9 items-center justify-center rounded-xl bg-brand-violet-soft text-shell-nav-active">
          <Users className="size-5" aria-hidden="true" />
        </span>
        {w.similar}
      </h2>
      <ul className="grid gap-3 @lg:grid-cols-2 @5xl:grid-cols-4">
        {similar.map((agent) => {
          const Icon = (agent.market && MARKET_ICON[agent.market]) || Sparkles;
          const state = agentStateOf(offers, agent.key);
          return (
            <li
              key={agent.key}
              className="flex flex-col rounded-xl border border-shell-line bg-white p-4"
              data-testid="agent-similar-card"
              data-key={agent.key}
            >
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-violet-soft text-shell-nav-active">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <Link
                    href={routes.capability(agent.key)}
                    className="rounded text-[0.9375rem] font-bold text-brand-navy outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    {agentTitle(t, agent.key, agent.title)}
                  </Link>
                  <p className="mt-0.5 line-clamp-2 text-xs text-shell-muted">{summaries[agent.key] ?? agent.summary}</p>
                </div>
              </div>
              <div className="mt-3 flex flex-1 items-end justify-between gap-2">
                <span className="text-[0.875rem] font-semibold tabular-nums text-brand-navy">
                  {euros(agent.monthly_price, format)}{" "}
                  <span className="text-xs font-normal text-shell-muted">{w.perMonth}</span>
                </span>
                {state === "option" ? (
                  <AgentAdd agentKey={agent.key} />
                ) : state === "included" || state === "owned" ? (
                  <span title={t.catalogue.offers.states[state]}>
                    <CircleCheck className="size-5 text-state-success" aria-hidden="true" />
                    <span className="sr-only">{t.catalogue.offers.states[state]}</span>
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── Beside: how to get it, the plans, the facts, what one can count on ─────

/** The action its state allows (LEKA-471): use it, buy it, manage it, see
 * the plans — or nothing to buy, said. */
function AgentCta({ capability, standing }: { capability: CapabilityDetail; standing: Standing }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const purchase = useAgentPurchase();
  const { offers, state, runnable } = standing;
  const wide = "w-full justify-center";
  // The mockup's violet: the one action that counts here.
  const primary = "w-full justify-center bg-brand-violet text-white hover:bg-brand-violet/90";
  if (!state || !offers) {
    return <div className="h-11 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  }
  if (state === "included" || state === "owned") {
    return (
      <div className="flex flex-col gap-2">
        {runnable ? (
          <a href="#use" className={cn(buttonVariants({ size: "lg" }), primary)} data-testid="agent-cta" data-cta="use">
            <Rocket aria-hidden="true" />
            {w.ctas.use}
          </a>
        ) : (
          <div className="flex flex-col gap-1" data-testid="agent-cta" data-cta={state}>
            <span className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-state-success/10 text-[0.875rem] font-semibold text-state-success">
              <CircleCheck className="size-4" aria-hidden="true" />
              {state === "owned" ? w.ctas.owned : w.ctas.included}
            </span>
            {capability.reasons.map((reason) => (
              <span key={reason.code} className="text-xs text-state-warning">
                {reasonSaid(t, reason)}
              </span>
            ))}
          </div>
        )}
        {state === "owned" ? (
          <Link
            href={routes.billing()}
            className={cn(buttonVariants({ variant: "outline", size: "lg" }), wide)}
            data-testid="agent-manage"
          >
            {w.ctas.manage}
          </Link>
        ) : null}
      </div>
    );
  }
  if (state === "option") {
    return (
      <div className="flex flex-col gap-1.5">
        <Button
          type="button"
          size="lg"
          className={primary}
          disabled={!purchase.may || purchase.pending}
          onClick={() => purchase.buy(capability.key)}
          data-testid="agent-cta"
          data-cta="buy"
        >
          <ShoppingCart aria-hidden="true" />
          {w.ctas.buy}
        </Button>
        {purchase.may ? null : <p className="text-xs text-shell-muted">{w.ctas.askAdmin}</p>}
      </div>
    );
  }
  if (state === "upgrade") {
    return (
      <div className="flex flex-col gap-1.5">
        <Link
          href={routes.billingPlans()}
          className={cn(buttonVariants({ size: "lg" }), primary)}
          data-testid="agent-cta"
          data-cta="upgrade"
        >
          {w.ctas.upgrade}
        </Link>
        <p className="text-xs text-shell-muted">
          {fill(w.ctas.upgradeHint, { plan: planName(offers.minimum_plan) })}
        </p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Button type="button" size="lg" className={wide} disabled data-testid="agent-cta" data-cta="unavailable">
        {w.ctas.unavailable}
      </Button>
      <p className="text-xs text-shell-muted">{w.ctas.unavailableHint}</p>
    </div>
  );
}

function ChooseCard({
  capability,
  standing,
  where,
}: {
  capability: CapabilityDetail;
  standing: Standing;
  where: "top" | "side";
}) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const { format } = useLocale();
  const inDemo = useInDemo();
  const { offer, state } = standing;
  const sold = offer && state !== "unavailable";
  return (
    <section
      aria-labelledby={`choose-${where}`}
      className="rounded-2xl border border-shell-line bg-white p-5"
      data-testid={where === "side" ? "agent-choose" : "agent-choose-top"}
    >
      <h2 id={`choose-${where}`} className="text-lg font-bold text-brand-navy">
        {w.choose}
      </h2>
      {sold ? (
        <>
          <p className="mt-3 flex items-baseline gap-1.5">
            <span className="text-[2rem] leading-none font-bold tabular-nums text-brand-navy">
              {euros(offer.monthly_price, format)}
            </span>
            <span className="text-[0.8125rem] text-shell-muted">{w.perMonth}</span>
          </p>
          <p className="mt-1.5 text-xs text-shell-muted">{w.terms}</p>
        </>
      ) : null}
      <div className="mt-4 flex flex-col gap-2.5">
        <AgentCta capability={capability} standing={standing} />
        {inDemo ? null : <ExploreDemoButton />}
      </div>
    </section>
  );
}

function PlansCard({ standing }: { standing: Standing }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const { offers, offer } = standing;
  if (!offers || !offer) return null;
  const from = offer.included_from;
  const plans = from ? PLAN_ORDER.filter((p) => rank(p) >= rank(from)) : [];
  // The mockup's marks: a coloured square for each plan.
  const marks = ["bg-violet-600", "bg-rose-600", "bg-emerald-600", "bg-sky-600"];
  return (
    <section aria-labelledby="plans-title" className="rounded-2xl border border-shell-line bg-white p-5" data-testid="agent-plans">
      <h2 id="plans-title" className="text-[1rem] font-bold text-brand-navy">
        {w.plans}
      </h2>
      {plans.length ? (
        <ul className="mt-3 space-y-2">
          {plans.map((plan, index) => (
            <li key={plan}>
              <Link
                href={routes.billingPlans()}
                className="flex items-center gap-3 rounded-lg bg-brand-violet-soft/45 px-3 py-2.5 text-[0.875rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                data-plan={plan}
              >
                <span
                  className={cn("flex size-5 items-center justify-center rounded-md", marks[index % marks.length])}
                  aria-hidden="true"
                >
                  <span className="size-1.5 rounded-full bg-white" />
                </span>
                <span className="flex-1">{planName(plan)}</span>
                {offers.plan === plan ? <Pill tone="violet">{w.yourPlan}</Pill> : null}
                <ChevronRight className="size-4 text-shell-muted rtl:-scale-x-100" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[0.8125rem] text-shell-muted">{w.plansNone}</p>
      )}
    </section>
  );
}

function FactsCard({ capability, standing }: { capability: CapabilityDetail; standing: Standing }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const { offer } = standing;
  const kinds = kindsOf(capability);
  const deliverable = deliverableOf(capability);
  const markets = t.catalogue.markets as Record<string, string>;
  const tiers = t.catalogue.offers.tiers as Record<string, string>;
  const rows: [LucideIcon, string, string][] = [
    [Tag, w.fact.category, (offer?.market && markets[offer.market]) || capability.category],
    ...(offer ? ([[BadgeCheck, w.fact.level, tiers[offer.tier] ?? offer.tier]] as [LucideIcon, string, string][]) : []),
    [Plug, w.fact.sources, kinds.length ? fill(w.fact.sourcesCount, { count: kinds.length }) : w.fact.sourcesAll],
    [FileText, w.fact.deliverable, w.formats[deliverable === "proposal" ? "report" : deliverable]],
    [Eye, w.fact.access, capability.mode === "read_only" ? w.fact.readOnly : w.fact.proposes],
    [Users, w.fact.run, capability.permission === "intention:create" ? w.fact.runMember : capability.permission],
    [Wallet, w.fact.buy, w.fact.buyAdmin],
  ];
  return (
    <section aria-labelledby="facts-title" className="rounded-2xl border border-shell-line bg-white p-5" data-testid="agent-facts">
      <h2 id="facts-title" className="text-[1rem] font-bold text-brand-navy">
        {w.facts}
      </h2>
      <dl className="mt-3 divide-y divide-shell-line text-[0.8125rem]">
        {rows.map(([Icon, label, value]) => (
          <div key={label} className="flex items-center gap-3 py-2.5">
            <Icon className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
            <dt className="text-shell-muted">{label}</dt>
            <dd className="ms-auto text-end font-medium text-brand-navy">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Where the mockup quotes a customer: what LEKA guarantees instead — no
 * testimony is made up. */
function TrustCard({ capability }: { capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.product;
  const items: [LucideIcon, string][] = [
    [ListChecks, w.trustCites],
    [ShieldCheck, w.trustNothing],
    [capability.mode === "read_only" ? Eye : Users, capability.mode === "read_only" ? w.trustReadOnly : w.trustDecide],
  ];
  return (
    <section aria-labelledby="trust-title" className="rounded-2xl border border-shell-line bg-white p-5" data-testid="agent-trust">
      <h2 id="trust-title" className="text-[1rem] font-bold text-brand-navy">
        {w.trust}
      </h2>
      <ul className="mt-3 space-y-3 rounded-xl bg-shell-canvas/70 p-4">
        {items.map(([Icon, text]) => (
          <li key={text} className="flex items-start gap-2.5 text-[0.8125rem] text-brand-navy">
            <Icon className="mt-0.5 size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
            {text}
          </li>
        ))}
      </ul>
    </section>
  );
}
