"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { CatalogueScreen } from "@/components/capabilities/catalogue";
import { V2 } from "@/config/v2-routes";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** The new interface's second screen (2026-10-14, Lot 6): the agents and
 * their bundles — Lot 2's catalogue, each with its price, what it takes and
 * the way to buy it — its « Demander » back to the home's bar. */
export function AgentsScreen() {
  const t = useDictionary();
  return (
    <div className="mx-auto w-full max-w-6xl" data-testid="v2-agents-screen">
      <title>{`${t.v2.agentsPage.title} · LEKA`}</title>
      <Link
        href={V2.home}
        className="mb-2 inline-flex items-center gap-1 text-[0.8125rem] font-medium text-brand-violet hover:underline"
      >
        <ArrowLeft className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
        {t.v2.agentsPage.back}
      </Link>
      <CatalogueScreen askHref={V2.home} />
    </div>
  );
}
