import { ApiError } from "@/lib/api";

/**
 * What kind of failure this is, in the terms a person can act on.
 *
 * The interface never shows an error's own message. That text is written
 * for whoever debugs — "Cannot reach the API at http://localhost:8000",
 * "TypeError: Cannot read properties of undefined" — and to anyone else it
 * says only that something is broken and it is their problem now. What a
 * person needs is which of a handful of situations they are in, because
 * each has a different next step:
 *
 *   offline       their connection — check it, and we retry when it is back
 *   unreachable   our service — nothing to fix on their side, try again soon
 *   server        our bug — not their fault; the reference helps us find it
 *   forbidden     their role — someone can grant it
 *   not-found     the address — go somewhere that exists
 *   unknown       anything else, a crash in the page included
 */
export type ErrorKind = "offline" | "unreachable" | "server" | "forbidden" | "not-found" | "unknown";

export interface ClassifiedError {
  kind: ErrorKind;
  /** The API's request id, to quote to whoever investigates. */
  reference?: string;
}

/**
 * `online` is passed in rather than read, so this stays a function of its
 * arguments. Callers give it `navigator.onLine`, or `useOnlineStatus()`.
 */
export function classifyError(error: unknown, online: boolean): ClassifiedError {
  // First, whatever the error says: a request that failed while the
  // browser was offline failed because it was offline, and "our service is
  // down" would send the person to wait for us instead of checking theirs.
  if (!online) return { kind: "offline" };

  if (error instanceof ApiError) {
    const reference = error.requestId;
    if (error.isUnreachable) return { kind: "unreachable" };
    if (error.status === 403) return { kind: "forbidden", reference };
    if (error.status === 404) return { kind: "not-found", reference };
    if (error.status >= 500) return { kind: "server", reference };
    return { kind: "unknown", reference };
  }

  return { kind: "unknown" };
}
