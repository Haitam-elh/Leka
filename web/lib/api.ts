/**
 * The single place the browser talks to the LEKA API.
 *
 * Every response shape comes from lib/api-types.ts, which is GENERATED from
 * the API's OpenAPI schema by `npm run gen:api`. Never edit that file by
 * hand: if a field changes on the backend, the type changes here and
 * `tsc --noEmit` fails in CI before the mismatch reaches a user.
 */

import type { components } from "./api-types";

/** The body of any error the API returns. One shape, whatever failed. */
type ErrorBody = components["schemas"]["ErrorBody"];

// localhost, not 127.0.0.1: the dev server is on localhost:3000, and a
// browser treats the two as different SITES — a SameSite=Lax session cookie
// set by one is never sent to the other. See docs/adr/009-cookie-strategy.md.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

const CSRF_COOKIE = "leka_csrf";
const REQUEST_ID_HEADER = "X-Request-ID";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Machine-readable codes the API returns alongside a human sentence.
 *
 * Taken from the generated schema rather than written out again: the API
 * owns this list, and a code added or renamed there now fails `tsc` here
 * instead of quietly falling through a switch at runtime.
 */
export type ApiErrorCode = components["schemas"]["ErrorCode"];

/** The name this was known by before LEKA-333 widened it past auth. */
export type AuthErrorCode = ApiErrorCode;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
    readonly code?: ApiErrorCode,
    readonly fieldErrors?: Record<string, string>,
    /** Quote this to us and we can find the exact request in the logs. */
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when the caller is simply not signed in, rather than forbidden. */
  get isUnauthenticated(): boolean {
    return this.status === 401 || this.code === "not_authenticated";
  }

  /** True when the API could not be reached at all.
   *
   * Status 0 is not an HTTP status — fetch rejects without one when the
   * server is down, the port is wrong or CORS refused the request. Screens
   * need to tell this apart from "you are not signed in", because the
   * answer is "start the API", not "sign in again". */
  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

/**
 * Read the CSRF token the API set at sign-in.
 *
 * Deliberately readable by JavaScript: the double-submit pattern needs the
 * page to copy it into a header. Its value is not that it is secret, but
 * that another origin cannot read it. The session cookie, by contrast, is
 * httpOnly and invisible here — which is why an XSS cannot steal it.
 */
function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Read an error body.
 *
 * One shape now, whatever failed: a missing field, a business rule, a bug,
 * a refused CSRF token, a path that matches no route. Before LEKA-333 this
 * file carried three parsers — one for Pydantic's 422, one for `detail` as
 * a string, one for it as an object — and they existed because the API had
 * three shapes. It has one.
 */
function readError(body: unknown): {
  message?: string;
  code?: ApiErrorCode;
  fieldErrors?: Record<string, string>;
  requestId?: string;
} {
  const error = (body as { error?: unknown } | null)?.error;
  if (typeof error !== "object" || error === null) return {};

  const shaped = error as ErrorBody;
  const fieldErrors: Record<string, string> = {};
  for (const item of shaped.details ?? []) {
    fieldErrors[item.field] = item.message;
  }

  return {
    message: shaped.message,
    code: shaped.code,
    fieldErrors: Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined,
    requestId: shaped.request_id ?? undefined,
  };
}

/**
 * Perform a request against the API.
 *
 * `credentials: "include"` is set once, here, so the session cookie travels
 * with every call. The workspace is never sent by the client — the server
 * reads it from the session (architecture rule 3). Any code that puts a
 * workspace id in a URL or a body is a bug.
 *
 * Mutations carry the CSRF token automatically. Forgetting it on one route
 * is the kind of mistake that only shows up as a mysterious 403, so it is
 * not left to the caller.
 */
/** Where an expired session sends the browser. */
const SIGN_IN_PATH = "/login";

/** Pages that must not bounce to sign-in when a call returns 401.
 *
 * The login page itself asks /auth/me to see whether it can skip the form.
 * Redirecting on that answer would loop forever. */
const AUTH_PATHS = ["/login", "/register", "/forgot-password", "/reset-password", "/verify"];

function onAnAuthPage(): boolean {
  if (typeof window === "undefined") return true;
  return AUTH_PATHS.some((path) => window.location.pathname.startsWith(path));
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { redirectOn401?: boolean } = {},
): Promise<T> {
  const url = `${API_URL}${API_PREFIX}${path}`;
  const method = (init.method ?? "GET").toUpperCase();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCsrfToken();
    if (csrf) headers[CSRF_HEADER] = csrf;
  }

  const { redirectOn401 = true, ...request } = init;

  let response: Response;
  try {
    response = await fetch(url, { ...request, credentials: "include", headers });
  } catch {
    // fetch rejects, rather than resolving with a status, when the server is
    // unreachable or CORS refused the request. Turning that into an ApiError
    // means every screen handles one error type instead of two — and an
    // unreachable API stops rendering as a blank page.
    throw new ApiError(
      0,
      path,
      `Cannot reach the API at ${API_URL}. Is it running?`,
    );
  }

  if (response.status === 401 && redirectOn401 && !onAnAuthPage()) {
    // The session expired, was revoked, or the person was signed out from
    // another device. Send them to sign in, keeping where they were so they
    // can be returned to it.
    const returnTo = encodeURIComponent(
      window.location.pathname + window.location.search,
    );
    window.location.assign(`${SIGN_IN_PATH}?next=${returnTo}`);
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const { message, code, fieldErrors, requestId } = readError(body);

    throw new ApiError(
      response.status,
      path,
      message ?? response.statusText,
      code,
      fieldErrors,
      // Falls back to the header, which the API sets on EVERY response —
      // including the ones whose body never parsed.
      requestId ?? response.headers.get(REQUEST_ID_HEADER) ?? undefined,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
