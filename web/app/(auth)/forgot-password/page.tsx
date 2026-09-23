"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

export default function ForgotPasswordPage() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await auth.forgotPassword(email);
      setSent(true);
    } catch (caught) {
      // Whatever the SERVER answered, the same confirmation: whether an
      // account exists is not ours to reveal. Two exceptions, neither of
      // which reveals anything. A rate limit, which is about the asker.
      // And a request that never reached the server — offline, or the API
      // down — where "a link is on its way" would simply be untrue, and
      // the person would wait for an email that was never going to come.
      const neverArrived = !online || (caught instanceof ApiError && caught.isUnreachable);
      const throttled = caught instanceof ApiError && caught.code === "rate_limited";
      if (neverArrived || throttled) {
        setError(authErrorMessage(t, caught, online));
      } else {
        setSent(true);
      }
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthCard
        title={t.auth.checkInbox}
        description={t.auth.resetSent}
        footer={
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.backToSignIn}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.resetLinkLife}</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t.auth.forgotTitle}
      description={t.auth.forgotDescription}
      footer={
        <Link href="/login" className="underline underline-offset-4">
          {t.auth.backToSignIn}
        </Link>
      }
    >
      <FormMessage message={error} />

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email">{t.auth.email}</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? t.auth.sending : t.auth.sendResetLink}
        </Button>
      </form>
    </AuthCard>
  );
}
