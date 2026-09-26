"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

export interface MetadataItem {
  label: string;
  /** Anything: a word, a link, a badge. Empty shows "—". */
  value: React.ReactNode;
  /** Makes the value copyable: this string is what lands in the clipboard. */
  copyValue?: string;
}

export interface MetadataSection {
  title?: string;
  items: readonly MetadataItem[];
}

export interface MetadataPanelProps {
  sections: readonly MetadataSection[];
  columns?: 1 | 2;
  /** Offer a copy button on every item whose value is plain text. */
  copyable?: boolean;
  className?: string;
}

function isEmpty(value: React.ReactNode): boolean {
  return value === null || value === undefined || value === "" || value === false;
}

function CopyButton({ label, text }: { label: string; text: string }) {
  const t = useDictionary();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Some app views refuse the clipboard. Nothing is claimed as copied,
      // and the value is still there to select by hand.
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={fill(t.knowledge.metadata.copy, { label })}
        className="rounded p-0.5 text-shell-icon outline-none hover:text-shell-nav-active focus-visible:ring-2 focus-visible:ring-brand-violet/40"
      >
        {copied ? (
          <Check aria-hidden="true" className="size-3.5 text-state-success" />
        ) : (
          <Copy aria-hidden="true" className="size-3.5" />
        )}
      </button>
      <span role="status" className="sr-only">
        {copied ? fill(t.knowledge.metadata.copied, { label }) : ""}
      </span>
    </>
  );
}

/**
 * Label and value pairs, in sections (LEKA-340) — the "Informations
 * générales" of mockup 11. A real description list, so each value is read
 * with its label.
 */
export function MetadataPanel({
  sections,
  columns = 1,
  copyable = false,
  className,
}: MetadataPanelProps) {
  const filled = sections.filter((section) => section.items.length > 0);
  if (filled.length === 0) return null;

  return (
    <div data-slot="metadata-panel" className={cn("flex flex-col gap-4", className)}>
      {filled.map((section, index) => (
        <section key={section.title ?? index}>
          {section.title ? (
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-shell-muted uppercase">
              {section.title}
            </h3>
          ) : null}
          <dl
            className={cn("grid gap-x-6 gap-y-2", columns === 2 ? "sm:grid-cols-2" : "grid-cols-1")}
          >
            {section.items.map((item) => {
              const text =
                item.copyValue ??
                (copyable && (typeof item.value === "string" || typeof item.value === "number")
                  ? String(item.value)
                  : undefined);
              return (
                <div
                  key={item.label}
                  className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3"
                >
                  <dt className="truncate text-[0.8125rem] text-shell-muted">{item.label}</dt>
                  <dd className="flex min-w-0 items-center gap-1.5 text-[0.8125rem] text-brand-navy">
                    {isEmpty(item.value) ? (
                      <span className="text-shell-muted">—</span>
                    ) : (
                      <span className="min-w-0 break-words">{item.value}</span>
                    )}
                    {text && !isEmpty(item.value) ? (
                      <CopyButton label={item.label} text={text} />
                    ) : null}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ))}
    </div>
  );
}
