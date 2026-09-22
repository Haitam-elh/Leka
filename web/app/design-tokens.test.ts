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

function token(name: string): string {
  const found = STYLESHEET.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  if (!found) {
    throw new Error(`--${name} is not a hex token in globals.css`);
  }
  return found[1];
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

/** Every pair the shell actually puts on screen, as text. */
const PAIRS: readonly [label: string, foreground: string, background: string][] = [
  ["page title", token("brand-navy"), token("shell-canvas")],
  ["navigation label at rest", token("shell-nav"), token("shell-surface")],
  ["active navigation label", token("brand-violet"), token("brand-violet-soft")],
  ["tagline and secondary labels", token("shell-muted"), token("shell-surface")],
  ["secondary text on the page", token("shell-muted"), token("shell-canvas")],
  ["search placeholder, on the white header", token("shell-muted"), "#FFFFFF"],
  ["the count beside an entry", token("shell-badge-foreground"), token("shell-badge")],
  ["skip link", "#FFFFFF", token("brand-navy")],
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
