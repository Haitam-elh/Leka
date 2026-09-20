"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { AuthErrorCode } from "@/lib/api";

/**
 * The message shown above a form after a failed — or successful — attempt.
 *
 * Every state the ticket asks for is represented here rather than invented
 * per screen, so that "invalid credentials" reads the same way on the login
 * page and anywhere else it can happen.
 */
export function FormMessage({
  message,
  tone = "error",
}: {
  message: string | null;
  tone?: "error" | "success";
}) {
  if (!message) return null;

  return (
    <Alert
      role="alert"
      className={
        tone === "success"
          ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"
          : "border-destructive/40 bg-destructive/5 text-destructive"
      }
    >
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

/**
 * Turn an error code into a sentence a person can act on.
 *
 * The API already returns a usable message; this adds the cases where the
 * interface can say something more specific than the server should — the
 * server must not confirm that an account exists, the browser already knows
 * which one the user typed.
 */
export function messageFor(code: AuthErrorCode | undefined, fallback: string): string {
  switch (code) {
    case "invalid_credentials":
      return "Invalid email or password.";
    case "account_unverified":
      return "Confirm your email address before signing in. Check your inbox — we can send another link.";
    case "rate_limited":
      return fallback;
    case "token_invalid":
    case "token_expired":
      return "This link is no longer valid. Ask for a new one.";
    case "password_breached":
      return "This password appears in a known data breach. Choose one you have not used elsewhere.";
    case "csrf_failed":
      return "Your session expired while this page was open. Reload and try again.";
    case undefined:
      // Includes the unreachable-API case, whose message already names the
      // address it tried. Passing it through beats replacing it with
      // something vaguer.
      return fallback;
    default:
      return fallback;
  }
}
