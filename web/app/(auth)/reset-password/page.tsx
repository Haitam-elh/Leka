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

const MINIMUM_LENGTH = 12;

function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < MINIMUM_LENGTH;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await auth.resetPassword(token, password);
      router.push("/login");
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(messageFor(caught.code, caught.fieldErrors?.password ?? caught.message));
      } else {
        setError("Something went wrong. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard
        title="Link incomplete"
        description="This page needs the link from your email."
        footer={
          <Link href="/forgot-password" className="underline underline-offset-4">
            Ask for a new link
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">
          Open the link exactly as it appears in the message — some email
          clients cut long links in half.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Choose a new password"
      description="Every other signed-in device will be signed out."
      footer={
        <Link href="/login" className="underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <FormMessage message={error} />

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="password">New password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MINIMUM_LENGTH}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <p
            className={`text-xs ${tooShort ? "text-destructive" : "text-muted-foreground"}`}
          >
            At least {MINIMUM_LENGTH} characters.
          </p>
        </div>

        <Button type="submit" className="w-full" disabled={busy || tooShort}>
          {busy ? "Saving…" : "Set new password"}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense fallback={<AuthCard title="Loading…">{null}</AuthCard>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
