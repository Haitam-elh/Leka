"use client";

import { BellOff, CheckCheck } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { NotificationRow } from "@/components/notifications/notification-row";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useDictionary } from "@/lib/i18n/locale-provider";
import {
  NOTIFICATION_CATEGORIES,
  type NotificationCategory,
} from "@/lib/notifications";
import {
  useMarkAllNotifications,
  useMuteNotifications,
  useNotificationPreferences,
  useNotifications,
  useUnreadNotifications,
} from "@/lib/notifications-queries";

const CHIP =
  "rounded-full border px-3 py-1.5 text-[0.8125rem] font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-brand-violet/40";

/**
 * The notification centre (LEKA-476): what happened in the workspace, the
 * latest first — by category, the unread only — each to where it leads,
 * read or not as one left it, all read at once; a page at a time. Beside
 * it, what one wants told here — in the application only: the monitoring
 * alerts' e-mails are set with the alerts.
 */
export function NotificationsScreen() {
  const t = useDictionary();
  const w = t.notifications;
  const [category, setCategory] = useState<NotificationCategory | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const list = useNotifications({ category, unread: unreadOnly });
  const unread = useUnreadNotifications().data?.unread ?? 0;
  const markAll = useMarkAllNotifications();
  const rows = list.data?.pages.flatMap((page) => page.data) ?? [];
  const categories = w.categories as Record<string, string>;

  return (
    <PageContainer>
      <PageHeader
        title={w.title}
        subtitle={w.subtitle}
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={unread === 0 || markAll.isPending}
            onClick={() => markAll.mutate(category)}
            data-testid="notifications-read-all"
          >
            <CheckCheck aria-hidden="true" />
            {w.markAll}
          </Button>
        }
      />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <section className="min-w-0 space-y-4" aria-label={w.title}>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={w.filters}>
            <button
              type="button"
              aria-pressed={category === null}
              onClick={() => setCategory(null)}
              className={cn(
                CHIP,
                category === null
                  ? "border-brand-violet bg-brand-violet text-white"
                  : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
              )}
              data-testid="notifications-filter"
              data-category="all"
            >
              {w.all}
            </button>
            {NOTIFICATION_CATEGORIES.map((one) => (
              <button
                key={one}
                type="button"
                aria-pressed={category === one}
                onClick={() => setCategory(one)}
                className={cn(
                  CHIP,
                  category === one
                    ? "border-brand-violet bg-brand-violet text-white"
                    : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
                )}
                data-testid="notifications-filter"
                data-category={one}
              >
                {categories[one]}
              </button>
            ))}
            <span className="ms-auto flex items-center gap-2 text-[0.8125rem] text-brand-navy">
              <Switch
                checked={unreadOnly}
                onCheckedChange={(checked) => setUnreadOnly(Boolean(checked))}
                aria-label={w.unreadOnly}
                data-testid="notifications-unread-only"
              />
              {w.unreadOnly}
            </span>
          </div>

          {list.isError ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} size="section" />
          ) : list.isPending ? (
            <ul className="space-y-2" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="h-16 animate-pulse rounded-xl bg-shell-canvas" />
              ))}
            </ul>
          ) : rows.length === 0 ? (
            <StatePanel
              icon={BellOff}
              title={unreadOnly ? w.emptyUnread : w.empty}
              description={unreadOnly ? undefined : w.emptyHint}
              size="section"
              testId="notifications-empty"
            />
          ) : (
            <div className="rounded-2xl border border-shell-line bg-white p-2">
              <ul className="space-y-1" data-testid="notifications-list">
                {rows.map((notification) => (
                  <NotificationRow key={notification.id} notification={notification} />
                ))}
              </ul>
              {list.hasNextPage ? (
                <div className="mt-2 flex justify-center border-t border-shell-line pt-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={list.isFetchingNextPage}
                    onClick={() => void list.fetchNextPage()}
                    data-testid="notifications-more"
                  >
                    {w.loadMore}
                  </Button>
                </div>
              ) : null}
            </div>
          )}
        </section>
        <Preferences />
      </div>
    </PageContainer>
  );
}

function Preferences() {
  const t = useDictionary();
  const w = t.notifications;
  const said = useNotificationPreferences();
  const mute = useMuteNotifications();
  const muted = new Set(said.data?.muted ?? []);
  const categories = w.categories as Record<string, string>;
  return (
    <section
      aria-labelledby="notification-preferences"
      className="rounded-2xl border border-shell-line bg-white p-5"
      data-testid="notification-preferences"
    >
      <h2 id="notification-preferences" className="text-[1rem] font-bold text-brand-navy">
        {w.preferences.title}
      </h2>
      <p className="mt-1 text-[0.8125rem] text-shell-muted">{w.preferences.lead}</p>
      <ul className="mt-4 space-y-3">
        {NOTIFICATION_CATEGORIES.map((one) => {
          const shown = !muted.has(one);
          return (
            <li key={one} className="flex items-center justify-between gap-3 text-[0.875rem] text-brand-navy">
              <span>
                {categories[one]}
                <span className="block text-xs text-shell-muted">
                  {shown ? w.preferences.shown : w.preferences.hidden}
                </span>
              </span>
              <Switch
                checked={shown}
                disabled={said.isPending || mute.isPending}
                onCheckedChange={(checked) => {
                  const next = new Set(muted);
                  if (checked) next.delete(one);
                  else next.add(one);
                  mute.mutate([...next]);
                }}
                aria-label={categories[one]}
                data-testid="notification-preference"
                data-category={one}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
