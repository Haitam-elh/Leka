import { describe, expect, it } from "vitest";

import { authErrorMessage } from "@/components/auth/form-message";
import { ApiError } from "@/lib/api";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";

const fr = DICTIONARIES.fr;

/**
 * What the sign-in screens say when a request fails. From the code, in the
 * interface's language — never the API's own message, which until LEKA-343
 * put "Cannot reach the API at http://localhost:8000. Is it running?" on
 * the login page.
 */
describe("the sign-in screens' error messages", () => {
  it.each([
    ["invalid_credentials", fr.auth.errors.invalidCredentials],
    ["account_unverified", fr.auth.errors.accountUnverified],
    ["rate_limited", fr.auth.errors.rateLimited],
    ["token_expired", fr.auth.errors.tokenInvalid],
    ["password_breached", fr.auth.errors.passwordBreached],
    ["csrf_failed", fr.auth.errors.sessionExpired],
    ["password_too_short", "Ce mot de passe est trop court : au moins 12 caractères."],
  ] as const)("%s", (code, expected) => {
    const error = new ApiError(400, "/auth/login", "English from the API", code);

    expect(authErrorMessage(fr, error, true)).toBe(expected);
  });

  it("says how long to wait when the API says it, in minutes", () => {
    const error = new ApiError(429, "/auth/register", "Too many attempts. Wait 3170 seconds and try again.", "rate_limited");

    expect(authErrorMessage(fr, error, true)).toBe("Trop de tentatives depuis ce réseau. Réessayez dans 53 min.");
  });

  it("never quotes an API it could not reach", () => {
    const error = new ApiError(0, "/auth/login", "Cannot reach the API at http://localhost:8000");

    expect(authErrorMessage(fr, error, true)).toBe(fr.auth.errors.unreachable);
  });

  it("blames the connection when there is none, whatever the error says", () => {
    const error = new ApiError(0, "/auth/login", "Cannot reach the API");

    expect(authErrorMessage(fr, error, false)).toBe(fr.auth.errors.offline);
  });

  it("owns a server error without repeating it", () => {
    const error = new ApiError(500, "/auth/login", "Traceback …", "internal_error");

    expect(authErrorMessage(fr, error, true)).toBe(fr.auth.errors.server);
  });
});
