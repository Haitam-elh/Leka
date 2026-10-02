"use client";

import { usePathname } from "next/navigation";

import { documentTitle } from "@/lib/navigation/breadcrumb";
import { usePageName } from "@/lib/navigation/page-name";
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
 * and the loser is whichever ran last. A page that knows its own name —
 * an entity's sheet — says it through page-name.ts rather than rendering a
 * <title> of its own.
 */
export function DocumentTitle() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const name = usePageName(pathname);

  return <title>{documentTitle(pathname, t, name)}</title>;
}
