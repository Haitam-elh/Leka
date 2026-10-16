"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type NotificationCategory,
  type NotificationFilters,
  notifications,
} from "@/lib/notifications";

export const notificationKeys = {
  all: ["notifications"] as const,
  list: (filters: NotificationFilters) => ["notifications", "list", filters] as const,
  unread: ["notifications", "unread"] as const,
  preferences: ["notifications", "preferences"] as const,
};

/** How often the bell asks: what is new is read in on the server as it asks. */
export const BELL_EVERY_MS = 60_000;

/** How many are unread — the bell's count, asked again every minute and
 * whenever the window is back in front. */
export function useUnreadNotifications(enabled = true) {
  return useQuery({
    queryKey: notificationKeys.unread,
    queryFn: notifications.unread,
    refetchInterval: BELL_EVERY_MS,
    refetchOnWindowFocus: true,
    enabled,
  });
}

/** The latest first, a page at a time — asked only when shown. */
export function useNotifications(filters: NotificationFilters, limit = 20, enabled = true) {
  return useInfiniteQuery({
    queryKey: [...notificationKeys.list(filters), limit],
    queryFn: ({ pageParam }) => notifications.page(filters, pageParam, limit),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled,
  });
}

/** Read, or unread again — every list and the count follow. */
export function useMarkNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, read }: { id: string; read: boolean }) =>
      read ? notifications.read(id) : notifications.unreadAgain(id),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useMarkAllNotifications() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (category: NotificationCategory | null) => notifications.readAll(category),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useNotificationPreferences() {
  return useQuery({ queryKey: notificationKeys.preferences, queryFn: notifications.preferences });
}

export function useMuteNotifications() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (muted: NotificationCategory[]) => notifications.mute(muted),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}
