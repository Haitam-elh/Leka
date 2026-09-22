"use client";

import { Ban, Compass, Lock, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * What a page shows when it has nothing, cannot show it, or does not exist.
 *
 * Four states, one component, and the rule that makes them useful: each one
 * says what happened AND what to do next. A dead end that only apologises
 * sends the person back to the sidebar to guess.
 *
 * Sober on purpose: the visual design of these belongs to LEKA-343. What
 * this ticket owes is that they exist, are reachable, and are worded.
 */
export type RouteStateVariant = "empty" | "unavailable" | "plan-gated" | "forbidden" | "not-found";

interface RouteStateProps {
  variant: RouteStateVariant;
  /** Replaces the default wording when a page has something better to say. */
  title?: string;
  body?: string;
  /** The page's own next step, for the empty state. */
  action?: React.ReactNode;
}

export function RouteState({ variant, title, body, action }: RouteStateProps) {
  const t = useDictionary();
  const router = useRouter();

  const content = {
    empty: {
      icon: Sparkles,
      title: t.states.emptyTitle,
      body: t.states.emptyBody,
      next: action,
    },
    unavailable: {
      icon: Compass,
      title: t.states.unavailableTitle,
      body: t.states.unavailableBody,
      next: (
        <Button variant="outline" onClick={() => router.back()}>
          {t.states.goBack}
        </Button>
      ),
    },
    "plan-gated": {
      icon: Lock,
      title: t.states.unavailableTitle,
      body: t.states.planGatedBody,
      // A link, not a button: it goes somewhere, and middle-clicking it
      // should open a tab like any other link in the product.
      next: (
        <Link href={routes.billing()} className={buttonVariants()}>
          {t.states.seeBilling}
        </Link>
      ),
    },
    forbidden: {
      icon: Ban,
      title: t.states.forbiddenTitle,
      body: t.states.forbiddenBody,
      next: (
        <>
          {/* TODO LEKA-402: asking for access needs somewhere to send the
              request. Inert until then, rather than a button that lies. */}
          <Button variant="outline" disabled>
            {t.states.requestAccess}
          </Button>
          <Link href={routes.overview()} className={buttonVariants()}>
            {t.states.backToOverview}
          </Link>
        </>
      ),
    },
    "not-found": {
      icon: Compass,
      title: t.shell.notFoundTitle,
      body: t.states.notFoundBody,
      next: (
        <Link href={routes.overview()} className={buttonVariants()}>
          {t.states.backToOverview}
        </Link>
      ),
    },
  }[variant];

  const Icon = content.icon;

  return (
    <div
      data-testid={`route-state-${variant}`}
      className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center"
    >
      <span className="flex size-12 items-center justify-center rounded-full bg-brand-violet-soft text-brand-violet">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <h2 className="mt-4 text-lg font-semibold text-brand-navy">{title ?? content.title}</h2>
      <p className="mt-2 text-sm text-shell-muted">{body ?? content.body}</p>
      {content.next && <div className="mt-6 flex flex-wrap justify-center gap-2">{content.next}</div>}
    </div>
  );
}
