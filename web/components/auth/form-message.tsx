"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { ApiError } from "@/lib/api";
import { classifyError } from "@/lib/errors";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";

/** The shortest password the API accepts; the forms check it first. */
export const PASSWORD_MIN = 12;

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

  // The error tone keeps its own raw classes rather than `variant="destructive"`:
  // that variant is the quieter bg-card treatment built for FormAlert's
  // field-level errors, and swapping it in here would mute a standalone
  // auth-failure banner, not just deduplicate one. Success has no such
  // conflict — nothing else uses this tone — so it takes the shared variant.
  return tone === "success" ? (
    <Alert role="alert" variant="success">
      <AlertDescription className="text-current">{message}</AlertDescription>
    </Alert>
  ) : (
    <Alert role="alert" className="border-state-danger/30 bg-state-danger-soft text-state-danger">
      <AlertDescription className="text-current">{message}</AlertDescription>
    </Alert>
  );
}

/**
 * Turn a failed request into a sentence a person can act on.
 *
 * From the error's CODE, never its message: the API's message is English
 * and written for whoever debugs, and an API that could not be reached
 * produced "Cannot reach the API at http://localhost:8000. Is it
 * running?" — shown, until LEKA-343, on the sign-in page.
 *
 * Where the interface can say something more specific than the server
 * should — the server must not confirm that an account exists, the browser
 * already knows which address was typed — it says it here.
 *
 * `online` is `useOnlineStatus()`: a request that failed offline failed
 * because of the connection, whatever it says.
 */
export function authErrorMessage(t: Dictionary, error: unknown, online: boolean): string {
  const errors = t.auth.errors;

  if (online && error instanceof ApiError) {
    switch (error.code) {
      case "invalid_credentials":
        return errors.invalidCredentials;
      case "account_unverified":
        return errors.accountUnverified;
      case "rate_limited": {
        // The API says how long: "Wait 3170 seconds…" — a window of an hour is not « quelques minutes ».
        const seconds = Number(/(\d+) seconds/.exec(error.message)?.[1]);
        return seconds > 0 ? fill(errors.rateLimitedFor, { minutes: Math.ceil(seconds / 60) }) : errors.rateLimited;
      }
      case "token_invalid":
      case "token_expired":
        return errors.tokenInvalid;
      case "password_too_short":
        return fill(errors.passwordTooShort, { min: PASSWORD_MIN });
      case "password_breached":
        return errors.passwordBreached;
      case "csrf_failed":
      case "session_expired":
        return errors.sessionExpired;
      case "validation_failed":
        return errors.invalid;
      default:
        break;
    }
  }

  switch (classifyError(error, online).kind) {
    case "offline":
      return errors.offline;
    case "unreachable":
      return errors.unreachable;
    case "server":
      return errors.server;
    default:
      return errors.unknown;
  }
}
