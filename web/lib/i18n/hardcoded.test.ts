/**
 * No French written into a screen (LEKA-495): every word a person reads
 * comes from the dictionaries, so it is translated — and `?qa-language=en-XA`
 * shows it accented. A French string in a component is a word the English
 * interface would show in French.
 *
 * Allowed: tests, comments, the dev pages, the dictionaries themselves, and
 * the agents' product pages (lib/agent-products), written as French and
 * English pairs, w("…", "…"). The names of the company's own things — a
 * service, a repository — come from the data, never from here.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..", "..");
const DIRS = ["components", "app", "lib", "config"];
const ALLOWED = [/\.test\./, /\/lib\/i18n\//, /%5Fdev|\/_dev\//, /\/lib\/agent-products\//, /api-types\.ts$/];
// A French letter inside a quoted string, or in JSX text between tags.
const FRENCH = /(["'`])([^"'`\n]*[éèêàçùôîûâÉÀ][^"'`\n]*)\1|>([^<>{}\n]*[éèêàçùôîûâÉÀ][^<>{}\n]*)</;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "node_modules" ? [] : files(full);
    return /\.(tsx?|jsx?)$/.test(name) ? [full] : [];
  });
}

describe("the screens' words", () => {
  it("are never French written into a component — always from the dictionaries", () => {
    const found: string[] = [];
    for (const dir of DIRS) {
      for (const file of files(path.join(ROOT, dir))) {
        if (ALLOWED.some((pattern) => pattern.test(file))) continue;
        readFileSync(file, "utf8")
          .split("\n")
          .forEach((line, at) => {
            const code = line.trim();
            if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*") || code.startsWith("{/*")) return;
            const match = FRENCH.exec(line);
            if (match) found.push(`${path.relative(ROOT, file)}:${at + 1}: ${(match[2] ?? match[3]).slice(0, 60)}`);
          });
      }
    }
    expect(found, "move these words to lib/i18n/dictionaries.ts").toEqual([]);
  });
});
