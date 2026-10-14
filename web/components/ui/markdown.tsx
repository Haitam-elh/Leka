import { Fragment } from "react";

import { cn } from "cn";

/**
 * An agent's report, read (2026-10-14: « où est son livrable ? »). The
 * markdown a model writes, drawn as a page in LEKA's own type. It covers:
 * - headings, paragraphs, lists (one level of nesting), quotes, rules;
 * - code blocks, and tables (`| a | b |`);
 * - inside a line: **bold**, *italic*, `code`, [links](https://…).
 *
 * Never HTML: what the model wrote is text, put in elements. A tag it
 * wrote is shown as written, never run. A link opens only http(s), in a new
 * tab.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: { text: string; children: string[] }[] }
  | { kind: "quote"; text: string }
  | { kind: "code"; text: string; lang: string }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "rule" };

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function blocksOf(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = /^```(\S*)/.exec(line.trim());
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push({ kind: "code", text: body.join("\n"), lang: fence[1] });
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push({ kind: "rule" });
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push({ kind: "table", head, rows });
      continue;
    }
    if (line.startsWith(">")) {
      const body: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) body.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push({ kind: "quote", text: body.join(" ") });
      continue;
    }
    const item = LIST.exec(line);
    if (item) {
      const ordered = /\d/.test(item[2]);
      const items: { text: string; children: string[] }[] = [];
      const base = item[1].length;
      while (i < lines.length) {
        const found = LIST.exec(lines[i]);
        if (found && found[1].length <= base) {
          items.push({ text: found[3], children: [] });
          i++;
        } else if (found && items.length) {
          items[items.length - 1].children.push(found[3]);
          i++;
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
          // A wrapped line of the item above.
          items[items.length - 1].text += ` ${lines[i].trim()}`;
          i++;
        } else break;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    const body: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6}\s|```|>|\s*([-*+]|\d+[.)])\s)/.test(lines[i]) &&
      !lines[i].trim().startsWith("|")
    ) {
      body.push(lines[i++].trim());
    }
    blocks.push({ kind: "paragraph", text: body.join(" ") });
  }
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;

/** A line's emphasis, code and links — as elements, never as HTML. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((part, index) => {
        if (!part) return null;
        if (/^(\*\*|__).+\1$/.test(part)) return <strong key={index}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
          return (
            <code key={index} className="rounded bg-shell-canvas px-1 py-0.5 font-mono text-[0.85em]">
              {part.slice(1, -1)}
            </code>
          );
        }
        const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
        if (link) {
          return /^https?:\/\//.test(link[2]) ? (
            <a
              key={index}
              href={link[2]}
              target="_blank"
              rel="noreferrer noopener"
              className="text-shell-nav-active underline underline-offset-2"
            >
              {link[1]}
            </a>
          ) : (
            <Fragment key={index}>{link[1]}</Fragment>
          );
        }
        if (/^([*_]).+\1$/.test(part)) return <em key={index}>{part.slice(1, -1)}</em>;
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}

const HEADING = [
  "text-[1.375rem] font-semibold tracking-[-0.01em]",
  "text-[1.125rem] font-semibold",
  "text-[1rem] font-semibold",
  "text-[0.9375rem] font-semibold",
  "text-[0.875rem] font-semibold",
  "text-[0.875rem] font-semibold",
];

export function Markdown({ source, className }: { source: string; className?: string }) {
  return (
    <div
      className={cn("flex flex-col gap-3 text-[0.9375rem] leading-relaxed text-brand-navy", className)}
      data-testid="markdown"
    >
      {blocksOf(source).map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Tag = `h${Math.min(block.level + 1, 6)}` as "h2";
            return (
              <Tag key={index} className={cn("mt-2 text-brand-navy", HEADING[block.level - 1])} dir="auto">
                <Inline text={block.text} />
              </Tag>
            );
          }
          case "paragraph":
            return (
              <p key={index} dir="auto">
                <Inline text={block.text} />
              </p>
            );
          case "quote":
            return (
              <blockquote key={index} className="border-s-2 border-brand-violet/40 ps-3 text-shell-muted" dir="auto">
                <Inline text={block.text} />
              </blockquote>
            );
          case "rule":
            return <hr key={index} className="border-shell-line" />;
          case "code":
            return (
              <pre
                key={index}
                className="overflow-x-auto rounded-lg bg-shell-canvas p-3 font-mono text-[0.8125rem] leading-5"
                data-lang={block.lang || undefined}
              >
                {block.text}
              </pre>
            );
          case "table":
            return (
              <div key={index} className="overflow-x-auto rounded-lg border border-shell-line">
                <table className="w-full text-start text-[0.8125rem]">
                  <thead className="bg-shell-canvas">
                    <tr>
                      {block.head.map((cell, c) => (
                        <th key={c} className="px-3 py-2 text-start font-semibold">
                          <Inline text={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-shell-line">
                    {block.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td key={c} className="px-3 py-2 align-top">
                            <Inline text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "list": {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List key={index} className={cn("flex flex-col gap-1 ps-5", block.ordered ? "list-decimal" : "list-disc")}>
                {block.items.map((item, n) => (
                  <li key={n} dir="auto">
                    <Inline text={item.text} />
                    {item.children.length ? (
                      <ul className="mt-1 flex list-[circle] flex-col gap-1 ps-5">
                        {item.children.map((child, c) => (
                          <li key={c}>
                            <Inline text={child} />
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </List>
            );
          }
        }
      })}
    </div>
  );
}
