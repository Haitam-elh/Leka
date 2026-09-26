/**
 * Creating an account sends who is registering, as the API expects it.
 *
 * The required three trimmed, and the optional two left out when left
 * empty: the API keeps what it is given, so an empty string sent would be
 * stored as an answer nobody gave.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

import RegisterPage from "./page";

const register = vi.fn();
vi.mock("@/lib/auth", async (original) => ({
  ...(await original<typeof import("@/lib/auth")>()),
  auth: { register: (...args: unknown[]) => register(...args) },
}));

const PASSWORD = "a long enough passphrase";

function mount() {
  return render(
    <LocaleProvider>
      <RegisterPage />
    </LocaleProvider>,
  );
}

async function fillRequired(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Prénom"), "  Nora ");
  await user.type(screen.getByLabelText("Nom"), "Diallo");
  await user.type(screen.getByLabelText("Entreprise"), "Acme");
  await user.type(screen.getByLabelText("E-mail professionnel"), "nora@acme.example");
  await user.type(screen.getByLabelText("Mot de passe"), PASSWORD);
}

describe("the registration form", () => {
  beforeEach(() => {
    register.mockReset().mockResolvedValue({ detail: "accepted" });
  });

  it("sends the required profile, trimmed, and leaves the optional part out", async () => {
    const user = userEvent.setup();
    mount();

    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));

    expect(register).toHaveBeenCalledWith("nora@acme.example", PASSWORD, {
      first_name: "Nora",
      last_name: "Diallo",
      company: "Acme",
    });
    expect(await screen.findByText("Consultez votre boîte de réception")).toBeVisible();
  });

  it("sends the role when one is given", async () => {
    const user = userEvent.setup();
    mount();

    await fillRequired(user);
    await user.type(screen.getByLabelText(/Fonction/), "CTO");
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));

    expect(register.mock.calls[0][2]).toEqual({
      first_name: "Nora",
      last_name: "Diallo",
      company: "Acme",
      job_title: "CTO",
    });
  });

  it("asks for the three required fields before sending anything", () => {
    mount();

    for (const label of ["Prénom", "Nom", "Entreprise"]) {
      expect(screen.getByLabelText(label)).toBeRequired();
    }
    expect(screen.getByLabelText(/Fonction/)).not.toBeRequired();
  });
});
