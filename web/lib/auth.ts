/**
 * The authentication calls, in one place.
 *
 * Thin wrappers over apiFetch. They exist so that a screen never builds a
 * path by hand, and so that a route rename is one edit rather than five.
 */

import { apiFetch } from "@/lib/api";

export interface WorkspaceMembership {
  id: string;
  name: string;
  slug: string;
  role: string;
}

/** The brackets the site's forms have always offered. */
export const COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"] as const;
export type CompanySize = (typeof COMPANY_SIZES)[number];

/** Who is registering: the first three are required, the rest optional. */
export interface AccountProfile {
  first_name: string;
  last_name: string;
  company: string;
  job_title?: string;
  company_size?: CompanySize;
}

export interface CurrentUser {
  user: {
    id: string;
    email: string;
    email_verified_at: string | null;
    last_login_at: string | null;
    // Null for an account made before registration asked.
    first_name?: string | null;
    last_name?: string | null;
    company?: string | null;
    job_title?: string | null;
    company_size?: CompanySize | null;
  };
  workspaces: WorkspaceMembership[];
  active_workspace_id: string | null;
}

export const auth = {
  register: (email: string, password: string, profile: AccountProfile) =>
    apiFetch<{ detail: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, ...profile }),
    }),

  verify: (token: string) =>
    apiFetch<unknown>(`/auth/verify/${encodeURIComponent(token)}`, { method: "POST" }),

  resendVerification: (email: string) =>
    apiFetch<{ detail: string }>("/auth/verify/resend", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  login: (email: string, password: string) =>
    apiFetch<CurrentUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  // redirectOn401: false — this is the one call for which 401 is the
  // outcome asked for, not a problem. The default sends the browser to
  // /login?next=<where you were>, which on a sign-out means bouncing the
  // person straight back into the application they just left, and which
  // races whatever navigation the caller is doing. The caller decides
  // where a sign-out lands.
  logout: () => apiFetch<void>("/auth/logout", { method: "POST", redirectOn401: false }),

  me: (init: { redirectOn401?: boolean } = {}) =>
    apiFetch<CurrentUser>("/auth/me", init),

  forgotPassword: (email: string) =>
    apiFetch<{ detail: string }>("/auth/password/forgot", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, password: string) =>
    apiFetch<void>("/auth/password/reset", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),
};
