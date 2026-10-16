/**
 * The notification centre (LEKA-476): what happened in the workspace, told
 * to whom it concerns — read from what its systems kept, once each; read or
 * not, as each person left it; muted by category.
 *
 * In the application only: the monitoring alerts' e-mails are set with the
 * alerts, never here.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Notification = components["schemas"]["NotificationOut"];
export type NotificationPage = components["schemas"]["NotificationPage"];
export type NotificationCategory = Notification["category"];
export type NotificationSeverity = Notification["severity"];

export const NOTIFICATION_CATEGORIES: readonly NotificationCategory[] = [
  "intention",
  "agent",
  "source",
  "monitoring",
  "billing",
  "workspace",
];

export type NotificationFilters = {
  category?: NotificationCategory | null;
  unread?: boolean;
};

const BASE = "/notifications";

export const notifications = {
  page: (filters: NotificationFilters, cursor: string | null, limit = 20) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (filters.category) query.set("category", filters.category);
    if (filters.unread) query.set("unread", "true");
    if (cursor) query.set("cursor", cursor);
    return apiFetch<NotificationPage>(`${BASE}?${query.toString()}`);
  },
  unread: () => apiFetch<{ unread: number }>(`${BASE}/unread`),
  read: (id: string) => apiFetch<void>(`${BASE}/${encodeURIComponent(id)}/read`, { method: "POST" }),
  unreadAgain: (id: string) =>
    apiFetch<void>(`${BASE}/${encodeURIComponent(id)}/read`, { method: "DELETE" }),
  readAll: (category: NotificationCategory | null) =>
    apiFetch<{ marked: number }>(`${BASE}/read`, {
      method: "POST",
      body: JSON.stringify(category ? { category } : {}),
    }),
  preferences: () => apiFetch<{ muted: NotificationCategory[] }>(`${BASE}/preferences`),
  mute: (muted: NotificationCategory[]) =>
    apiFetch<{ muted: NotificationCategory[] }>(`${BASE}/preferences`, {
      method: "PUT",
      body: JSON.stringify({ muted }),
    }),
};
