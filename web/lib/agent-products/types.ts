/**
 * An agent said to whoever might buy it (LEKA-471): one structure for every
 * agent on sale, in French and in English.
 *
 * Written from each agent's SKILL.md — what it reads, what it delivers, what
 * it must never do — and nothing it does not do. What changes is never
 * written here: its price, the plans that include it, who may run or buy
 * it, its sources and its formats are the API's. An example of a result is
 * shown as an example, never as the workspace's own.
 */

export type Words = { readonly fr: string; readonly en: string };

export const w = (fr: string, en: string): Words => ({ fr, en });

/** French where it is asked, English everywhere else. */
export function inLanguage(words: Words, language: string): string {
  return language.startsWith("fr") ? words.fr : words.en;
}

export type ProductIcon =
  | "accessibility"
  | "alert"
  | "book"
  | "bug"
  | "check"
  | "clock"
  | "cloud"
  | "code"
  | "database"
  | "eye"
  | "file"
  | "flask"
  | "git"
  | "layers"
  | "list"
  | "map"
  | "move"
  | "palette"
  | "rocket"
  | "route"
  | "search"
  | "shield"
  | "sparkles"
  | "target"
  | "users"
  | "zap";

export type Level = "critical" | "high" | "medium" | "low";

/** An example of what it delivers — shown as an example, its data made up. */
export type ExampleResult =
  | { readonly kind: "levels"; readonly title: Words; readonly items: readonly { level: Level; text: Words }[] }
  | { readonly kind: "list"; readonly title: Words; readonly items: readonly Words[] }
  /** The first item at the centre, the others around it. */
  | { readonly kind: "diagram"; readonly title: Words; readonly items: readonly Words[] };

export type AgentProduct = {
  /** What it brings, in a sentence: the page's promise. */
  readonly promise: Words;
  /** The concrete problem it solves. */
  readonly problem: Words;
  /** « Pourquoi cet agent ? »: three. */
  readonly benefits: readonly { icon: ProductIcon; title: Words; body: Words }[];
  /** « Ce que fait l'agent », in a paragraph. */
  readonly does: Words;
  /** What it can do, as a checklist. */
  readonly features: readonly Words[];
  /** Four situations, each with a request one can give it. */
  readonly useCases: readonly { icon: ProductIcon; title: Words; body: Words; ask: Words }[];
  /** Its deliverable's parts, as its SKILL.md has it write them. */
  readonly outline: readonly Words[];
  /** Two examples of results. */
  readonly examples: readonly ExampleResult[];
  /** What it cannot do, besides what every agent cannot (said by the page). */
  readonly limits: readonly Words[];
};
