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
