"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * What the page on screen is called, when only the page knows (LEKA-369).
 *
 * The registry knows a page by its address; an entity's sheet learns its
 * entity's name once the API answers. The sheet says it here, and the
 * browser tab (DocumentTitle) reads it — "Payment API · LEKA" rather than
 * an identifier made presentable. One page is on screen at a time: one name.
 */
let named: { pathname: string; name: string } | null = null;
const listeners = new Set<() => void>();

function publish(next: typeof named) {
  named = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Names the page at `pathname` while it is on screen. */
export function useNamePage(pathname: string, name: string | undefined) {
  useEffect(() => {
    if (!name) return;
    publish({ pathname, name });
    return () => {
      if (named?.pathname === pathname && named.name === name) publish(null);
    };
  }, [pathname, name]);
}

/** What the page at `pathname` said it is called, if it did. */
export function usePageName(pathname: string): string | undefined {
  const current = useSyncExternalStore(
    subscribe,
    () => named,
    () => null,
  );
  return current?.pathname === pathname ? current.name : undefined;
}
