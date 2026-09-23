"use client";

import { Wifi, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "cn";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

/** Long enough to be read, short enough not to become furniture. */
const RECOVERED_MS = 4_000;

/**
 * The connection is gone, said once, at the top of the content.
 *
 * A banner rather than a page: the person may be halfway through reading
 * something, and what is on screen is still worth reading — it just may be
 * out of date, and nothing they do will be saved. Both are in the sentence.
 *
 * When the connection returns, the banner says so for a few seconds and
 * leaves. Pages that failed because of it retry on their own (ErrorState).
 */
export function OfflineBanner() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const [recovered, setRecovered] = useState(false);
  const wasOffline = useRef(false);

  useEffect(() => {
    if (!online) {
      wasOffline.current = true;
      setRecovered(false);
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    setRecovered(true);
    const timer = window.setTimeout(() => setRecovered(false), RECOVERED_MS);
    return () => window.clearTimeout(timer);
  }, [online]);

  const message = !online ? t.states.offlineBanner : recovered ? t.states.backOnline : null;

  return (
    // Always rendered, filled when needed: that is what makes the change
    // announced, politely, without taking the focus from what they were doing.
    <div role="status" data-testid="offline-banner">
      {message ? (
        <p
          data-online={online}
          className={cn(
            "flex items-center gap-2 border-b px-4 py-2 text-sm sm:px-8",
            online
              ? "border-state-success/20 bg-state-success-soft text-state-success"
              : "border-state-warning/20 bg-state-warning-soft text-state-warning",
          )}
        >
          {online ? (
            <Wifi className="size-4 shrink-0" aria-hidden="true" />
          ) : (
            <WifiOff className="size-4 shrink-0" aria-hidden="true" />
          )}
          {message}
        </p>
      ) : null}
    </div>
  );
}
