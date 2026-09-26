import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { KnowledgeGallery } from "./gallery";

export const metadata: Metadata = { title: "Composants knowledge — LEKA" };

/**
 * Every knowledge component, with complete, partial, empty and large data
 * (LEKA-340). Development only, like the other galleries beside it — see
 * /_dev/forms for why the folder is spelled %5Fdev.
 */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <KnowledgeGallery />;
}
