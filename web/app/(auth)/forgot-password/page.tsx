"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, messageFor } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";

export default function ForgotPasswordPage() {
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
      // Only a rate limit can fail here. Anything else still shows the same
      // confirmation: whether an account exists is not ours to reveal.
      if (caught instanceof ApiError && caught.code === "rate_limited") {
        setError(messageFor(caught.code, caught.message));
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
        title="Check your inbox"
        description="If an account exists for that address, a reset link is on its way."
        footer={
          <Link href="/login" className="underline underline-offset-4">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">
          The link works for one hour, and once only.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      description="We will email you a link."
      footer={
        <Link href="/login" className="underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <FormMessage message={error} />

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

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Sending…" : "Send reset link"}
        </Button>
      </form>
    </AuthCard>
  );
}
