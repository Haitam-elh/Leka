"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { NotificationRow } from "@/components/notifications/notification-row";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import {
  useMarkAllNotifications,
  useNotifications,
  useUnreadNotifications,
} from "@/lib/notifications-queries";

/**
 * The bell, in the header (LEKA-476): how many are unread — asked every
 * minute, and again whenever the window is back — and, opened, the latest
 * few, each to where it leads; all read at once; the centre one click on.
 */
export function NotificationBell({ className }: { className?: string }) {
  const t = useDictionary();
  const w = t.notifications;
  const [open, setOpen] = useState(false);
  const unread = useUnreadNotifications().data?.unread ?? 0;
  const latest = useNotifications({}, 6, open);
  const markAll = useMarkAllNotifications();
  const rows = latest.data?.pages.flatMap((page) => page.data) ?? [];
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={unread > 0 ? fill(w.bellUnread, { count: unread }) : w.bell}
        className={cn("relative", className)}
        data-testid="notifications-bell"
      >
        <Bell className="size-5" aria-hidden="true" />
        {unread > 0 ? (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[1.125rem] rounded-full bg-state-danger px-1 text-center text-[0.625rem] leading-[1.125rem] font-bold text-white tabular-nums"
            data-testid="notifications-count"
            aria-hidden="true"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[23rem] max-w-[calc(100vw-1.5rem)] gap-0 overflow-hidden p-0"
        data-testid="notifications-panel"
      >
        <div className="flex items-center justify-between gap-3 border-b border-shell-line px-4 py-3">
          <h2 className="text-[0.9375rem] font-semibold text-brand-navy">{w.latest}</h2>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={unread === 0 || markAll.isPending}
            onClick={() => markAll.mutate(null)}
            data-testid="notifications-read-all"
          >
            {w.markAll}
          </Button>
        </div>
        <div className="max-h-[26rem] overflow-y-auto p-2" aria-busy={latest.isPending && open}>
          {latest.isError ? (
            <p className="px-3 py-6 text-center text-[0.8125rem] text-state-danger" role="alert">
              {w.error}
            </p>
          ) : latest.isPending ? (
            <ul className="space-y-2" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <li key={i} className="h-14 animate-pulse rounded-xl bg-shell-canvas" />
              ))}
            </ul>
          ) : rows.length === 0 ? (
            <p className="px-3 py-6 text-center text-[0.8125rem] text-shell-muted" data-testid="notifications-empty">
              {w.empty}
            </p>
          ) : (
            <ul className="space-y-1">
              {rows.map((notification) => (
                <NotificationRow key={notification.id} notification={notification} onOpen={() => setOpen(false)} />
              ))}
            </ul>
          )}
        </div>
        <div className="border-t border-shell-line px-4 py-2.5 text-center">
          <Link
            href={routes.notifications()}
            onClick={() => setOpen(false)}
            className="rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            data-testid="notifications-see-all"
          >
            {w.seeAll}
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}
