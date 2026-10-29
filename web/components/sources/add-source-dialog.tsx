"use client";

import { useQuery } from "@tanstack/react-query";
import { Ban, CircleCheck, Lock, Search, TriangleAlert, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { FormProvider, useFormContext, useWatch } from "react-hook-form";

import { cn } from "cn";
import { FormAlert } from "@/components/forms/form-alert";
import { MetadataPanel } from "@/components/knowledge/metadata-panel";
import { CheckboxField, SelectField } from "@/components/forms/choice-fields";
import { TextField } from "@/components/forms/text-field";
import { TextareaField } from "@/components/forms/textarea-field";
import { capabilityWord, fieldWords } from "@/components/sources/source-panel";
import { SourceLogo } from "@/components/sources/source-logo";
import { LoadingState } from "@/components/states/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { CUSTOM_KINDS, isCustom, shownFor, shownOnly, TEMPLATES } from "@/lib/custom-connectors";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import {
  type CatalogEntry,
  type Diagnostic,
  receivingAddress,
  type Source,
  type SourceKind,
  sources,
  type TestOutcome,
} from "@/lib/sources";
import {
  defaultsOf,
  type FieldSpec,
  fieldsOf,
  filled,
  initialOf,
  scopeFieldOf,
  zodOf,
} from "@/lib/sources-form";
import { useCatalog, useSourceMutation } from "@/lib/sources-queries";
import { z } from "@/lib/validation";

/**
 * Connecting a tool, in the order the API needs it (docs/connectors/framework.md):
 *
 *   1. the tool        — from the catalogue: only what has a connector
 *   2. the connection  — a form read from the connector's JSON Schemas;
 *                        saving creates the source, in draft
 *   3. the scope       — what the vendor lists, asked now; everything, or a
 *                        selection (skipped for a connector without one)
 *   4. test, activate  — the test's answer in the admin's words; activation
 *                        only after it succeeded
 *
 * Nothing is lost by stopping: the source exists from step 2, in draft, and
 * its own page takes it from there. Going back from 3 or 4 edits it.
 *
 * A tool chosen beforehand — on the welcome page, where a new workspace
 * picks its tools — skips step 1: the wizard opens at its connection.
 *
 * A CUSTOM CONNECTOR (LEKA-426) — a tool LEKA has no connector for — is the
 * same wizard, from its own entry: its first step is the method (REST,
 * GraphQL, webhook), with what each needs and what none can do; the
 * connection shows only the fields the choices make useful and starts the
 * definition from an example; the test shows what the mapping read. The
 * native catalogue lists natives only, and leads here when the tool is
 * not in it.
 */

type Step = "connector" | "settings" | "scope" | "test";
const STEPS: Step[] = ["connector", "settings", "scope", "test"];
type Kind = "native" | "custom";

export function AddSourceDialog({
  open,
  onOpenChange,
  onDone,
  editing,
  start = "native",
  reconnecting = false,
  tool,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: (source: Source) => void;
  /** A source to change: the wizard starts at its connection. */
  editing?: Source;
  /** The catalogue of natives, or the custom connector's methods. */
  start?: Kind;
  /** Changing a source to connect it again — a new secret, most often. */
  reconnecting?: boolean;
  /** A tool already chosen: the wizard starts at its connection. */
  tool?: SourceKind;
}) {
  const t = useDictionary();
  const catalog = useCatalog();
  const first: Step = editing || tool ? "settings" : "connector";
  const [step, setStep] = useState<Step>(first);
  const [kind, setKind] = useState<Kind>(start);
  const [picked, setEntry] = useState<CatalogEntry | null>(null);
  const [source, setSource] = useState<Source | null>(editing ?? null);
  const known = editing?.type ?? tool;
  const entry = picked ?? (known ? (catalog.data?.find((e) => e.key === known) ?? null) : null);
  const custom = kind === "custom" || (entry !== null && isCustom(entry.key));

  // Opened again from another entry — "Ajouter", "Connecteur sur mesure".
  useEffect(() => {
    if (open) setKind(start);
  }, [open, start]);

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setStep(first);
      setKind(start);
      setEntry(null);
      setSource(editing ?? null);
    }
  }

  function finish(done: Source) {
    close(false);
    onDone(done);
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent showCloseButton={false} className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <div className="flex items-start gap-3">
          <div className="flex-1">
            <DialogTitle>
              {editing
                ? reconnecting
                  ? t.sources.page.reconnectTitle
                  : t.sources.page.editTitle
                : custom
                  ? t.sources.custom.open
                  : t.sources.add.title}
            </DialogTitle>
            <DialogDescription className="mt-1 flex items-center gap-1.5">
              <Lock className="size-3.5" aria-hidden="true" />
              {t.sources.add.readOnly}
            </DialogDescription>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => close(false)}
            aria-label={t.sources.add.close}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
        <Stepper step={step} custom={custom} />

        {step === "connector" && kind === "native" ? (
          <ConnectorStep
            onPick={(picked) => {
              setEntry(picked);
              setStep("settings");
            }}
            onCustom={() => setKind("custom")}
          />
        ) : null}
        {step === "connector" && kind === "custom" ? (
          <MethodStep
            onPick={(picked) => {
              setEntry(picked);
              setStep("settings");
            }}
            onBack={start === "native" ? () => setKind("native") : undefined}
          />
        ) : null}
        {step === "settings" && !entry ? <LoadingState size="section" /> : null}
        {step === "settings" && entry ? (
          <SettingsStep
            entry={entry}
            source={source}
            reconnecting={reconnecting}
            onBack={source || tool ? undefined : () => setStep("connector")}
            onSaved={(saved) => {
              setSource(saved);
              setStep(scopeFieldOf(entry.config_schema) ? "scope" : "test");
            }}
          />
        ) : null}
        {step === "scope" && entry && source ? (
          <ScopeStep
            entry={entry}
            source={source}
            onEdit={() => setStep("settings")}
            onSaved={(saved) => {
              setSource(saved);
              setStep("test");
            }}
          />
        ) : null}
        {step === "test" && source ? (
          <TestStep source={source} onEdit={() => setStep("settings")} onDone={finish} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function Stepper({ step, custom }: { step: Step; custom: boolean }) {
  const t = useDictionary();
  const current = STEPS.indexOf(step);
  return (
    <ol
      aria-label={fill(t.sources.add.stepOf, { current: current + 1, total: STEPS.length })}
      className="flex flex-wrap gap-2 text-xs"
    >
      {STEPS.map((name, index) => (
        <li
          key={name}
          aria-current={index === current ? "step" : undefined}
          className={cn(
            "rounded-full px-2.5 py-1",
            index === current
              ? "bg-brand-violet-soft font-medium text-shell-nav-active"
              : index < current
                ? "text-brand-navy"
                : "text-shell-muted",
          )}
        >
          {index + 1}.{" "}
          {name === "connector" && custom ? t.sources.custom.step : t.sources.add.steps[name]}
        </li>
      ))}
    </ol>
  );
}

// ── 1. The tool ─────────────────────────────────────────────────────────────

function ConnectorStep({
  onPick,
  onCustom,
}: {
  onPick: (entry: CatalogEntry) => void;
  onCustom: () => void;
}) {
  const t = useDictionary();
  const catalog = useCatalog();
  if (!catalog.data) return <LoadingState size="section" />;
  // Natives only: a custom connector has its own way in, below.
  const natives = catalog.data.filter((entry) => !isCustom(entry.key));
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-medium text-brand-navy">{t.sources.add.choose}</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {natives.map((entry) => (
          <li key={entry.key}>
            <button
              type="button"
              onClick={() => onPick(entry)}
              className="flex w-full items-center gap-3 rounded-lg border border-shell-line bg-white p-3 text-start outline-none hover:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            >
              <SourceLogo kind={entry.key} className="size-7 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium text-brand-navy">{entry.display_name}</span>
                <span className="block truncate text-xs text-shell-muted">
                  {entry.capabilities.map((c) => capabilityWord(t, c, entry.key)).join(", ")}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-shell-line p-3 sm:flex-row sm:items-center">
        <p className="flex-1 text-xs text-shell-muted">
          <span className="font-medium text-brand-navy">{t.sources.custom.fromCatalog}</span>{" "}
          {t.sources.add.missingBody}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onCustom}>
          <Wrench aria-hidden="true" />
          {t.sources.custom.fromCatalogAction}
        </Button>
      </div>
    </section>
  );
}

// ── 1. The method, for a custom connector (LEKA-426) ────────────────────────

function MethodStep({
  onPick,
  onBack,
}: {
  onPick: (entry: CatalogEntry) => void;
  onBack?: () => void;
}) {
  const t = useDictionary();
  const w = t.sources.custom;
  const catalog = useCatalog();
  if (!catalog.data) return <LoadingState size="section" />;
  const methods = CUSTOM_KINDS.map((key) => catalog.data.find((entry) => entry.key === key)).filter(
    (entry): entry is CatalogEntry => entry !== undefined,
  );
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-medium text-brand-navy">{w.title}</h3>
        <p className="text-xs text-shell-muted">{w.intro}</p>
      </div>
      <ul className="flex flex-col gap-2">
        {methods.map((entry) => {
          const words = w.methods[entry.key as keyof typeof w.methods];
          return (
            <li key={entry.key}>
              <button
                type="button"
                onClick={() => onPick(entry)}
                className="flex w-full items-start gap-3 rounded-lg border border-shell-line bg-white p-3 text-start outline-none hover:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                <SourceLogo kind={entry.key} className="mt-0.5 size-7 shrink-0" />
                <span className="min-w-0">
                  <span className="block font-medium text-brand-navy">{words.title}</span>
                  <span className="block text-sm text-shell-muted">{words.body}</span>
                  <span className="mt-1 block text-xs text-shell-muted">
                    {fill(w.needs, { needs: words.needs })}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <section
        aria-labelledby="custom-unsupported"
        className="rounded-lg border border-shell-line bg-shell-canvas p-3"
      >
        <h4
          id="custom-unsupported"
          className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-brand-navy"
        >
          <Ban className="size-4" aria-hidden="true" />
          {w.unsupportedTitle}
        </h4>
        <ul className="list-disc space-y-0.5 ps-5 text-xs text-shell-muted">
          {w.unsupported.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-shell-muted">{w.unsupportedContact}</p>
      </section>
      {onBack ? (
        <Button type="button" variant="ghost" className="self-start" onClick={onBack}>
          {t.sources.add.back}
        </Button>
      ) : null}
    </section>
  );
}

// ── 2. The connection ───────────────────────────────────────────────────────

type Values = {
  display_name: string;
  // A yes or no — what LEKA may write — is a box, true or false.
  config: Record<string, string | boolean>;
  credentials: Record<string, string>;
};

function SettingsStep({
  entry,
  source,
  reconnecting = false,
  onBack,
  onSaved,
}: {
  entry: CatalogEntry;
  source: Source | null;
  reconnecting?: boolean;
  onBack?: () => void;
  onSaved: (source: Source) => void;
}) {
  const t = useDictionary();
  const configFields = useMemo(() => fieldsOf(entry.config_schema), [entry]);
  const secretFields = useMemo(() => fieldsOf(entry.credentials_schema), [entry]);
  const scopeField = scopeFieldOf(entry.config_schema);
  const editing = source !== null;
  const save = useSourceMutation(async (given: Values) => {
    // What a choice made pointless — a header name without a header — is
    // not sent, whatever was typed in it before the choice changed.
    const values = {
      ...given,
      config: shownOnly(entry.key, given.config, given.config),
      credentials: shownOnly(entry.key, given.credentials, given.config),
    };
    if (!source) {
      return sources.create({
        type: entry.key,
        display_name: values.display_name,
        config: filled(values.config),
        credentials: filled(values.credentials),
      });
    }
    // A field emptied goes back to its default; the scope is kept.
    const scope = scopeField ? { [scopeField]: source.config[scopeField] ?? null } : {};
    let saved = await sources.update(source.id, {
      display_name: values.display_name,
      config: { ...scope, ...filled(values.config) },
    });
    const secrets = filled(values.credentials);
    if (Object.keys(secrets).length > 0)
      saved = await sources.rotateCredentials(source.id, secrets);
    return saved;
  });

  const schema = useMemo(
    () =>
      z.object({
        display_name: z.string().trim().min(1).max(200),
        config: zodOf(configFields),
        credentials: zodOf(secretFields, { keepSecrets: editing }),
      }),
    [configFields, secretFields, editing],
  ) as unknown as z.ZodType<Values, Values>;

  const current = (source?.config ?? {}) as Record<string, unknown>;
  const form = useLekaForm<Values>({
    schema,
    defaultValues: {
      display_name: source?.display_name ?? entry.display_name,
      config: Object.fromEntries(
        configFields.map((f) => [f.name, initialOf(f, current[f.name])]),
      ),
      credentials: defaultsOf(secretFields),
    },
    onSubmit: async (values) => {
      try {
        onSaved(await save.mutateAsync(values));
      } catch (error) {
        // The plan's limit (LEKA-463), said in the person's language.
        if (!(error instanceof ApiError && error.code === "plan_limit")) throw error;
        form.setError("root", { type: "server", message: t.billing.planLimit.sources });
      }
    },
  });
  const chosen = (useWatch({ control: form.control, name: "config" }) ?? {}) as Record<
    string,
    string
  >;
  const shown = (field: FieldSpec) => shownFor(entry.key, field.name, chosen);

  return (
    <FormProvider {...form}>
      <form onSubmit={form.submit} className="flex flex-col gap-4" noValidate>
        <FormAlert<Values> />
        {reconnecting ? (
          <Alert>
            <TriangleAlert aria-hidden="true" />
            <AlertDescription>{t.sources.page.reconnectHint}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex items-center gap-2">
          <SourceLogo kind={entry.key} className="size-6" />
          <span className="font-medium text-brand-navy">{entry.display_name}</span>
        </div>
        <TextField<Values, "display_name">
          name="display_name"
          label={t.sources.add.name}
          description={t.sources.add.nameHelp}
        />
        {secretFields.filter(shown).map((field) => (
          <SchemaField
            key={field.name}
            kind={entry.key}
            field={field}
            part="credentials"
            keepSecret={editing}
          />
        ))}
        {configFields.filter(shown).map((field) => (
          <SchemaField key={field.name} kind={entry.key} field={field} part="config" />
        ))}
        <div className="flex justify-between gap-2">
          {onBack ? (
            <Button type="button" variant="ghost" onClick={onBack}>
              {t.sources.add.back}
            </Button>
          ) : (
            <span />
          )}
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {editing ? t.sources.add.next : t.sources.add.create}
          </Button>
        </div>
      </form>
    </FormProvider>
  );
}

function SchemaField({
  kind,
  field,
  part,
  keepSecret = false,
}: {
  kind: string;
  field: FieldSpec;
  part: "config" | "credentials";
  keepSecret?: boolean;
}) {
  const t = useDictionary();
  const known = fieldWords(t, field.name, kind);
  const help = [
    known?.help,
    keepSecret && field.kind === "password" ? t.sources.add.keepSecret : null,
  ]
    .filter(Boolean)
    .join(" ");
  const name = `${part}.${field.name}` as `config.${string}`;
  const optional = !field.required || (keepSecret && field.kind === "password");
  if (field.kind === "toggle") {
    return (
      <CheckboxField<Values, typeof name>
        name={name}
        label={known?.label ?? field.title}
        description={help || undefined}
      />
    );
  }
  if (field.kind === "choice") {
    const words = (t.sources.choices as Record<string, Record<string, string> | undefined>)[
      field.name
    ];
    return (
      <SelectField<Values, typeof name>
        name={name}
        label={known?.label ?? field.title}
        description={help || undefined}
        optional={optional}
        options={(field.options ?? []).map((value) => ({
          value,
          label: words?.[value] ?? value,
        }))}
      />
    );
  }
  if (field.kind === "json") {
    return (
      <div className="flex flex-col gap-1.5">
        <TextareaField<Values, typeof name>
          name={name}
          label={known?.label ?? field.title}
          description={help || undefined}
          optional={optional}
          minRows={8}
          maxRows={24}
          code
        />
        {TEMPLATES[kind] ? <Example kind={kind} name={name} /> : null}
      </div>
    );
  }
  return (
    <TextField<Values, typeof name>
      name={name}
      label={known?.label ?? field.title}
      description={help || undefined}
      optional={optional}
      type={field.kind === "number" ? "text" : field.kind}
      inputMode={field.kind === "number" ? "numeric" : undefined}
      autoComplete={field.kind === "password" ? "off" : undefined}
    />
  );
}

/** An empty definition starts from one that works — to edit, not to write. */
function Example({ kind, name }: { kind: string; name: `config.${string}` }) {
  const t = useDictionary();
  const form = useFormContext<Values>();
  const value = useWatch({ control: form.control, name });
  if (typeof value === "string" && value.trim() !== "") return null;
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="self-start"
      onClick={() =>
        form.setValue(name, TEMPLATES[kind], { shouldDirty: true, shouldValidate: true })
      }
    >
      {t.sources.custom.example}
    </Button>
  );
}

// ── 3. The scope ────────────────────────────────────────────────────────────

function ScopeStep({
  entry,
  source,
  onEdit,
  onSaved,
}: {
  entry: CatalogEntry;
  source: Source;
  onEdit: () => void;
  onSaved: (source: Source) => void;
}) {
  const t = useDictionary();
  const scopeField = scopeFieldOf(entry.config_schema) as string;
  const stored = source.config[scopeField];
  const [mode, setMode] = useState<"all" | "some">(Array.isArray(stored) ? "some" : "all");
  const [chosen, setChosen] = useState<Set<string>>(
    new Set(Array.isArray(stored) ? (stored as string[]) : []),
  );
  const [filter, setFilter] = useState("");
  const [refused, setRefused] = useState(false);
  const options = useQuery({
    queryKey: ["sources", "scope", source.id],
    queryFn: () => sources.scopeOptions(source.id),
    retry: false,
    staleTime: 0,
    // Asked of the connected service itself: once, not on a timer.
    refetchInterval: false,
  });
  const save = useSourceMutation((scope: string[] | null) =>
    sources.update(source.id, { config: { ...source.config, [scopeField]: scope } }),
  );

  // A connector without a scope to choose: nothing to ask.
  const noScope = options.error instanceof ApiError && options.error.status === 409;
  const skipped = useRef(false);
  useEffect(() => {
    if (noScope && !skipped.current) {
      skipped.current = true;
      onSaved(source);
    }
  }, [noScope, onSaved, source]);

  if (options.isPending || noScope)
    return <LoadingState size="section" label={t.sources.add.scopeLoading} />;
  if (options.isError) return <ErrorAlert title={t.sources.add.testFailed} onEdit={onEdit} />;
  if (!options.data.ok) {
    return (
      <ErrorAlert
        title={t.sources.add.testFailed}
        diagnostic={options.data.diagnostic}
        onEdit={onEdit}
      />
    );
  }

  const listed = options.data.options ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = needle ? listed.filter((o) => o.name.toLowerCase().includes(needle)) : listed;

  async function next() {
    if (mode === "some" && chosen.size === 0) {
      setRefused(true);
      return;
    }
    const scope = mode === "all" ? null : listed.map((o) => o.key).filter((key) => chosen.has(key));
    const unchanged = JSON.stringify(scope) === JSON.stringify(stored ?? null);
    onSaved(unchanged ? source : await save.mutateAsync(scope));
  }

  return (
    <section className="flex flex-col gap-3">
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium text-brand-navy">
          {t.sources.add.scopeTitle}
        </legend>
        {(["all", "some"] as const).map((value) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={mode === value}
              onChange={() => setMode(value)}
            />
            {value === "all" ? t.sources.add.scopeAll : t.sources.add.scopeSome}
          </label>
        ))}
      </fieldset>

      {mode === "some" ? (
        listed.length === 0 ? (
          <p className="text-sm text-shell-muted">{t.sources.add.scopeEmpty}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="relative">
              <Search
                className="absolute top-2.5 start-2.5 size-4 text-shell-muted"
                aria-hidden="true"
              />
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder={t.sources.add.scopeSearch}
                aria-label={t.sources.add.scopeSearch}
                className="ps-8"
              />
            </div>
            <ul
              aria-label={t.sources.add.scopeTitle}
              className="max-h-64 divide-y divide-shell-line overflow-y-auto rounded-lg border border-shell-line"
            >
              {shown.map((option) => (
                <li key={option.key}>
                  <label className="flex cursor-pointer items-start gap-3 p-2.5 text-sm">
                    <Checkbox
                      checked={chosen.has(option.key)}
                      onCheckedChange={(checked) => {
                        const next = new Set(chosen);
                        if (checked) next.add(option.key);
                        else next.delete(option.key);
                        setChosen(next);
                        setRefused(false);
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block text-brand-navy">{option.name}</span>
                      {option.description ? (
                        <span className="block truncate text-xs text-shell-muted">
                          {option.description}
                        </span>
                      ) : null}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <p className="text-xs text-shell-muted" aria-live="polite">
              {fill(t.sources.add.scopeChosen, { count: chosen.size })}
              {options.data.truncated ? ` · ${t.sources.add.scopeTruncated}` : ""}
            </p>
          </div>
        )
      ) : null}
      {refused ? (
        <p role="alert" className="text-sm text-state-danger">
          {t.sources.add.scopeNone}
        </p>
      ) : null}

      <div className="flex justify-between gap-2">
        <Button type="button" variant="ghost" onClick={onEdit}>
          {t.sources.add.back}
        </Button>
        <Button type="button" onClick={() => void next()} disabled={save.isPending}>
          {t.sources.add.next}
        </Button>
      </div>
    </section>
  );
}

// ── 4. Test and activation ──────────────────────────────────────────────────

function TestStep({
  source,
  onEdit,
  onDone,
}: {
  source: Source;
  onEdit: () => void;
  onDone: (source: Source) => void;
}) {
  const t = useDictionary();
  const test = useSourceMutation(() => sources.test(source.id));
  const activate = useSourceMutation(() => sources.activate(source.id));
  const started = useRef(false);

  useEffect(() => {
    // Once, on arrival: the admin is here to see whether it works.
    if (started.current) return;
    started.current = true;
    test.mutate(undefined);
  }, [test]);

  if (test.isPending || test.isIdle)
    return <LoadingState size="section" label={t.sources.add.testing} />;
  const outcome = test.data;
  if (!outcome || !outcome.ok || !outcome.result) {
    // What LEKA cannot do is said as such, not as a failure to retry.
    const unsupported = outcome?.diagnostic?.code === "UNSUPPORTED";
    return (
      <div className="flex flex-col gap-3">
        <ErrorAlert
          title={unsupported ? t.sources.add.unsupported : t.sources.add.testFailed}
          diagnostic={outcome?.diagnostic}
          onEdit={onEdit}
        />
        <Button
          type="button"
          variant="outline"
          className="self-start"
          onClick={() => test.mutate(undefined)}
        >
          {t.sources.add.retry}
        </Button>
      </div>
    );
  }

  const result = outcome.result;
  async function switchOn() {
    const activated = await activate.mutateAsync(undefined);
    notify.success({ title: fill(t.sources.add.activated, { name: activated.display_name }) });
    onDone(activated);
  }
  function later() {
    notify.info({ title: fill(t.sources.add.saved, { name: outcome?.source.display_name ?? "" }) });
    onDone(outcome?.source ?? source);
  }

  return (
    <div className="flex flex-col gap-3">
      <Alert variant="success">
        <CircleCheck aria-hidden="true" />
        <AlertTitle>{t.sources.add.testOk}</AlertTitle>
        <AlertDescription>
          {result.account ? (
            <p>{fill(t.sources.add.account, { account: result.account })}</p>
          ) : null}
          <p>
            {fill(t.sources.add.reads, {
              list: result.capabilities.map((c) => capabilityWord(t, c, source.type)).join(", "),
            })}
          </p>
        </AlertDescription>
      </Alert>
      {(result.warnings ?? []).map((warning) => (
        <Alert key={warning}>
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>{warning}</AlertDescription>
        </Alert>
      ))}
      <MappingPreview outcome={outcome} />
      {source.type === "custom_webhook" ? (
        <Receiving source={source} />
      ) : null}
      <div className="flex justify-between gap-2">
        <Button type="button" variant="ghost" onClick={later}>
          {t.sources.add.later}
        </Button>
        <Button type="button" onClick={() => void switchOn()} disabled={activate.isPending}>
          {t.sources.add.activate}
        </Button>
      </div>
    </div>
  );
}

/** What the mapping read in each resource's first record (LEKA-426): the
 * admin sees it work before switching the source on. Shown here, stored
 * nowhere — the API returns it with the test and keeps none of it. */
function MappingPreview({ outcome }: { outcome: TestOutcome }) {
  const t = useDictionary();
  const w = t.sources.custom;
  const previews = outcome.result?.preview ?? [];
  if (previews.length === 0) return null;
  const fieldLabel = (name: string) =>
    name.startsWith("metadata.")
      ? fill(w.preview.metadata, { name: name.slice("metadata.".length) })
      : ((w.fields as Record<string, string>)[name] ?? name);
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-medium text-brand-navy">{w.preview.title}</h3>
      {previews.map((preview) => (
        <div key={preview.name} className="rounded-lg border border-shell-line p-3">
          <p className="text-sm text-brand-navy">
            <span className="font-medium">{preview.name}</span>
            {preview.entity ? (
              <span className="text-shell-muted">
                {" "}
                · {(w.entities as Record<string, string>)[preview.entity] ?? preview.entity}
              </span>
            ) : null}
            <span className="text-shell-muted">
              {" "}
              · {fill(w.preview.read, { count: preview.read })}
            </span>
          </p>
          {preview.read === 0 ? (
            <p className="mt-1 text-xs text-shell-muted">{w.preview.empty}</p>
          ) : (
            <table className="mt-2 w-full text-start text-xs">
              <caption className="sr-only">
                {fill(w.preview.caption, { resource: preview.name })}
              </caption>
              <thead className="text-shell-muted">
                <tr>
                  <th scope="col" className="w-40 py-1 pe-3 font-medium">
                    {w.preview.field}
                  </th>
                  <th scope="col" className="py-1 font-medium">
                    {w.preview.value}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-shell-line">
                {Object.entries(preview.fields ?? {}).map(([name, value]) => (
                  <tr key={name}>
                    <th scope="row" className="py-1 pe-3 font-normal text-shell-muted">
                      {fieldLabel(name)}
                    </th>
                    <td className="py-1 break-all text-brand-navy">{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(preview.missing ?? []).length > 0 ? (
            <p className="mt-2 text-xs text-state-warning">
              {fill(w.preview.missing, {
                fields: (preview.missing ?? []).map(fieldLabel).join(", "),
              })}
            </p>
          ) : null}
        </div>
      ))}
    </section>
  );
}

/** A webhook reads nothing to test: what the admin needs next is its address. */
function Receiving({ source }: { source: Source }) {
  const t = useDictionary();
  const address = receivingAddress(source.id);
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-shell-line p-3">
      <MetadataPanel
        sections={[
          {
            items: [
              {
                label: t.sources.reception.address,
                value: <code className="break-all">{address}</code>,
                copyValue: address,
              },
            ],
          },
        ]}
      />
      <p className="text-xs text-shell-muted">{t.sources.custom.webhookNext}</p>
    </div>
  );
}

function ErrorAlert({
  title,
  diagnostic,
  onEdit,
}: {
  title: string;
  diagnostic?: Diagnostic | null;
  onEdit: () => void;
}) {
  const t = useDictionary();
  return (
    <div className="flex flex-col gap-3">
      <Alert variant="destructive">
        <TriangleAlert aria-hidden="true" />
        <AlertTitle>{title}</AlertTitle>
        {diagnostic ? (
          <AlertDescription>
            <p>{diagnostic.message}</p>
            <p>{diagnostic.remediation}</p>
          </AlertDescription>
        ) : null}
      </Alert>
      <Button type="button" variant="outline" className="self-start" onClick={onEdit}>
        {t.sources.add.edit}
      </Button>
    </div>
  );
}
