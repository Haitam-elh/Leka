/**
 * The multi-select, which is the field with the most keyboard in it.
 *
 * What these protect: a chip says what removing it removes, the limit
 * refuses rather than truncates, and Backspace on an empty input takes the
 * last one back — the behaviour every tag field has taught people to
 * expect, and the one that silently disappears when a library is swapped.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MultiSelectField } from "@/components/forms/combobox-field";
import { Form } from "@/components/forms/form";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { z } from "@/lib/validation";

const OPTIONS = [
  { value: "payment-api", label: "Payment API" },
  { value: "auth-service", label: "Auth Service" },
  { value: "billing", label: "Billing" },
];

const schema = z.object({ services: z.array(z.string()) });
type Values = z.infer<typeof schema>;

function mount({ max, defaults = [] }: { max?: number; defaults?: string[] } = {}) {
  const submitted = vi.fn();

  function Harness() {
    const form = useLekaForm({
      schema,
      defaultValues: { services: defaults },
      onSubmit: submitted,
    });
    return (
      <Form form={form}>
        <MultiSelectField<Values, "services">
          name="services"
          label="Services"
          options={OPTIONS}
          max={max}
        />
      </Form>
    );
  }

  render(
    <LocaleProvider>
      <Harness />
    </LocaleProvider>,
  );
  return { submitted };
}

/** The text box inside the chips, which is what typing goes into. */
function input() {
  return screen.getByRole("combobox");
}

describe("MultiSelectField", () => {
  it("adds a choice and shows it as a chip", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(input());
    await user.type(input(), "Payment");
    await user.click(await screen.findByRole("option", { name: "Payment API" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retirer Payment API" })).toBeInTheDocument(),
    );
  });

  it("names each remove button after what it removes", async () => {
    mount({ defaults: ["payment-api", "auth-service"] });

    // Two buttons both called "remove" would be two identical announcements
    // and no way to tell which chip is which.
    expect(screen.getByRole("button", { name: "Retirer Payment API" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer Auth Service" })).toBeInTheDocument();
  });

  it("removes a chip when its own button is pressed", async () => {
    const user = userEvent.setup();
    mount({ defaults: ["payment-api", "auth-service"] });

    await user.click(screen.getByRole("button", { name: "Retirer Payment API" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retirer Payment API" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Retirer Auth Service" })).toBeInTheDocument();
  });

  it("takes the last chip back on Backspace in an empty input", async () => {
    const user = userEvent.setup();
    mount({ defaults: ["payment-api", "auth-service"] });

    await user.click(input());
    await user.keyboard("{Backspace}");
    // The open popup is modal: while it is up, Base UI hides the rest of
    // the page from assistive technology, chips included. Closing it is
    // what a person does too, and it is the only way to read the result.
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retirer Auth Service" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Retirer Payment API" })).toBeInTheDocument();
  });

  it("refuses a choice past the limit instead of truncating the list", async () => {
    const user = userEvent.setup();
    mount({ max: 2, defaults: ["payment-api", "auth-service"] });

    await user.click(input());
    await user.type(input(), "Billing");
    await user.click(await screen.findByRole("option", { name: "Billing" }));

    // The two that were there are untouched, and the third simply did not
    // arrive. Nothing the person chose was undone behind their back.
    expect(screen.queryByRole("button", { name: "Retirer Billing" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer Payment API" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer Auth Service" })).toBeInTheDocument();
  });
});
