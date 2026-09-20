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

const MINIMUM_LENGTH = 12;

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < MINIMUM_LENGTH;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await auth.register(email, password);
      // Shown whether or not the address was free. The server answers
      // identically in both cases, and so does this screen — otherwise the
      // form becomes a way to ask who already has an account.
      setDone(true);
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

  if (done) {
    return (
      <AuthCard
        title="Check your inbox"
        description="If that address can be registered, a confirmation link is on its way."
        footer={
          <Link href="/login" className="underline underline-offset-4">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">
          The link works for 24 hours, and once only.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create an account"
      description="Start mapping your architecture."
      footer={
        <>
          Already have one?{" "}
          <Link href="/login" className="underline underline-offset-4">
            Sign in
          </Link>
        </>
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

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MINIMUM_LENGTH}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby="password-help"
          />
          <p
            id="password-help"
            className={`text-xs ${tooShort ? "text-destructive" : "text-muted-foreground"}`}
          >
            {/* Length only. No composition rules: demanding an uppercase and
                a digit produces Password1! and nothing stronger. */}
            At least {MINIMUM_LENGTH} characters. A memorable phrase beats a
            short, complicated word.
          </p>
        </div>

        <Button type="submit" className="w-full" disabled={busy || tooShort}>
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}
