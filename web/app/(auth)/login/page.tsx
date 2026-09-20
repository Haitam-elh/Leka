"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, messageFor } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";

function LoginForm() {
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
      router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (caught) {
      if (caught instanceof ApiError) {
        // The one case where the interface can offer a way forward: the
        // person has proved they own the account, so telling them to confirm
        // their address reveals nothing they do not already know.
        setUnverified(caught.code === "account_unverified");
        setError(messageFor(caught.code, caught.message));
      } else {
        setError("Something went wrong. Try again.");
      }
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
      title="Sign in"
      description="Access your workspace."
      footer={
        <>
          No account?{" "}
          <Link href="/register" className="underline underline-offset-4">
            Create one
          </Link>
        </>
      }
    >
      <FormMessage message={error} />

      {unverified ? (
        resent ? (
          <FormMessage
            tone="success"
            message="If that address needs confirming, a new link is on its way."
          />
        ) : (
          <Button type="button" variant="outline" className="w-full" onClick={resend}>
            Send a new confirmation link
          </Button>
        )
      ) : null}

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
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
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="text-xs text-muted-foreground underline underline-offset-4"
            >
              Forgot it?
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
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthCard>
  );
}


export default function LoginPage() {
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense fallback={<AuthCard title="Sign in">{null}</AuthCard>}>
      <LoginForm />
    </Suspense>
  );
}
