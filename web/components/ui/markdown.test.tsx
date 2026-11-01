/**
 * An agent's report, drawn (components/ui/markdown.tsx) — what a model
 * writes as it writes it (2026-10-31, a database review):
 * - a file name's underscores stay in it, never set in italics;
 * - « 1. » written before each step, blank lines between them: one list,
 *   numbered on;
 * - SQL written at the end of a step's line, or under it: drawn as code;
 * - a table whose header has fewer cells than its rows: every cell drawn;
 * - code inside bold, as a model titles a point: drawn as code (2026-11-01).
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { blocksOf, Markdown } from "@/components/ui/markdown";

describe("an agent's report, drawn", () => {
  it("keeps a file name's underscores in it, and still sets _emphasis_ apart", () => {
    render(<Markdown source={"Migration [20260919_003_encrypt_source_credentials.py:20-25] and _this_."} />);
    const text = screen.getByTestId("markdown");
    expect(text).toHaveTextContent("20260919_003_encrypt_source_credentials.py:20-25");
    const emphasis = text.querySelectorAll("em");
    expect([...emphasis].map((e) => e.textContent)).toEqual(["this"]);
  });

  it("numbers on a list whose steps are apart, each with its code", () => {
    const source = [
      "1. **Corriger l'absence de tables**",
      "   - **Où** : base PostgreSQL.",
      "",
      "1. **Ajouter les index manquants** ```sql CREATE INDEX ix_a ON a(b);```",
      "   - **Où** : `a.b`.",
      "",
      "1. **Remplacer FLOAT**",
      "   ```sql",
      "   ALTER TABLE e ALTER COLUMN c TYPE NUMERIC(3,2);",
      "   ```",
      "   - **Où** : `e.c`.",
    ].join("\n");
    const blocks = blocksOf(source);
    expect(blocks).toHaveLength(1);
    render(<Markdown source={source} />);
    const list = screen.getByTestId("markdown").querySelector("ol") as HTMLElement;
    expect(screen.getByTestId("markdown").querySelectorAll("ol")).toHaveLength(1);
    const steps = within(list).getAllByRole("listitem").filter((li) => li.parentElement === list);
    expect(steps).toHaveLength(3);
    expect(steps[1]).toHaveTextContent("Ajouter les index manquants");
    expect(steps[1].querySelector("pre")).toHaveTextContent("CREATE INDEX ix_a ON a(b);");
    expect(steps[1]).not.toHaveTextContent("```");
    expect(steps[2].querySelector("pre")).toHaveTextContent("ALTER TABLE e ALTER COLUMN c TYPE NUMERIC(3,2);");
  });

  it("draws every cell of a table whose header is short", () => {
    render(<Markdown source={"| Table | Problème |\n|---|---|\n| `sessions` | `user_agent` | Mineur |"} />);
    expect(screen.getAllByRole("columnheader")).toHaveLength(3);
    expect(screen.getByRole("cell", { name: "Mineur" })).toBeInTheDocument();
  });

  it("draws the code a bold title holds as code, never its backticks", () => {
    render(<Markdown source={"1. **Zéro inférence (`night.py:17`)** : aucun *modèle (`gemini`)*."} />);
    const text = screen.getByTestId("markdown");
    expect(text).not.toHaveTextContent("`");
    expect(text.querySelector("strong code")?.textContent).toBe("night.py:17");
    expect(text.querySelector("em code")?.textContent).toBe("gemini");
  });
});
