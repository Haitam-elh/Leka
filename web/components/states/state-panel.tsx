import type { LucideIcon } from "lucide-react";

import { cn } from "cn";

/**
 * The one layout every whole-area state shares: an icon, a sentence saying
 * what happened, one saying what to do, and the way to do it.
 *
 * RouteState, ErrorState and the pages' own empty states are all this, so
 * that "nothing here", "not allowed" and "it broke" look like three answers
 * from the same product rather than three components that met late.
 *
 * TONE IS NEVER THE ONLY SIGNAL. The icon and the title carry the meaning;
 * colour repeats it for whoever can see it. One person in twelve cannot tell
 * the success green from the danger red.
 */
export type StateTone = "neutral" | "success" | "warning" | "danger";

const TONES: Record<StateTone, string> = {
  neutral: "bg-brand-violet-soft text-brand-violet",
  success: "bg-state-success-soft text-state-success",
  warning: "bg-state-warning-soft text-state-warning",
  danger: "bg-state-danger-soft text-state-danger",
};

export interface StatePanelProps {
  icon: LucideIcon;
  title: string;
  /** What to do next. A state that only describes is a dead end. */
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** Small print under the actions — a reference to quote, a timestamp. */
  footer?: React.ReactNode;
  tone?: StateTone;
  /**
   * 1 when the state IS the page — not found, forbidden, a crash — so the
   * page still has a title; 2 under a page header that already has one.
   */
  headingLevel?: 1 | 2 | 3;
  /** "page" fills a screen; "section" sits inside a panel or a list. */
  size?: "page" | "section";
  /**
   * "alert" for a failure that has just happened, so it is announced;
   * nothing for a state someone navigated to and will read anyway.
   */
  role?: "alert" | "status";
  className?: string;
  testId?: string;
}

export function StatePanel({
  icon: Icon,
  title,
  description,
  actions,
  footer,
  tone = "neutral",
  headingLevel = 2,
  size = "page",
  role,
  className,
  testId,
}: StatePanelProps) {
  const Heading = `h${headingLevel}` as const;
  const page = size === "page";

  return (
    <div
      role={role}
      data-testid={testId}
      data-tone={tone}
      className={cn(
        "mx-auto flex max-w-md flex-col items-center px-4 text-center",
        page ? "py-16" : "py-8",
        className,
      )}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-full",
          page ? "size-12" : "size-10",
          TONES[tone],
        )}
      >
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <Heading
        className={cn("mt-4 font-semibold text-brand-navy", page ? "text-lg" : "text-base")}
      >
        {title}
      </Heading>
      {description ? <p className="mt-2 text-sm text-shell-muted">{description}</p> : null}
      {actions ? <div className="mt-6 flex flex-wrap justify-center gap-2">{actions}</div> : null}
      {footer ? <p className="mt-4 text-xs text-shell-muted">{footer}</p> : null}
    </div>
  );
}
