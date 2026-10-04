import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IntelligenceGallery } from "./gallery";

export const metadata: Metadata = { title: "Composants d'intelligence — LEKA" };

/**
 * Every intelligence component, and an analysis in each of its states —
 * complete, partial, inconclusive, failed, none yet (LEKA-341).
 * Development only, like the other galleries beside it — see /_dev/forms
 * for why the folder is spelled %5Fdev.
 */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <IntelligenceGallery />;
}
