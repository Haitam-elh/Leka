"use client";

/**
 * The counts the sidebar shows beside an entry.
 *
 * Mocked, and that is the honest state: how many decisions are waiting is
 * the approvals screen's business, and that screen does not exist yet.
 *
 * TODO LEKA-390: replace the constant with the real count. The shape is
 * what matters — the shell is handed numbers by key, and never asks an API
 * itself, so a feature can start reporting one without touching the shell.
 */

import type { BadgeKey } from "@/config/routes";

const MOCKED: Partial<Record<BadgeKey, number>> = { approvals: 3 };

export function useNavBadges(): Partial<Record<BadgeKey, number>> {
  return MOCKED;
}
