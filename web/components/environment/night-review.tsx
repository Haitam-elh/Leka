"use client";

import { Loader2, MoonStar } from "lucide-react";

import { cn } from "cn";

import { Card, IconTile } from "@/components/environment/parts";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api";
import { useNightReviewSetting, useNightReviewSettingChange } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * The night review, an alert each workspace chooses (LEKA-526): on, LEKA
 * goes through the environment every hour of the night and tells the
 * morning, in the application and by e-mail; off, no review at night and
 * nothing told — past reviews stay. A setting among the alerts', never a
 * card on the environment's overview. Read-only for whoever may not manage
 * the sources and the alerts.
 */

/** An hour of the night, given in UTC (« 21:30 »), as the reader's clock says it. */
function localHour(utc: string, locale: string): string {
  const [hours, minutes] = utc.split(":").map(Number);
  const at = new Date();
  at.setUTCHours(hours ?? 0, minutes ?? 0, 0, 0);
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(at);
}

export function NightReviewSetting({ id }: { id?: string }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.night.setting;
  const setting = useNightReviewSetting();
  const change = useNightReviewSettingChange();
  const said = setting.data;

  async function turn(on: boolean) {
    try {
      await change.mutateAsync(on);
      notify.success({ title: on ? w.turnedOn : w.turnedOff });
    } catch (problem) {
      notify.error({ title: problem instanceof ApiError ? problem.message : w.failed });
    }
  }

  let body: React.ReactNode;
  if (setting.isError) {
    body = (
      <p className="text-[0.8125rem] text-state-danger" data-testid="night-review-setting-failed">
        {w.loadFailed}
      </p>
    );
  } else if (!said) {
    body = <div className="h-14 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  } else {
    const hours = said.hours_utc;
    const from = hours.length ? localHour(hours[0], locale) : "";
    const to = hours.length ? localHour(hours[hours.length - 1], locale) : "";
    body = (
      <div className="flex flex-col gap-2" data-testid="night-review-setting" data-enabled={said.enabled}>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-shell-line bg-shell-canvas/50 px-3 py-2.5">
          <span className="min-w-0">
            <span id="night-review-setting-label" className="block text-[0.875rem] font-semibold text-brand-navy">
              {w.label}
            </span>
            <span
              className={cn("block text-xs font-medium", said.enabled ? "text-state-success" : "text-shell-muted")}
              data-testid="night-review-setting-state"
            >
              {said.enabled ? w.on : w.off}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-2">
            {change.isPending ? <Loader2 className="size-3.5 animate-spin text-shell-muted" aria-hidden="true" /> : null}
            <Switch
              checked={said.enabled}
              disabled={!said.can_change || change.isPending}
              onCheckedChange={(checked) => void turn(Boolean(checked))}
              aria-labelledby="night-review-setting-label"
              data-testid="night-review-toggle"
            />
          </span>
        </div>
        <p className="text-[0.8125rem] text-shell-muted">{fill(w.explain, { from, to })}</p>
        <p className="text-[0.8125rem] text-shell-muted">{said.enabled ? w.whenOn : w.whenOff}</p>
        {said.can_change ? null : (
          <p className="text-xs text-shell-muted" data-testid="night-review-setting-readonly">
            {w.readOnly}
          </p>
        )}
      </div>
    );
  }

  return (
    <Card title={w.label} icon={<IconTile icon={MoonStar} tone="violet" className="size-9" />} id={id}>
      {body}
    </Card>
  );
}
