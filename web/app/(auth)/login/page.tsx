"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { auth, justSignedOut } from "@/lib/auth";
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
  // Only a same-site path: an open redirect turns our login page into a
  // convincing way to send someone to an attacker's site.
  //
  // The fallback is the overview itself, not "/": "/" is leka-core.com's
  // home page, the site, not the application.
  const target = next && next.startsWith("/") && !next.startsWith("//") ? next : routes.overview();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);
  const [resendError, setResendError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in: the site's "Se connecter" is the way into the
  // application, so it goes on rather than asking for a password again.
  useEffect(() => {
    if (justSignedOut()) return;
    let cancelled = false;
    auth.me({ redirectOn401: false }).then(
      () => {
        if (!cancelled) router.replace(target);
      },
      () => {
        // Not signed in, or the API is unreachable: the form is the answer
        // either way, and it says so itself when it is used.
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router, target]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setUnverified(false);

    try {
      await auth.login(email, password);
      router.push(target);
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
    setResendError(null);
    try {
      await auth.resendVerification(email);
      // The server answers the same whether the address exists or not, and
      // so does this screen. That sameness is about the ANSWER: a request
      // that failed got none, and "a link is on its way" would be untrue —
      // it is how a resend route nobody could reach went unnoticed.
      setResent(true);
    } catch (caught) {
      setResendError(authErrorMessage(t, caught, online));
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
          <>
            <FormMessage message={resendError} />
            <Button type="button" variant="outline" className="w-full" onClick={resend}>
              {t.auth.resendConfirmation}
            </Button>
          </>
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
          <Label htmlFor="password">{t.auth.password}</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {/* Under the field, on the right, as the site's own form has it. */}
          <div className="flex justify-end">
            <Link
              href="/forgot-password"
              className="text-[13.5px] font-semibold tracking-[-0.01em] text-site-violet"
            >
              {t.auth.forgot}
            </Link>
          </div>
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
