"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, PASSWORD_MIN, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { auth } from "@/lib/auth";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

export default function RegisterPage() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < PASSWORD_MIN;

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
      setError(authErrorMessage(t, caught, online));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <AuthCard
        title={t.auth.checkInbox}
        description={t.auth.registerSent}
        footer={
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.backToSignIn}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.registerLinkLife}</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t.auth.registerTitle}
      description={t.auth.registerDescription}
      footer={
        <>
          {t.auth.alreadyHaveOne}{" "}
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.signIn}
          </Link>
        </>
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

        <div className="space-y-2">
          <Label htmlFor="password">{t.auth.password}</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby="password-help"
          />
          {/* Length only. No composition rules: demanding an uppercase and
              a digit produces Password1! and nothing stronger. */}
          <p
            id="password-help"
            className={`text-xs ${tooShort ? "text-state-danger" : "text-muted-foreground"}`}
          >
            {fill(t.auth.passwordRule, { min: PASSWORD_MIN })}
          </p>
        </div>

        <Button type="submit" className="w-full" disabled={busy || tooShort}>
          {busy ? t.auth.creating : t.auth.createAccount}
        </Button>
      </form>
    </AuthCard>
  );
}
