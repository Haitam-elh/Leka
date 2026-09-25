/**
 * Asking for a new confirmation link from the sign-in page.
 *
 * What went wrong: the request failed — the API route was unreachable — and
 * the page said "a new link is on its way" anyway, because it showed that
 * message whatever happened. The error itself was left uncaught, which is
 * the red "1 Issue" Next.js showed in development. Nobody could tell that
 * nothing had been sent.
 *
 * "Whatever happened" was meant for the ANSWER: the server says the same
 * thing whether the address exists or not. A request that failed is not an
 * answer, and saying it succeeded helps nobody.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

import LoginPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const login = vi.fn();
const resendVerification = vi.fn();
vi.mock("@/lib/auth", () => ({
  auth: {
    login: (...args: unknown[]) => login(...args),
    resendVerification: (...args: unknown[]) => resendVerification(...args),
  },
}));

const SENT = "Si cette adresse doit être confirmée, un nouveau lien est en route.";

async function reachTheResendButton() {
  const user = userEvent.setup();
  render(
    <LocaleProvider>
      <LoginPage />
    </LocaleProvider>,
  );
  await user.type(screen.getByLabelText("Adresse e-mail"), "nora@acme.example");
  await user.type(screen.getByLabelText("Mot de passe"), "a long enough passphrase");
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
  await user.click(await screen.findByRole("button", { name: "Renvoyer le lien de confirmation" }));
}

describe("asking for a new confirmation link", () => {
  beforeEach(() => {
    login.mockReset().mockRejectedValue(
      new ApiError(403, "/auth/login", "Unverified", "account_unverified"),
    );
    resendVerification.mockReset();
  });

  it("says a link is on its way when the server accepted the request", async () => {
    resendVerification.mockResolvedValue({ detail: "accepted" });

    await reachTheResendButton();

    expect(await screen.findByText(SENT)).toBeInTheDocument();
    expect(resendVerification).toHaveBeenCalledWith("nora@acme.example");
  });

  it("says what went wrong when it did not, and lets them try again", async () => {
    resendVerification.mockRejectedValue(
      new ApiError(429, "/auth/verify/resend", "Too many", "rate_limited"),
    );

    await reachTheResendButton();

    expect(
      await screen.findByText("Trop de tentatives. Patientez quelques minutes avant de réessayer."),
    ).toBeInTheDocument();
    expect(screen.queryByText(SENT)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Renvoyer le lien de confirmation" })).toBeVisible();
  });
});
