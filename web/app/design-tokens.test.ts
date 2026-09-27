/**
 * The palette, measured rather than asserted.
 *
 * "Contrast AA on text" was written in the ticket, in the documentation and
 * in a commit message before anything checked it — and three of the values
 * taken from the mockups did not meet it. This reads the tokens out of
 * globals.css and does the arithmetic, so the claim and the stylesheet
 * cannot drift apart again.
 *
 * WCAG 2.1 AA: 4.5:1 for body text, 3:1 for large text and for the boundary
 * of a control. Everything here is body text.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const STYLESHEET = readFileSync(path.join(import.meta.dirname, "globals.css"), "utf8");

function token(name: string, seen: ReadonlySet<string> = new Set()): string {
  const declaration = STYLESHEET.match(new RegExp(`--${name}:\\s*([^;]+);`));
  if (!declaration) {
    throw new Error(`--${name} is not declared in globals.css`);
  }
  const value = declaration[1].trim();

  const hex = value.match(/^#[0-9a-fA-F]{6}$/);
  if (hex) return hex[0];

  // A token that aliases another rather than repeating its value — --primary
  // pointing at --brand-navy, say. One level of var(--x) is a design-system
  // alias; more than one is the thing worth catching, not chasing forever.
  const alias = value.match(/^var\(--([\w-]+)\)$/);
  if (alias && !seen.has(name)) {
    return token(alias[1], new Set(seen).add(name));
  }

  throw new Error(`--${name} is "${value}", not a hex colour or a single-level var() alias`);
}

function luminance(colour: string): number {
  const channels = [1, 3, 5].map((at) => Number.parseInt(colour.slice(at, at + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

/** Every pair the interface actually puts on screen, as text. */
const PAIRS: readonly [label: string, foreground: string, background: string][] = [
  ["page title", token("brand-navy"), token("shell-page")],
  ["navigation label at rest", token("shell-nav"), token("shell-surface")],
  ["active navigation label", token("shell-nav-active"), token("brand-violet-soft")],
  ["navigation icon — held to text contrast, not the 3:1 icons need", token("shell-icon"), token("shell-surface")],
  ["tagline and secondary labels", token("shell-muted"), token("shell-surface")],
  ["secondary text on the page", token("shell-muted"), token("shell-page")],
  ["search placeholder, in its field", token("shell-muted"), token("shell-canvas")],
  ["search placeholder, on the white header", token("shell-muted"), "#FFFFFF"],
  ["the count beside an entry", token("shell-badge-foreground"), token("shell-badge")],
  ["skip link", "#FFFFFF", token("brand-navy")],
  // The system states: each tone on its own soft background, and on white.
  ["success, on its background", token("state-success"), token("state-success-soft")],
  ["success, on white", token("state-success"), "#FFFFFF"],
  ["warning, on its background", token("state-warning"), token("state-warning-soft")],
  ["warning, on white", token("state-warning"), "#FFFFFF"],
  ["danger, on its background", token("state-danger"), token("state-danger-soft")],
  ["danger, on white", token("state-danger"), "#FFFFFF"],
  ["danger, on the page", token("state-danger"), token("shell-page")],
  ["info, on its background", token("state-info"), token("state-info-soft")],
  ["the line under the greeting", token("shell-accent-muted"), token("shell-page")],
  ["text on the closing banner", token("shell-muted"), token("shell-highlight")],
  // The default button and every other surface styled with the shadcn
  // "primary" pair (LEKA-339): brand navy, not shadcn's stock near-black.
  ["primary button label", token("primary-foreground"), token("primary")],
  // leka-core.com's screens before signing in.
  ["site text on the card", token("site-ink"), "#FFFFFF"],
  ["site secondary text on the card", token("site-slate"), "#FFFFFF"],
  ["site secondary text on the page", token("site-slate"), token("site-mist")],
  ["site link on the card", token("site-violet"), "#FFFFFF"],
  ["site button label", "#FFFFFF", token("site-ink")],
  ["site button label, hovered", "#FFFFFF", token("site-violet")],
];

describe("the shell's text is readable", () => {
  it.each(PAIRS)("%s", (_label, foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
  });

  it("measures something real", () => {
    // Guards the guard: a typo in a token name throws, and a formula that
    // returned the same number for everything would pass all of the above.
    expect(contrast("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
    expect(contrast("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(() => token("no-such-token")).toThrow();
  });
});
