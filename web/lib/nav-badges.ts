"use client";

/**
 * The counts the sidebar shows beside an entry.
 *
 * Empty, and that is the honest state. It used to hand the sidebar a mocked
 * "3" beside À valider — the mockup's number, shown to every workspace in
 * production while no approval exists anywhere. A count is shown when a
 * feature reports a real one, and not before (decided 2026-09-25: real data
 * or an honest empty state, never the mockup's figures).
 *
 * TODO LEKA-390: return the real number of approvals waiting. The shape is
 * what matters — the shell is handed numbers by key, and never asks an API
 * itself, so a feature can start reporting one without touching the shell.
 */

import type { BadgeKey } from "@/config/routes";

const NONE: Partial<Record<BadgeKey, number>> = {};

export function useNavBadges(): Partial<Record<BadgeKey, number>> {
  return NONE;
}
