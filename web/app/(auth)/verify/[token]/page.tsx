"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";

type State = "checking" | "confirmed" | "invalid";

export default function VerifyPage() {
  const params = useParams<{ token: string }>();
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        await auth.verify(params.token);
        if (!cancelled) setState("confirmed");
      } catch (caught) {
        // One outcome for "never existed", "already used" and "expired".
        // The server does not tell them apart, and neither do we.
        if (!cancelled) setState(caught instanceof ApiError ? "invalid" : "invalid");
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [params.token]);

  if (state === "checking") {
    return (
      <AuthCard title="Confirming your address…">
        <p className="text-sm text-muted-foreground">This takes a moment.</p>
      </AuthCard>
    );
  }

  if (state === "confirmed") {
    return (
      <AuthCard
        title="Address confirmed"
        description="Your account is ready."
        footer={
          <Link href="/login" className="underline underline-offset-4">
            Sign in
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">
          You can close this tab once you have signed in.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="This link is no longer valid"
      description="Confirmation links last 24 hours and work once."
      footer={
        <Link href="/login" className="underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <p className="text-sm text-muted-foreground">
        Sign in with your email and password, and we will offer to send a new
        link.
      </p>
    </AuthCard>
  );
}
