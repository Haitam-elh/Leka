"use client";

import {
  Ban,
  Compass,
  RefreshCw,
  ServerCrash,
  TriangleAlert,
  Unplug,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { StatePanel, type StateTone } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { classifyError, type ErrorKind } from "@/lib/errors";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

/**
 * Something failed, said in words a person can act on.
 *
 * Takes the error itself and decides the wording from what KIND of failure
 * it is (lib/errors.ts) — never from its message, which is written for
 * whoever debugs. Offline, our service down, our bug, a refusal, a wrong
 * address: five different next steps, and a sixth for everything else.
 *
 * A retry is offered whenever trying again could help. Offline, it happens
 * on its own as soon as the connection is back — the body says so, and it
 * has to be true.
 */
export function ErrorState({
  error,
  onRetry,
  reference,
  size = "page",
  headingLevel = 2,
  className,
}: {
  error: unknown;
  /** Omitted where trying again cannot help, or cannot be done. */
  onRetry?: () => void;
  /** A reference of the caller's own — Next's digest for a crash. */
  reference?: string;
  size?: "page" | "section";
  headingLevel?: 1 | 2 | 3;
  className?: string;
}) {
  const t = useDictionary();
  const online = useOnlineStatus();
  const classified = classifyError(error, online);
  const quoted = classified.reference ?? reference;

  // Back online after failing offline: retry without being asked.
  const wasOffline = useRef(!online);
  useEffect(() => {
    if (online && wasOffline.current) onRetry?.();
    wasOffline.current = !online;
  }, [online, onRetry]);

  const content: Record<ErrorKind, { icon: LucideIcon; tone: StateTone; title: string; body: string }> = {
    offline: {
      icon: WifiOff,
      tone: "warning",
      title: t.states.offlineTitle,
      body: t.states.offlineBody,
    },
    unreachable: {
      icon: Unplug,
      tone: "warning",
      title: t.states.unreachableTitle,
      body: t.states.unreachableBody,
    },
    server: {
      icon: ServerCrash,
      tone: "danger",
      title: t.states.serverTitle,
      body: t.states.serverBody,
    },
    forbidden: {
      icon: Ban,
      tone: "neutral",
      title: t.states.forbiddenTitle,
      body: t.states.forbiddenBody,
    },
    "not-found": {
      icon: Compass,
      tone: "neutral",
      title: t.shell.notFoundTitle,
      body: t.states.notFoundBody,
    },
    unknown: {
      icon: TriangleAlert,
      tone: "danger",
      title: t.states.errorTitle,
      body: t.states.errorBody,
    },
  };
  const { icon, tone, title, body } = content[classified.kind];

  // Retrying a refusal or a wrong address gets the same answer again.
  const retryable = onRetry && classified.kind !== "forbidden" && classified.kind !== "not-found";

  return (
    <StatePanel
      role="alert"
      testId={`error-state-${classified.kind}`}
      icon={icon}
      tone={tone}
      title={title}
      description={body}
      headingLevel={headingLevel}
      size={size}
      className={className}
      actions={
        <>
          {retryable ? (
            <Button onClick={onRetry}>
              <RefreshCw aria-hidden="true" />
              {t.states.retry}
            </Button>
          ) : null}
          {size === "page" ? (
            <Link
              href={routes.overview()}
              className={buttonVariants({ variant: retryable ? "outline" : "default" })}
            >
              {t.states.backToOverview}
            </Link>
          ) : null}
        </>
      }
      footer={quoted ? fill(t.states.reference, { id: quoted }) : undefined}
    />
  );
}
