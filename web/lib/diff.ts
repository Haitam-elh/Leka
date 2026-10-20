/**
 * A unified diff, line by line, each numbered as the review numbers it
 * (leka/capabilities/review.py): the old file's number for what was removed
 * or kept, the new file's for what was added or kept — so a comment on
 * « line 42, new side » finds its line.
 */

export type DiffRow = {
  kind: "hunk" | "add" | "remove" | "same";
  text: string;
  old: number | null;
  new: number | null;
};

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function diffRows(patch: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let old = 0;
  let fresh = 0;
  for (const text of patch.replace(/\n$/, "").split("\n")) {
    const hunk = HUNK.exec(text);
    if (hunk) {
      old = Number(hunk[1]);
      fresh = Number(hunk[2]);
      rows.push({ kind: "hunk", text, old: null, new: null });
    } else if (text.startsWith("\\")) {
      continue;
    } else if (text.startsWith("+")) {
      rows.push({ kind: "add", text: text.slice(1), old: null, new: fresh++ });
    } else if (text.startsWith("-")) {
      rows.push({ kind: "remove", text: text.slice(1), old: old++, new: null });
    } else if (old || fresh) {
      rows.push({ kind: "same", text: text.slice(1), old: old++, new: fresh++ });
    }
  }
  return rows;
}

/** The row a comment sits under: its line, on its side. */
export function rowOf(
  rows: readonly DiffRow[],
  line: number,
  side: "new" | "old",
): number {
  return rows.findIndex((row) => (side === "new" ? row.new === line : row.old === line && row.kind !== "add"));
}

export type SplitCell = { number: number; text: string; change: "same" | "remove" | "add" };
export type SplitRow =
  | { kind: "hunk"; text: string }
  | { kind: "pair"; left: SplitCell | null; right: SplitCell | null };

/** A diff as two pages side by side: the file before on the left, after on
 * the right — each line numbered as in its file, what was removed beside
 * what replaced it, unchanged lines on both sides. The file names above the
 * first hunk (a diff LEKA computed has them) are not lines. */
export function splitRows(diff: string): SplitRow[] {
  const first = diff.startsWith("@@") ? 0 : diff.indexOf("\n@@") + 1;
  const rows: SplitRow[] = [];
  let removed: SplitCell[] = [];
  let added: SplitCell[] = [];
  const flush = () => {
    for (let i = 0; i < Math.max(removed.length, added.length); i++) {
      rows.push({ kind: "pair", left: removed[i] ?? null, right: added[i] ?? null });
    }
    removed = [];
    added = [];
  };
  for (const row of first > 0 || diff.startsWith("@@") ? diffRows(diff.slice(first)) : []) {
    if (row.kind === "hunk") {
      flush();
      rows.push({ kind: "hunk", text: row.text });
    } else if (row.kind === "remove") {
      removed.push({ number: row.old ?? 0, text: row.text, change: "remove" });
    } else if (row.kind === "add") {
      added.push({ number: row.new ?? 0, text: row.text, change: "add" });
    } else {
      flush();
      rows.push({
        kind: "pair",
        left: { number: row.old ?? 0, text: row.text, change: "same" },
        right: { number: row.new ?? 0, text: row.text, change: "same" },
      });
    }
  }
  flush();
  return rows;
}

/** One modification of a file: a hunk of its diff, with the lines it
 * changes — numbered in the new file, or the old one for what is only
 * removed — and what it adds and removes. */
export type Hunk = {
  text: string;
  from: number;
  to: number;
  added: number;
  removed: number;
};

/** A file's diff, modification by modification (2026-10-19: « montre-moi
 * toutes les modifs, modif 1, modif 2, chacune dépliable »). */
export function hunksOf(diff: string): Hunk[] {
  const hunks: string[][] = [];
  for (const line of diff.replace(/\n$/, "").split("\n")) {
    if (HUNK.test(line)) hunks.push([line]);
    else if (hunks.length) hunks[hunks.length - 1].push(line);
  }
  return hunks.map((lines) => {
    const rows = diffRows(lines.join("\n"));
    const changed = rows.filter((row) => row.kind === "add" || row.kind === "remove");
    const numbers = changed.map((row) => row.new ?? row.old ?? 0).filter((n) => n > 0);
    return {
      text: lines.join("\n"),
      from: numbers.length ? Math.min(...numbers) : 0,
      to: numbers.length ? Math.max(...numbers) : 0,
      added: changed.filter((row) => row.kind === "add").length,
      removed: changed.filter((row) => row.kind === "remove").length,
    };
  });
}

