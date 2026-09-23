"use client";

import { GitBranch } from "lucide-react";
import { useState } from "react";

import { CheckboxField, RadioGroupField, SelectField, SwitchField } from "@/components/forms/choice-fields";
import { ComboboxField, MultiSelectField } from "@/components/forms/combobox-field";
import { DateField, DateRangeField, PeriodField, TimeField } from "@/components/forms/date-fields";
import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { FormErrorSummary } from "@/components/forms/form-error-summary";
import { SearchInput } from "@/components/forms/search-input";
import { SelectableListField } from "@/components/forms/selectable-list-field";
import { TextareaField } from "@/components/forms/textarea-field";
import { TextField } from "@/components/forms/text-field";
import { Button } from "@/components/ui/button";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { z } from "@/lib/validation";

const ENVIRONMENTS = [
  { value: "production", label: "Production" },
  { value: "staging", label: "Pré-production" },
  { value: "dev", label: "Développement" },
];

const SERVICES = [
  { value: "payment-api", label: "Payment API" },
  { value: "auth-service", label: "Auth Service" },
  { value: "billing", label: "Billing" },
  { value: "notifications", label: "Notifications" },
  { value: "search", label: "Search" },
];

const SOURCES = [
  { value: "github", title: "GitHub", subtitle: "12 dépôts connectés", icon: <GitBranch className="size-4" /> },
  { value: "jira", title: "Jira", subtitle: "Projet LEKA" },
  { value: "datadog", title: "Datadog", subtitle: "Métriques et traces" },
  { value: "confluence", title: "Confluence", subtitle: "Non connecté", disabled: true },
];

const schema = z.object({
  name: z.string().min(3),
  email: z.email(),
  site: z.url(),
  password: z.string().min(12),
  summary: z.string().min(10).max(200),
  environment: z.string().min(1),
  timezone: z.string().min(1),
  services: z.array(z.string()).max(3),
  sources: z.array(z.string()).min(1),
  consent: z.boolean(),
  notifications: z.boolean(),
  cadence: z.string().min(1),
});

type Values = z.infer<typeof schema>;

const EMPTY: Values = {
  name: "",
  email: "",
  site: "",
  password: "",
  summary: "",
  environment: "",
  timezone: "",
  services: [],
  sources: [],
  consent: false,
  notifications: true,
  cadence: "",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 rounded-xl border border-shell-line bg-white p-5">
      <h2 className="text-sm font-semibold tracking-wide text-shell-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function FormsGallery() {
  const [search, setSearch] = useState("");
  const [reported, setReported] = useState("");

  const form = useLekaForm({
    schema,
    defaultValues: EMPTY,
    onSubmit: () => {
      throw new Error("La galerie ne soumet rien.");
    },
  });

  return (
    <main className="mx-auto max-w-3xl space-y-6 bg-shell-canvas p-8">
      <header>
        <h1 className="text-xl font-semibold text-brand-navy">Champs et interactions</h1>
        <p className="mt-1 text-sm text-shell-muted">
          LEKA-342 · développement uniquement. Soumettez le formulaire vide pour voir tous les
          états d&apos;erreur d&apos;un coup.
        </p>
      </header>

      <Form form={form}>
        <FormAlert />
        <FormErrorSummary<Values>
          labels={{
            name: "Nom",
            email: "E-mail",
            site: "Site",
            password: "Mot de passe",
            summary: "Résumé",
            environment: "Environnement",
            timezone: "Fuseau horaire",
            sources: "Sources",
            cadence: "Fréquence",
          }}
        />

        <Section title="Texte">
          <TextField<Values, "name"> name="name" label="Nom" description="Au moins 3 caractères." />
          <TextField<Values, "email"> name="email" label="E-mail" type="email" />
          <TextField<Values, "site"> name="site" label="Site" type="url" optional />
          <TextField<Values, "password"> name="password" label="Mot de passe" type="password" />
          <TextareaField<Values, "summary">
            name="summary"
            label="Résumé"
            max={200}
            description="Le compteur passe en alerte à 90 % de la limite."
          />
        </Section>

        <Section title="Choix">
          <SelectField<Values, "environment">
            name="environment"
            label="Environnement"
            options={ENVIRONMENTS}
          />
          <ComboboxField<Values, "timezone">
            name="timezone"
            label="Fuseau horaire"
            options={[
              { value: "Europe/Paris", label: "Europe/Paris" },
              { value: "UTC", label: "UTC" },
              { value: "America/New_York", label: "America/New_York" },
            ]}
          />
          <MultiSelectField<Values, "services">
            name="services"
            label="Services"
            optional
            max={3}
            options={SERVICES}
          />
          <RadioGroupField<Values, "cadence">
            name="cadence"
            label="Fréquence"
            options={[
              { value: "daily", label: "Chaque jour", hint: "Un résumé le matin." },
              { value: "weekly", label: "Chaque semaine" },
            ]}
          />
          <CheckboxField<Values, "consent"> name="consent" label="J&apos;accepte les conditions" />
          <SwitchField<Values, "notifications"> name="notifications" label="Notifications" />
        </Section>

        <Section title="Listes riches">
          <SelectableListField<Values, "sources">
            name="sources"
            label="Contexte qui sera analysé"
            items={SOURCES}
            selectAll
          />
        </Section>

        <div className="flex gap-2">
          <Button type="submit">Soumettre</Button>
          <Button type="button" variant="outline" onClick={() => form.reset(EMPTY)}>
            Réinitialiser
          </Button>
        </div>
      </Form>

      <Section title="Dates">
        <Dates />
      </Section>

      <Section title="États asynchrones">
        <AsyncStates />
      </Section>

      <Section title="Désactivé et lecture seule">
        <DisabledStates />
      </Section>

      <Section title="Recherche">
        <SearchInput value={search} onChange={(next) => { setSearch(next); setReported(next); }} />
        <p className="text-xs text-shell-muted">
          Rapporté après la pause : <code>{reported || "—"}</code>
        </p>
      </Section>
    </main>
  );
}

const asyncSchema = z.object({ loading: z.string(), failed: z.string() });
type AsyncValues = z.infer<typeof asyncSchema>;

function AsyncStates() {
  const form = useLekaForm({
    schema: asyncSchema,
    defaultValues: { loading: "", failed: "" },
    onSubmit: () => {},
  });
  return (
    <Form form={form}>
      <ComboboxField<AsyncValues, "loading"> name="loading" label="En chargement" options={[]} loading />
      <ComboboxField<AsyncValues, "failed"> name="failed" label="Chargement échoué" options={[]} failed />
    </Form>
  );
}

const disabledSchema = z.object({ text: z.string(), choice: z.string(), tags: z.array(z.string()) });
type DisabledValues = z.infer<typeof disabledSchema>;

function DisabledStates() {
  const form = useLekaForm({
    schema: disabledSchema,
    defaultValues: { text: "Valeur figée", choice: "production", tags: ["payment-api"] },
    onSubmit: () => {},
  });
  return (
    <Form form={form}>
      <TextField<DisabledValues, "text"> name="text" label="Texte désactivé" disabled />
      <SelectField<DisabledValues, "choice">
        name="choice"
        label="Choix désactivé"
        options={ENVIRONMENTS}
        disabled
      />
      <MultiSelectField<DisabledValues, "tags">
        name="tags"
        label="Chips désactivés"
        options={SERVICES}
        disabled
      />
    </Form>
  );
}

const dateSchema = z.object({
  day: z.string(),
  range: z.object({ from: z.string(), to: z.string() }),
  at: z.string(),
  period: z.object({
    preset: z.enum(["24h", "7d", "30d", "custom"]),
    range: z.object({ from: z.string(), to: z.string() }),
  }),
});
type DateValues = z.infer<typeof dateSchema>;

function Dates() {
  const form = useLekaForm({
    schema: dateSchema,
    defaultValues: {
      day: "",
      range: { from: "", to: "" },
      at: "09:00",
      period: { preset: "7d", range: { from: "", to: "" } },
    },
    onSubmit: () => {},
  });
  return (
    <Form form={form}>
      <DateField<DateValues, "day">
        name="day"
        label="Un jour"
        description="Bornes : 2026-01-01 à 2026-12-31."
        min="2026-01-01"
        max="2026-12-31"
      />
      <DateRangeField<DateValues, "range"> name="range" label="Une plage" optional />
      <TimeField<DateValues, "at"> name="at" label="Heure" />
      <PeriodField<DateValues> name="period" label="Période" />
    </Form>
  );
}
