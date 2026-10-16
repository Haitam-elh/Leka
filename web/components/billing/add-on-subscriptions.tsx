"use client";

import { Bot } from "lucide-react";

import { IconTile, TILE_TONES } from "@/components/environment/parts";
import { useConfirm } from "@/components/interactions/confirm";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { AddOns, Entitlement } from "@/lib/billing";
import { useAddOnRenewal, useAddOns, useEntitlements } from "@/lib/billing-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * Vos agents et bundles (LEKA-474): each subscription bought besides the plan
 * — renewed every month until cancelled. « Annuler l'abonnement » while it
 * renews; cancelled, the day it stays until and « Réactiver le
 * renouvellement ». Its state is the server's, as Stripe last said it; the
 * plan's subscription and the others are never touched by it.
 */
export function AddOnSubscriptions() {
  const t = useDictionary();
  const w = t.billing.subscription;
  const a = w.addOns;
  const { format: locale } = useLocale();
  const owned = useEntitlements().data;
  const offers = useAddOns().data;
  const renewal = useAddOnRenewal();
  const confirm = useConfirm();
  const pays = usePermissions()?.includes("workspace:update") ?? false;

  // One line a subscription: several agents bought together share one.
  const bought = new Map<string, Entitlement[]>();
  for (const each of owned ?? []) {
    if (each.origin !== "purchase" || !each.subscription) continue;
    bought.set(each.subscription, [...(bought.get(each.subscription) ?? []), each]);
  }
  if (!bought.size) return null;

  const day = (iso: string) => new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(iso));
  const nameOf = (each: Entitlement) => named(offers, each, locale);
  const failed = (error: unknown) =>
    notify.error({ title: error instanceof ApiError ? error.message : w.failed });

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-add-ons">
      <div className="mb-3 flex items-center gap-3">
        <IconTile icon={Bot} tone="violet" />
        <h2 className="font-semibold text-brand-navy">{a.title}</h2>
      </div>
      <ul className="divide-y divide-shell-line">
        {[...bought.entries()].map(([subscription, rows]) => {
          const [first] = rows;
          const name = rows.map(nameOf).join(", ");
          const end = first.current_period_end;
          const cancelled = first.cancel_at_period_end;
          return (
            <li
              key={subscription}
              className="flex flex-wrap items-center justify-between gap-3 py-3"
              data-testid="billing-add-on"
              data-cancelled={cancelled || undefined}
            >
              <div className="min-w-0">
                <p className="font-medium text-brand-navy">{name}</p>
                <p
                  className={cancelled ? `mt-1 rounded-lg px-2 py-1 text-[0.8125rem] ${TILE_TONES.warning}` : "text-xs text-shell-muted"}
                >
                  {cancelled
                    ? end ? fill(a.endsOn, { date: day(end) }) : a.ends
                    : end ? fill(a.renewsOn, { date: day(end) }) : a.renews}
                </p>
              </div>
              {pays ? (
                cancelled ? (
                  <Button
                    type="button"
                    disabled={renewal.isPending}
                    onClick={() =>
                      renewal.mutate(
                        { subscription, renew: true },
                        { onSuccess: () => notify.success({ title: fill(a.resumed, { name }) }), onError: failed },
                      )
                    }
                    data-testid="billing-add-on-renew"
                  >
                    {w.resumeRenewal}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={renewal.isPending}
                    onClick={async () => {
                      const ok = await confirm({
                        title: fill(a.stopTitle, { name }),
                        description: fill(a.stopBody, { name, date: end ? day(end) : a.periodEnd }),
                        confirmLabel: w.stopConfirm,
                        cancelLabel: w.keep,
                      });
                      if (!ok) return;
                      renewal.mutate(
                        { subscription, renew: false },
                        { onSuccess: () => notify.success({ title: fill(a.stopped, { name }) }), onError: failed },
                      );
                    }}
                    data-testid="billing-add-on-cancel"
                  >
                    {w.stopRenewal}
                  </Button>
                )
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** An agent's title, a bundle's name — its key while the catalogue is read. */
function named(offers: AddOns | undefined, each: Entitlement, locale: string): string {
  if (each.kind === "bundle") {
    const bundle = offers?.bundles.find((b) => b.key === each.key);
    if (bundle) return locale.startsWith("en") ? bundle.name.en : bundle.name.fr;
  }
  return offers?.agents.find((agent) => agent.key === each.key)?.title ?? each.key;
}
