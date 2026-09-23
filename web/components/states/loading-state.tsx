"use client";

import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** Under this, a skeleton is a flicker, not information. */
const SHOW_AFTER_MS = 200;

/**
 * Something is on its way.
 *
 * The shape of what is coming rather than a spinner: a page whose layout
 * jumps when the content lands makes people lose their place, and a
 * skeleton says roughly what they are about to read.
 *
 * NOTHING FOR THE FIRST 200 MS, to the eye or to a screen reader. Most
 * loads are faster than that, and a skeleton that flashes for a frame, or
 * a "Loading" read out for something already there, is noise.
 */
export function LoadingState({
  label,
  size = "page",
  delayMs = SHOW_AFTER_MS,
}: {
  /** What is loading, when there is something better to say than "Loading". */
  label?: string;
  size?: "page" | "section";
  delayMs?: number;
}) {
  const t = useDictionary();
  const [shown, setShown] = useState(delayMs === 0);

  useEffect(() => {
    if (delayMs === 0) return;
    const timer = window.setTimeout(() => setShown(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs]);

  return (
    // The region is there from the start and filled later: a live region
    // that appears already full is not reliably announced.
    <div role="status" data-testid="loading-state">
      {shown ? (
        <>
          <span className="sr-only">{label ?? t.states.loading}</span>
          {size === "page" ? <PageSkeleton /> : <SectionSkeleton />}
        </>
      ) : null}
    </div>
  );
}

function PageSkeleton() {
  return (
    <div aria-hidden="true" className="mx-auto w-full max-w-content px-4 py-6 sm:px-6 lg:px-8">
      <Skeleton className="h-7 w-64" />
      <Skeleton className="mt-3 h-4 w-96 max-w-full" />
      <div className="mt-8 grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <Skeleton className="mt-4 h-4 w-3/4" />
      <Skeleton className="mt-2 h-4 w-1/2" />
    </div>
  );
}

function SectionSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-2 py-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}
