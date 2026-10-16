"use client";

import { Ban, Compass, Lock, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { StatePanel } from "@/components/states/state-panel";
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
 * Drawn by StatePanel since LEKA-343, like ErrorState, so a refusal and a
 * failure look like two answers from the same product.
 */
export type RouteStateVariant = "empty" | "unavailable" | "plan-gated" | "forbidden" | "not-found";

/**
 * A refusal or a wrong address replaces the whole page, so its title is the
 * page's title — without an h1, a screen reader user jumping to the heading
 * lands nowhere. The others sit under a PageHeader that already has one.
 */
const STANDS_ALONE: ReadonlySet<RouteStateVariant> = new Set(["forbidden", "not-found"]);

interface RouteStateProps {
  variant: RouteStateVariant;
  /** Replaces the default wording when a page has something better to say. */
  title?: string;
  body?: string;
  /** The page's own next step, for the empty state. */
  action?: React.ReactNode;
  /** Overrides the default: 1 for the variants that stand alone, 2 otherwise. */
  headingLevel?: 1 | 2 | 3;
}

export function RouteState({ variant, title, body, action, headingLevel }: RouteStateProps) {
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
        <Link href={routes.billingPlans()} className={buttonVariants()}>
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

  return (
    <StatePanel
      testId={`route-state-${variant}`}
      icon={content.icon}
      title={title ?? content.title}
      description={body ?? content.body}
      actions={content.next}
      headingLevel={headingLevel ?? (STANDS_ALONE.has(variant) ? 1 : 2)}
    />
  );
}
