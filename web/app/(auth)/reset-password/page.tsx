"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, PASSWORD_MIN, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { auth } from "@/lib/auth";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

function ResetPasswordForm() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < PASSWORD_MIN;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await auth.resetPassword(token, password);
      router.push("/login");
    } catch (caught) {
      setError(authErrorMessage(t, caught, online));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard
        title={t.auth.linkIncompleteTitle}
        description={t.auth.linkIncompleteDescription}
        footer={
          <Link href="/forgot-password" className="underline underline-offset-4">
            {t.auth.askNewLink}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.linkIncompleteBody}</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t.auth.resetTitle}
      description={t.auth.resetDescription}
      footer={
        <Link href="/login" className="underline underline-offset-4">
          {t.auth.backToSignIn}
        </Link>
      }
    >
      <FormMessage message={error} />

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="password">{t.auth.newPassword}</Label>
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
          <p
            id="password-help"
            className={`text-xs ${tooShort ? "text-state-danger" : "text-muted-foreground"}`}
          >
            {fill(t.auth.passwordRuleShort, { min: PASSWORD_MIN })}
          </p>
        </div>

        <Button type="submit" className="w-full" disabled={busy || tooShort}>
          {busy ? t.auth.saving : t.auth.setNewPassword}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  const t = useDictionary();
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense fallback={<AuthCard title={t.states.loading}>{null}</AuthCard>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
