/**
 * The foundation every field in LEKA stands on.
 *
 * What these protect is not the look of a form but its behaviour under the
 * two things no screenshot shows: what a screen reader is told, and when
 * validation is allowed to speak. Both were decided once, here, so that
 * twenty forms cannot each decide differently.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SelectField } from "@/components/forms/choice-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { TextField } from "@/components/forms/text-field";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { z } from "@/lib/validation";

const fr = DICTIONARIES.fr;

const schema = z.object({
  name: z.string().min(3),
  email: z.email(),
  city: z.string().min(2),
  note: z.string().min(2),
});

type Values = z.infer<typeof schema>;

const EMPTY: Values = { name: "", email: "", city: "", note: "" };

function Harness({ onSubmit = vi.fn() }: { onSubmit?: (values: Values) => Promise<void> | void }) {
  const form = useLekaForm({ schema, defaultValues: EMPTY, onSubmit });
  return (
    <Form form={form}>
      <FormAlert />
      <TextField name="name" label="Nom" description="Le nom de votre workspace" />
      <TextField name="email" label="E-mail" type="email" />
      <TextField name="city" label="Ville" optional />
      <TextField name="note" label="Note" />
      <button type="submit">Enregistrer</button>
    </Form>
  );
}

function mount(props: { onSubmit?: (values: Values) => Promise<void> | void } = {}) {
  return render(
    <LocaleProvider>
      <Harness {...props} />
    </LocaleProvider>,
  );
}

/** Everything the control points at, as a screen reader would read it. */
function describedText(control: HTMLElement): string {
  const ids = (control.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  return ids
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ")
    .trim();
}

describe("FormField", () => {
  it("wires the label, the description and the error to the control itself", async () => {
    const user = userEvent.setup();
    mount();

    // getByLabelText only finds it if the label really points at the input.
    const name = screen.getByLabelText("Nom");
    expect(name).toHaveAttribute("aria-required", "true");
    expect(name).not.toHaveAttribute("aria-invalid", "true");
    expect(describedText(name)).toContain("Le nom de votre workspace");

    await user.click(name);
    await user.type(name, "ab");
    await user.tab();

    await waitFor(() => expect(name).toHaveAttribute("aria-invalid", "true"));
    // The description does not disappear when an error arrives: the rule
    // and what broke it are both worth reading.
    expect(describedText(name)).toContain("Le nom de votre workspace");
    expect(describedText(name)).toContain("Au moins 3 caractères.");
  });

  it("marks the optional field, and only that one", () => {
    mount();

    expect(screen.getByLabelText(/^Ville/)).not.toHaveAttribute("aria-required");
    expect(screen.getByLabelText("Nom")).toHaveAttribute("aria-required", "true");
    expect(screen.getByText(fr.forms.optional)).toBeInTheDocument();
  });

  it("puts the message in the language in use, not the one zod speaks", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByLabelText("E-mail"), "pas-une-adresse");
    await user.tab();

    await waitFor(() => expect(screen.getByText(fr.validation.email)).toBeInTheDocument());
  });
});

describe("when validation speaks", () => {
  it("says nothing while a field is being filled for the first time", async () => {
    const user = userEvent.setup();
    mount();

    const name = screen.getByLabelText("Nom");
    await user.type(name, "a");

    // "a" is already too short. Saying so now is a complaint about a value
    // that is still being typed.
    expect(screen.queryByText("Au moins 3 caractères.")).not.toBeInTheDocument();
    expect(name).not.toHaveAttribute("aria-invalid", "true");
  });

  it("speaks when the field is left, then corrects live", async () => {
    const user = userEvent.setup();
    mount();

    const name = screen.getByLabelText("Nom");
    await user.type(name, "a");
    await user.tab();

    await waitFor(() => expect(screen.getByText("Au moins 3 caractères.")).toBeInTheDocument());

    // From here on it must follow each keystroke: the only thing that
    // matters once an error is on screen is watching it go.
    await user.type(name, "bc");
    await waitFor(() =>
      expect(screen.queryByText("Au moins 3 caractères.")).not.toBeInTheDocument(),
    );
  });
});

describe("submitting", () => {
  it("puts focus on the first invalid field", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByLabelText("E-mail"), "valide@exemple.fr");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    // Name comes before city and note, and all three are empty.
    await waitFor(() => expect(screen.getByLabelText("Nom")).toHaveFocus());
  });

  it("refuses a second submission while the first is in flight", async () => {
    const user = userEvent.setup();
    let release = () => {};
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    mount({ onSubmit });

    await user.type(screen.getByLabelText("Nom"), "Acme");
    await user.type(screen.getByLabelText("E-mail"), "nora@acme.example");
    await user.type(screen.getByLabelText(/^Ville/), "Marseille");
    await user.type(screen.getByLabelText("Note"), "ok");

    const save = screen.getByRole("button", { name: "Enregistrer" });
    await user.click(save);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    await user.click(save);
    await user.click(save);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    release();
  });

  it("leaves the form filled in and editable after a refusal", async () => {
    const user = userEvent.setup();
    mount({
      onSubmit: () => {
        throw new ApiError(500, "/workspaces/current", "Le serveur a refusé.");
      },
    });

    await user.type(screen.getByLabelText("Nom"), "Acme");
    await user.type(screen.getByLabelText("E-mail"), "nora@acme.example");
    await user.type(screen.getByLabelText(/^Ville/), "Marseille");
    await user.type(screen.getByLabelText("Note"), "ok");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Le serveur a refusé."));
    expect(screen.getByLabelText("Nom")).toHaveValue("Acme");

    await user.type(screen.getByLabelText("Nom"), " SAS");
    expect(screen.getByLabelText("Nom")).toHaveValue("Acme SAS");
  });
});

describe("applyServerErrors", () => {
  async function submitWith(error: ApiError) {
    const user = userEvent.setup();
    mount({
      onSubmit: () => {
        throw error;
      },
    });

    await user.type(screen.getByLabelText("Nom"), "Acme");
    await user.type(screen.getByLabelText("E-mail"), "nora@acme.example");
    await user.type(screen.getByLabelText(/^Ville/), "Marseille");
    await user.type(screen.getByLabelText("Note"), "ok");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    return user;
  }

  it("puts a field error on its field, and focuses it", async () => {
    await submitWith(
      new ApiError(422, "/x", "Requête invalide.", "validation_failed", {
        name: "Ce nom est déjà pris.",
      }),
    );

    await waitFor(() => expect(screen.getByText("Ce nom est déjà pris.")).toBeInTheDocument());
    expect(screen.getByLabelText("Nom")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Nom")).toHaveFocus();
  });

  it("sends an error about a field this form does not have to the top", async () => {
    await submitWith(
      new ApiError(422, "/x", "Requête invalide.", "validation_failed", {
        billing_plan: "Votre offre ne permet pas ce réglage.",
      }),
    );

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Votre offre ne permet pas ce réglage."),
    );
  });

  it("does not quote the API at someone when it could not be reached", async () => {
    await submitWith(new ApiError(0, "/x", "Cannot reach the API at http://localhost:8000."));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(fr.forms.submitFailed),
    );
    expect(screen.queryByText(/localhost/)).not.toBeInTheDocument();
  });
});

describe("a select", () => {
  it("shows the option that was chosen, not the value it is stored as", () => {
    // It printed "7d" and "production" on the settings screen: what the
    // form stores, rather than what the person picked from.
    const schema = z.object({ environment: z.string() });
    function Select() {
      const form = useLekaForm({
        schema,
        defaultValues: { environment: "production" },
        onSubmit: vi.fn(),
      });
      return (
        <Form form={form}>
          <SelectField
            name="environment"
            label="Environnement"
            options={[
              { value: "production", label: "Production" },
              { value: "staging", label: "Pré-production" },
            ]}
          />
        </Form>
      );
    }
    render(
      <LocaleProvider>
        <Select />
      </LocaleProvider>,
    );

    const trigger = screen.getByRole("combobox", { name: "Environnement" });
    expect(trigger).toHaveTextContent("Production");
    expect(trigger).not.toHaveTextContent("production");
  });
});

describe("a label hidden from the eye", () => {
  it("still names the field for a screen reader", () => {
    function Hidden() {
      const form = useLekaForm({ schema, defaultValues: EMPTY, onSubmit: vi.fn() });
      return (
        <Form form={form}>
          <TextField name="name" label="Nom" hideLabel />
        </Form>
      );
    }
    render(
      <LocaleProvider>
        <Hidden />
      </LocaleProvider>,
    );

    expect(screen.getByRole("textbox", { name: "Nom" })).toBeInTheDocument();
    expect(screen.getByText("Nom")).toHaveClass("sr-only");
  });
});
