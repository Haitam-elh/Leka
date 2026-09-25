/**
 * The page the verification email opens.
 *
 * What went wrong: in development React runs every effect twice (StrictMode,
 * on by default in Next's App Router). The page POSTed the token twice; the
 * first request verified the account, the second was told the token was
 * already spent — and that second answer is the one the page showed. The
 * person read "this link is no longer valid" about an account that had just
 * been confirmed.
 *
 * The fake server below does what the real one does: a token works once.
 */

import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

import VerifyPage from "./page";

// A different token per test: the page remembers each token's request.
let token = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ token }),
}));

const spent = new Set<string>();
const verify = vi.fn(async (value: string) => {
  if (spent.has(value)) {
    throw new ApiError(400, `/auth/verify/${value}`, "Invalid token", "token_invalid");
  }
  spent.add(value);
  return {};
});

vi.mock("@/lib/auth", () => ({ auth: { verify: (value: string) => verify(value) } }));

function mount() {
  render(
    <StrictMode>
      <LocaleProvider>
        <VerifyPage />
      </LocaleProvider>
    </StrictMode>,
  );
}

describe("the verification page", () => {
  beforeEach(() => {
    token = crypto.randomUUID();
    spent.clear();
    verify.mockClear();
  });

  it("confirms the address, even when React runs the effect twice", async () => {
    mount();

    expect(await screen.findByText("Adresse confirmée")).toBeInTheDocument();
    expect(screen.queryByText("Ce lien n'est plus valable")).not.toBeInTheDocument();
    expect(verify).toHaveBeenCalledTimes(1);
  });

  it("still says so when the link really was spent", async () => {
    spent.add(token);

    mount();

    expect(await screen.findByText("Ce lien n'est plus valable")).toBeInTheDocument();
  });
});
