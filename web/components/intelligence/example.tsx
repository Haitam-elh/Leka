"use client";

import { FlaskConical } from "lucide-react";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Says, before anything else, that what follows is an example (LEKA-341):
 * a screen that shows LEKA's outputs before LEKA can produce them never
 * lets them pass for the customer's own.
 */
export function ExampleNotice({ body }: { body?: string }) {
  const t = useDictionary();
  const w = t.intelligence.example;
  return (
    <p
      role="note"
      className="flex items-start gap-2 rounded-lg bg-state-info-soft px-3 py-2 text-[0.8125rem] text-brand-navy"
      data-testid="example-notice"
    >
      <FlaskConical className="mt-0.5 size-4 shrink-0 text-state-info" aria-hidden="true" />
      <span>
        <span className="font-semibold">{w.title} · </span>
        {body ?? w.body}
      </span>
    </p>
  );
}
