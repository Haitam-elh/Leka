"use client";

import { usePathname } from "next/navigation";

import { documentTitle } from "@/lib/navigation/breadcrumb";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * "Payment API · LEKA" in the browser tab, from the registry.
 *
 * A rendered <title>, not `document.title = …` in an effect: Next applies
 * its own metadata after every navigation and overwrote the assignment, so
 * the tab kept saying "LEKA" everywhere. React 19 hoists this element into
 * the head from wherever it is rendered, which is why a client component in
 * the middle of the tree may own it.
 *
 * The root layout therefore exports no `title` — two owners, one <title>,
 * and the loser is whichever ran last.
 */
export function DocumentTitle() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";

  return <title>{documentTitle(pathname, t)}</title>;
}
