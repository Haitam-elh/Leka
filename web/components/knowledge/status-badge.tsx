"use client";

import { cn } from "cn";

import { type StatusVariant, statusLabel, statusLook, TONES } from "@/components/knowledge/status";
import { useDictionary } from "@/lib/i18n/locale-provider";

export interface StatusBadgeProps {
  /** `family.value` — see components/knowledge/status.ts for the whole list. */
  variant: StatusVariant;
  /** Replaces the dictionary's word. The icon and the tone stay the variant's. */
  label?: string;
  /** A dot instead of the icon, as in the mockups' legends and graph nodes. */
  dot?: boolean;
  size?: "sm" | "md";
  /**
   * Announce changes: role="status". Only for a badge that changes while
   * someone looks at it — a list of fifty live regions is fifty interruptions.
   */
  live?: boolean;
  className?: string;
}

/**
 * The one badge for every state in the product (LEKA-340).
 *
 * Its word is always there: colour and icon repeat it, never replace it.
 */
export function StatusBadge({
  variant,
  label,
  dot = false,
  size = "md",
  live = false,
  className,
}: StatusBadgeProps) {
  const t = useDictionary();
  const { tone, icon: Icon } = statusLook(variant);
  const spins = variant === "sync.running";

  return (
    <span
      role={live ? "status" : undefined}
      data-slot="status-badge"
      data-variant={variant}
      data-tone={tone}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1.5 rounded-md font-medium whitespace-nowrap",
        size === "sm" ? "px-1.5 py-0.5 text-[0.6875rem]" : "px-2 py-0.5 text-xs",
        TONES[tone].badge,
        className,
      )}
    >
      {dot ? (
        <span
          aria-hidden="true"
          className={cn("size-1.5 shrink-0 rounded-full", TONES[tone].dot)}
        />
      ) : (
        <Icon
          aria-hidden="true"
          className={cn(
            "shrink-0",
            size === "sm" ? "size-3" : "size-3.5",
            spins && "motion-safe:animate-spin",
          )}
        />
      )}
      {label ?? statusLabel(t, variant)}
    </span>
  );
}
