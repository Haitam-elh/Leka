"use client";

import { Bot, Check, CreditCard, Lightbulb, type LucideIcon, Mail, Plug, Siren, Users } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { exactDate, timeAgo } from "@/components/knowledge/time";
import { wordsOf } from "@/components/notifications/words";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Notification, NotificationCategory, NotificationSeverity } from "@/lib/notifications";
import { useMarkNotification } from "@/lib/notifications-queries";

const ICONS: Record<NotificationCategory, LucideIcon> = {
  intention: Lightbulb,
  agent: Bot,
  source: Plug,
  monitoring: Siren,
  billing: CreditCard,
  workspace: Users,
};

const TONES: Record<NotificationSeverity, string> = {
  info: "bg-state-info-soft text-state-info",
  success: "bg-state-success-soft text-state-success",
  warning: "bg-state-warning-soft text-state-warning",
  critical: "bg-state-danger-soft text-state-danger",
};

/**
 * One notification (LEKA-476): what happened, in words; how grave; when;
 * where it leads — opened, it is read — and read or not, as one left it.
 */
export function NotificationRow({
  notification,
  onOpen,
}: {
  notification: Notification;
  /** Opened: what holds it (the bell's panel) may close. */
  onOpen?: () => void;
}) {
  const t = useDictionary();
  const w = t.notifications;
  const { format } = useLocale();
  const mark = useMarkNotification();
  const { title, body } = wordsOf(t, notification, format);
  const Icon = ICONS[notification.category] ?? Lightbulb;
  const unread = !notification.read;
  const heading = (
    <>
      {title}
      {unread ? <span className="sr-only"> · {w.unread}</span> : null}
    </>
  );
  return (
    <li
      className={cn(
        "flex items-start gap-3 rounded-xl px-3 py-2.5",
        unread ? "bg-brand-violet-soft/45" : "bg-transparent",
      )}
      data-testid="notification"
      data-kind={notification.kind}
      data-read={notification.read}
    >
      <span
        className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg", TONES[notification.severity])}
        title={(w.severities as Record<string, string>)[notification.severity]}
      >
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        {notification.link ? (
          <Link
            href={notification.link}
            onClick={() => {
              if (unread) mark.mutate({ id: notification.id, read: true });
              onOpen?.();
            }}
            className={cn(
              "rounded text-[0.875rem] text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40",
              unread ? "font-semibold" : "font-medium",
            )}
            data-testid="notification-open"
          >
            {heading}
          </Link>
        ) : (
          <p className={cn("text-[0.875rem] text-brand-navy", unread ? "font-semibold" : "font-medium")}>
            {heading}
          </p>
        )}
        {body ? <p className="mt-0.5 text-[0.8125rem] text-shell-muted">{body}</p> : null}
        <p className="mt-1 text-[0.6875rem] text-shell-muted">
          <time dateTime={notification.occurred_at} title={exactDate(format, notification.occurred_at)}>
            {timeAgo(t, notification.occurred_at)}
          </time>
          {" · "}
          {(w.categories as Record<string, string>)[notification.category]}
        </p>
      </div>
      <button
        type="button"
        onClick={() => mark.mutate({ id: notification.id, read: unread })}
        aria-label={unread ? w.markRead : w.markUnread}
        title={unread ? w.markRead : w.markUnread}
        className="mt-0.5 shrink-0 rounded-md p-1.5 text-shell-muted outline-none hover:bg-white hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        data-testid="notification-toggle"
      >
        {unread ? <Check className="size-4" aria-hidden="true" /> : <Mail className="size-4" aria-hidden="true" />}
      </button>
    </li>
  );
}
