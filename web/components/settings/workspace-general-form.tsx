"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { SelectField } from "@/components/forms/choice-fields";
import { ComboboxField } from "@/components/forms/combobox-field";
import { PeriodField } from "@/components/forms/date-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { FormErrorSummary } from "@/components/forms/form-error-summary";
import { TextField } from "@/components/forms/text-field";
import { usePermissions, useRenameWorkspace } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";
import { type CurrentWorkspace, type WorkspacePreferences, type WorkspaceRead, workspace } from "@/lib/workspace";

/**
 * Votre espace (LEKA-502): its name and three preferences, read from the
 * workspace and saved to it — `PATCH /workspaces/current`, which checks
 * each value again. The identifier is shown, never changed: links already
 * point at it. Only an admin changes them; the others read them.
 */

const schema = z.object({
  name: z.string().trim().min(2).max(60),
  timezone: z.string().min(1),
  environment: z.enum(["production", "staging", "dev"]),
  period: z.object({
    preset: z.enum(["24h", "7d", "30d", "custom"]),
    range: z.object({ from: z.string(), to: z.string() }),
  }),
});

type Values = z.infer<typeof schema>;

// Every zone the browser knows, so a saved one is always among them.
const TIMEZONES = Intl.supportedValuesOf("timeZone").map((zone) => ({ value: zone, label: zone }));

const ENVIRONMENTS = ["production", "staging", "dev"] as const;

const CURRENT = ["workspace", "current"] as const;

function valuesOf(saved: WorkspaceRead): Values {
  const said = saved.settings as WorkspacePreferences;
  return {
    name: saved.name,
    timezone: said.timezone ?? "Europe/Paris",
    environment: said.default_environment ?? "production",
    period: {
      preset: said.default_period?.preset ?? "7d",
      range: { from: said.default_period?.from ?? "", to: said.default_period?.to ?? "" },
    },
  };
}

export function WorkspaceGeneralForm() {
  const current = useQuery({ queryKey: CURRENT, queryFn: workspace.current });
  if (!current.data) return null;
  return <Loaded saved={current.data.workspace} />;
}

function Loaded({ saved }: { saved: WorkspaceRead }) {
  const t = useDictionary();
  const queries = useQueryClient();
  const rename = useRenameWorkspace();
  const admin = usePermissions()?.includes("workspace:update") ?? false;

  const form = useLekaForm<Values>({
    schema,
    defaultValues: valuesOf(saved),
    onSubmit: async (values) => {
      const custom = values.period.preset === "custom";
      const kept = await workspace.configure({
        name: values.name,
        settings: {
          timezone: values.timezone,
          default_environment: values.environment,
          default_period: {
            preset: values.period.preset,
            from: custom ? values.period.range.from || null : null,
            to: custom ? values.period.range.to || null : null,
          },
        },
      });
      // What the server kept, not what was typed.
      queries.setQueryData<CurrentWorkspace>(CURRENT, (was) => was && { ...was, workspace: kept });
      rename(kept.name);
      form.reset(valuesOf(kept));
      notify.success({ title: t.settings.saved, description: t.settings.savedBody });
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
          timezone: t.settings.timezone,
          environment: t.settings.defaultEnvironment,
        }}
      />

      <fieldset disabled={!admin} className="space-y-6">
        <TextField<Values, "name"> name="name" label={t.settings.name} />
        <div>
          <p className="text-sm font-medium">{t.settings.slug}</p>
          <p className="font-mono text-sm" data-testid="settings-slug">
            {saved.slug}
          </p>
          <p className="text-xs text-muted-foreground">{t.settings.slugHint}</p>
        </div>
        <ComboboxField<Values, "timezone">
          name="timezone"
          label={t.settings.timezone}
          options={TIMEZONES}
        />
        <SelectField<Values, "environment">
          name="environment"
          label={t.settings.defaultEnvironment}
          options={ENVIRONMENTS.map((value) => ({ value, label: t.settings.environments[value] }))}
        />
        <PeriodField<Values> name="period" label={t.settings.defaultPeriod} />
      </fieldset>

      {admin ? (
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
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="settings-admin-only">
          {t.settings.adminOnly}
        </p>
      )}
    </Form>
  );
}
