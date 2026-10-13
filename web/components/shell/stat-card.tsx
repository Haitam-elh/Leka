import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { cn } from "cn";

/**
 * One figure at the top of a page: its icon, its value, what it counts, a
 * line under it. Every page drew its own (LEKA-438 audit, T1) — seven copies
 * with seven sizes. A figure that leads somewhere is a link: clicking it opens
 * what it counts.
 */
export function StatCard({
  icon,
  tone,
  value,
  label,
  foot,
  href,
  onClick,
  active,
  testId,
  valueTestId,
}: {
  icon: LucideIcon;
  tone: TileTone;
  value: React.ReactNode;
  label: string;
  foot?: React.ReactNode;
  href?: string;
  /** A figure that filters the page below it: pressed while it does. */
  onClick?: () => void;
  active?: boolean;
  testId?: string;
  /** For a test that reads the value alone. */
  valueTestId?: string;
}) {
  const body = (
    <>
      <IconTile icon={icon} tone={tone} />
      <div className="min-w-0">
        <p
          className={cn(
            "leading-tight font-bold text-brand-navy tabular-nums",
            // A figure is big; a sentence ("il y a 30 min", "Free") is not.
            typeof value === "string" && value.length > 6 ? "text-base" : "text-[1.5rem]",
          )}
          data-testid={valueTestId}
        >
          {value}
        </p>
        <p className="text-[0.8125rem] text-shell-muted">{label}</p>
        {foot ? <div className="mt-0.5 text-xs text-shell-muted">{foot}</div> : null}
      </div>
    </>
  );
  const box = "flex items-start gap-3 rounded-xl border border-shell-line bg-white p-4";
  const pressable =
    "text-start outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40";
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        className={cn(box, pressable, active && "border-brand-violet bg-brand-violet-soft/40")}
        data-testid={testId}
      >
        {body}
      </button>
    );
  }
  return href ? (
    <Link
      href={href}
      className={cn(
        box,
        "outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40",
      )}
      data-testid={testId}
    >
      {body}
    </Link>
  ) : (
    <div className={box} data-testid={testId}>
      {body}
    </div>
  );
}

/** The row they sit in: as many columns as figures, up to five. */
export function StatGrid({
  count,
  testId,
  children,
}: {
  count: number;
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3",
        count >= 5 ? "md:grid-cols-3 xl:grid-cols-5" : count === 4 ? "xl:grid-cols-4" : "xl:grid-cols-3",
      )}
      data-testid={testId}
    >
      {children}
    </div>
  );
}
