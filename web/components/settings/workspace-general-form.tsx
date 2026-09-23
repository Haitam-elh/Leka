"use client";

import { SelectField } from "@/components/forms/choice-fields";
import { ComboboxField } from "@/components/forms/combobox-field";
import { PeriodField } from "@/components/forms/date-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { FormErrorSummary } from "@/components/forms/form-error-summary";
import { TextField } from "@/components/forms/text-field";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";

/**
 * An ordinary form, which is the point of it.
 *
 * Nothing on this screen is special: a name, an identifier, three
 * preferences. It is here because a component set proves itself on the
 * boring form, not on the interesting one — if the plain case needs
 * anything bespoke, the set is wrong.
 *
 * TODO LEKA-331: PATCH /workspaces/current is the call this replaces. The
 * shape below is already the one the API takes.
 */

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const schema = z.object({
  name: z.string().trim().min(2).max(60),
  // The message is the only one written by hand in this file: "does not
  // match /^[a-z0-9]…/" is true and unusable, and the rule has no generic
  // wording worth putting in the dictionary's validation section.
  slug: z.string().trim().regex(SLUG, { error: "leka.validation:invalidFormat:{}" }),
  timezone: z.string().min(1),
  environment: z.string().min(1),
  period: z.object({
    preset: z.enum(["24h", "7d", "30d", "custom"]),
    range: z.object({ from: z.string(), to: z.string() }),
  }),
});

type Values = z.infer<typeof schema>;

const TIMEZONES = [
  { value: "Europe/Paris", label: "Europe/Paris" },
  { value: "Europe/London", label: "Europe/London" },
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "America/New_York" },
];

const ENVIRONMENTS = [
  { value: "production", label: "Production" },
  { value: "staging", label: "Pré-production" },
  { value: "dev", label: "Développement" },
];

const SAVED: Values = {
  name: "Acme Corp",
  slug: "acme",
  timezone: "Europe/Paris",
  environment: "production",
  period: { preset: "7d", range: { from: "", to: "" } },
};

export function WorkspaceGeneralForm({ failOnce = false }: { failOnce?: boolean }) {
  const t = useDictionary();

  const form = useLekaForm<Values>({
    schema,
    defaultValues: SAVED,
    onSubmit: async (values) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      if (failOnce) {
        // Exactly the shape LEKA-333 returns, so applyServerErrors is
        // exercised here rather than described in a document.
        throw new ApiError(422, "/workspaces/current", "Ce formulaire a été refusé.", "validation_failed", {
          slug: "Cet identifiant est déjà utilisé.",
        });
      }
      notify.success({ title: t.settings.saved, description: t.settings.savedBody });
      form.reset(values);
    },
  });

  const { isDirty, isSubmitting } = form.formState;
  useUnsavedChangesGuard(isDirty);

  return (
    <Form form={form} className="max-w-xl">
      <FormAlert />
      <FormErrorSummary<Values>
        labels={{
          name: t.settings.name,
          slug: t.settings.slug,
          timezone: t.settings.timezone,
          environment: t.settings.defaultEnvironment,
        }}
      />

      <TextField<Values, "name"> name="name" label={t.settings.name} />
      <TextField<Values, "slug">
        name="slug"
        label={t.settings.slug}
        description={t.settings.slugHint}
      />
      <ComboboxField<Values, "timezone">
        name="timezone"
        label={t.settings.timezone}
        options={TIMEZONES}
      />
      <SelectField<Values, "environment">
        name="environment"
        label={t.settings.defaultEnvironment}
        options={ENVIRONMENTS}
      />
      <PeriodField<Values> name="period" label={t.settings.defaultPeriod} />

      <div className="flex gap-2">
        {/* Both refused while nothing has changed: a Save that saves what
            is already saved teaches people that the button means nothing. */}
        <Button type="submit" disabled={!isDirty || isSubmitting} data-testid="settings-save">
          {isSubmitting ? t.forms.saving : t.forms.save}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={!isDirty || isSubmitting}
          onClick={() => form.reset()}
        >
          {t.forms.discard}
        </Button>
      </div>
    </Form>
  );
}
