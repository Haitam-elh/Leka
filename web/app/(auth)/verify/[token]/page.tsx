"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

type State = "checking" | "confirmed" | "invalid" | { failed: unknown };

/**
 * One request per token, whoever asks.
 *
 * A token works once. In development React runs this page's effect twice
 * (StrictMode): two POSTs, the first verifies, the second is told the token
 * is spent — and the page showed that second answer. Sharing the request
 * means both runs read the same answer. "Retry" drops it, so a request that
 * never reached the server is really sent again.
 */
const requests = new Map<string, Promise<unknown>>();

function verifyOnce(token: string): Promise<unknown> {
  let request = requests.get(token);
  if (!request) {
    request = auth.verify(token);
    requests.set(token, request);
  }
  return request;
}

export default function VerifyPage() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const params = useParams<{ token: string }>();
  const [state, setState] = useState<State>("checking");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    requests.delete(params.token);
    setState("checking");
    setAttempt((previous) => previous + 1);
  }, [params.token]);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        await verifyOnce(params.token);
        if (!cancelled) setState("confirmed");
      } catch (caught) {
        if (cancelled) return;
        // One outcome for "never existed", "already used" and "expired":
        // the server does not tell them apart, and neither do we. But only
        // when the SERVER said so. A request that never got there says
        // nothing about the link, and "this link is no longer valid" would
        // send the person to ask for a new one they do not need.
        const answered = caught instanceof ApiError && !caught.isUnreachable && caught.status < 500;
        setState(answered ? "invalid" : { failed: caught });
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [params.token, attempt]);

  if (state === "checking") {
    return (
      <AuthCard title={t.auth.verifyingTitle}>
        <p className="text-sm text-muted-foreground">{t.auth.verifyingBody}</p>
      </AuthCard>
    );
  }

  if (state === "confirmed") {
    return (
      <AuthCard
        title={t.auth.verifiedTitle}
        description={t.auth.verifiedDescription}
        footer={
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.signIn}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.verifiedBody}</p>
      </AuthCard>
    );
  }

  if (state === "invalid") {
    return (
      <AuthCard
        title={t.auth.verifyInvalidTitle}
        description={t.auth.verifyInvalidDescription}
        footer={
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.backToSignIn}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.verifyInvalidBody}</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t.auth.verifyFailedTitle}
      description={authErrorMessage(t, state.failed, online)}
    >
      <Button className="w-full" onClick={retry}>
        {t.states.retry}
      </Button>
    </AuthCard>
  );
}
