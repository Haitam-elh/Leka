import {
  BadgeCheck,
  Cloud,
  Code,
  FileText,
  Layers,
  type LucideIcon,
  Network,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Target,
  TriangleAlert,
  Workflow,
  Zap,
} from "lucide-react";
import { cn } from "cn";

/**
 * An agent's marketplace domain, drawn the same everywhere (LEKA-493): the
 * home's cards, the marketplace's boxes and lines, a bundle's agents, an
 * agent's page — one icon, one hue, its name always said beside or for
 * screen readers: the colour is never the only way to tell.
 *
 * The hues are none of the states': green, red, orange and violet say
 * « inclus », « en panne », « à surveiller », « option » (docs/frontend/
 * design-system.md § Agents and bundles) — a domain is never mistaken for
 * one. Text and icon at -700 on -50: contrast above 4.5:1.
 */

export type Hue = {
  /** Its words. */
  text: string;
  /** Its icon on its tint. */
  tile: string;
  /** The stroke along a box's top. */
  bar: string;
  /** Where a box's header's wash starts. */
  band: string;
};

export const MARKETS = [
  "product",
  "architecture",
  "testing",
  "incident",
  "security",
  "performance",
  "frontend",
  "mobile",
  "devops",
  "network",
  "documentation",
  "orchestration",
] as const;

/** An agent outside the reference: its registry category's domain. */
export const MARKET_OF_CATEGORY: Record<string, string> = {
  architecture: "architecture",
  development: "architecture",
  operations: "incident",
  security: "security",
  compliance: "security",
  data: "performance",
  infrastructure: "devops",
  documentation: "documentation",
};

export const MARKET_ICON: Record<string, LucideIcon> = {
  product: Target,
  architecture: Code,
  testing: BadgeCheck,
  incident: TriangleAlert,
  security: ShieldCheck,
  performance: Zap,
  frontend: Layers,
  mobile: Smartphone,
  devops: Cloud,
  network: Network,
  documentation: FileText,
  orchestration: Workflow,
};

const HUE: Record<string, Hue> = {
  product: { text: "text-blue-700", tile: "bg-blue-50 text-blue-700", bar: "bg-blue-500", band: "from-blue-50" },
  architecture: { text: "text-indigo-700", tile: "bg-indigo-50 text-indigo-700", bar: "bg-indigo-500", band: "from-indigo-50" },
  testing: { text: "text-teal-700", tile: "bg-teal-50 text-teal-700", bar: "bg-teal-500", band: "from-teal-50" },
  incident: { text: "text-rose-700", tile: "bg-rose-50 text-rose-700", bar: "bg-rose-500", band: "from-rose-50" },
  security: { text: "text-slate-700", tile: "bg-slate-100 text-slate-700", bar: "bg-slate-500", band: "from-slate-100" },
  performance: { text: "text-pink-700", tile: "bg-pink-50 text-pink-700", bar: "bg-pink-500", band: "from-pink-50" },
  frontend: { text: "text-sky-700", tile: "bg-sky-50 text-sky-700", bar: "bg-sky-500", band: "from-sky-50" },
  mobile: { text: "text-fuchsia-700", tile: "bg-fuchsia-50 text-fuchsia-700", bar: "bg-fuchsia-500", band: "from-fuchsia-50" },
  devops: { text: "text-cyan-700", tile: "bg-cyan-50 text-cyan-700", bar: "bg-cyan-500", band: "from-cyan-50" },
  network: { text: "text-lime-700", tile: "bg-lime-50 text-lime-700", bar: "bg-lime-500", band: "from-lime-50" },
  documentation: { text: "text-stone-700", tile: "bg-stone-100 text-stone-700", bar: "bg-stone-500", band: "from-stone-100" },
  orchestration: { text: "text-purple-700", tile: "bg-purple-50 text-purple-700", bar: "bg-purple-500", band: "from-purple-50" },
};
const NONE: Hue = { text: "text-brand-navy", tile: "bg-shell-canvas text-shell-muted", bar: "bg-shell-line", band: "from-shell-canvas" };

/** A registry domain's hue (2026-10-25: « chacun sa couleur »): an
 * Enterprise contract's boxes are by domain — never two alike side by side. */
const DOMAIN_HUE: Record<string, string> = {
  development: "product",
  architecture: "architecture",
  operations: "incident",
  infrastructure: "devops",
  security: "security",
  compliance: "testing",
  data: "performance",
  documentation: "documentation",
  knowledge: "frontend",
  project_management: "orchestration",
  business: "network",
};

/** A box's colours: a marketplace category's, else a registry domain's. */
export function hueOf(group: string, { market }: { market: boolean }): Hue {
  return HUE[market ? group : (DOMAIN_HUE[group] ?? group)] ?? NONE;
}

/** The domain of an agent: its marketplace's, else its category's. */
export function marketOf(agent: { market?: string | null; category: string }): string {
  return agent.market ?? MARKET_OF_CATEGORY[agent.category] ?? agent.category;
}

export function marketText(market: string): string {
  return (HUE[market] ?? NONE).text;
}

/** Its tile: the domain's icon on the domain's hue — `label` said for
 * screen readers and on hover, so the hue never speaks alone. */
export function MarketTile({
  market,
  label,
  className,
}: {
  market: string;
  label: string;
  className?: string;
}) {
  const Icon = MARKET_ICON[market] ?? Sparkles;
  return (
    <span
      className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", (HUE[market] ?? NONE).tile, className)}
      title={label}
      data-market={market}
    >
      <Icon className="size-4.5" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}
