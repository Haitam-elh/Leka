/**
 * The single place the browser talks to the LEKA API.
 *
 * Every response shape comes from lib/api-types.ts, which is GENERATED from
 * the API's OpenAPI schema by `npm run gen:api`. Never edit that file by
 * hand: if a field changes on the backend, the type changes here and
 * `tsc --noEmit` fails in CI before the mismatch reaches a user.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Perform a request against the API.
 *
 * `credentials: "include"` is set once, here, so the session cookie travels
 * with every call. The workspace is never sent by the client — the server
 * reads it from the session (architecture rule 3). Any code that puts a
 * workspace id in a URL or a body is a bug.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${API_PREFIX}${path}`;

  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new ApiError(response.status, path, detail || response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
