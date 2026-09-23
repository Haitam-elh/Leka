"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

function LoginForm() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const router = useRouter();
  // Where to go once signed in. apiFetch puts the page an expired session
  // was on here, so the person lands back where they were rather than on
  // the home page wondering what happened.
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setUnverified(false);

    try {
      await auth.login(email, password);
      // Only a same-site path: an open redirect turns our login page into a
      // convincing way to send someone to an attacker's site.
      //
      // The fallback is the overview itself, not "/". Since LEKA-338 every
      // zone has a named path and "/" is a server redirect onto one, so
      // going through it spent two round trips where one does — at the
      // moment someone is watching a spinner and judging whether the
      // product is slow.
      router.push(
        next && next.startsWith("/") && !next.startsWith("//") ? next : routes.overview(),
      );
    } catch (caught) {
      // The one case where the interface can offer a way forward: the
      // person has proved they own the account, so telling them to confirm
      // their address reveals nothing they do not already know.
      setUnverified(caught instanceof ApiError && caught.code === "account_unverified");
      setError(authErrorMessage(t, caught, online));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setResent(false);
    try {
      await auth.resendVerification(email);
    } finally {
      // Same message whatever happened: the server does not confirm whether
      // the address exists, and neither does this screen.
      setResent(true);
    }
  }

  return (
    <AuthCard
      title={t.auth.signInTitle}
      description={t.auth.signInDescription}
      footer={
        <>
          {t.auth.noAccount}{" "}
          <Link href="/register" className="underline underline-offset-4">
            {t.auth.createOne}
          </Link>
        </>
      }
    >
      <FormMessage message={error} />

      {unverified ? (
        resent ? (
          <FormMessage tone="success" message={t.auth.confirmationResent} />
        ) : (
          <Button type="button" variant="outline" className="w-full" onClick={resend}>
            {t.auth.resendConfirmation}
          </Button>
        )
      ) : null}

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

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">{t.auth.password}</Label>
            <Link
              href="/forgot-password"
              className="text-xs text-muted-foreground underline underline-offset-4"
            >
              {t.auth.forgot}
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? t.auth.signingIn : t.auth.signIn}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function LoginPage() {
  const t = useDictionary();
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense fallback={<AuthCard title={t.auth.signInTitle}>{null}</AuthCard>}>
      <LoginForm />
    </Suspense>
  );
}
