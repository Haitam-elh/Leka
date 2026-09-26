"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, Lock, Search, TriangleAlert, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { FormProvider } from "react-hook-form";

import { cn } from "cn";
import { FormAlert } from "@/components/forms/form-alert";
import { TextField } from "@/components/forms/text-field";
import { capabilityWord } from "@/components/sources/source-panel";
import { SourceLogo } from "@/components/sources/source-logo";
import { LoadingState } from "@/components/states/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { type CatalogEntry, type Diagnostic, type Source, sources } from "@/lib/sources";
import {
  defaultsOf,
  type FieldSpec,
  fieldsOf,
  filled,
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
 */

type Step = "connector" | "settings" | "scope" | "test";
const STEPS: Step[] = ["connector", "settings", "scope", "test"];

export function AddSourceDialog({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: (source: Source) => void;
}) {
  const t = useDictionary();
  const [step, setStep] = useState<Step>("connector");
  const [entry, setEntry] = useState<CatalogEntry | null>(null);
  const [source, setSource] = useState<Source | null>(null);

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setStep("connector");
      setEntry(null);
      setSource(null);
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
            <DialogTitle>{t.sources.add.title}</DialogTitle>
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
        <Stepper step={step} />

        {step === "connector" ? (
          <ConnectorStep
            onPick={(picked) => {
              setEntry(picked);
              setStep("settings");
            }}
          />
        ) : null}
        {step === "settings" && entry ? (
          <SettingsStep
            entry={entry}
            source={source}
            onBack={source ? undefined : () => setStep("connector")}
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

function Stepper({ step }: { step: Step }) {
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
          {index + 1}. {t.sources.add.steps[name]}
        </li>
      ))}
    </ol>
  );
}

// ── 1. The tool ─────────────────────────────────────────────────────────────

function ConnectorStep({ onPick }: { onPick: (entry: CatalogEntry) => void }) {
  const t = useDictionary();
  const catalog = useCatalog();
  if (!catalog.data) return <LoadingState size="section" />;
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-medium text-brand-navy">{t.sources.add.choose}</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {catalog.data.map((entry) => (
          <li key={entry.key}>
            <button
              type="button"
              onClick={() => onPick(entry)}
              className="flex w-full items-center gap-3 rounded-lg border border-shell-line bg-white p-3 text-left outline-none hover:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            >
              <SourceLogo kind={entry.key} className="size-7 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium text-brand-navy">{entry.display_name}</span>
                <span className="block truncate text-xs text-shell-muted">
                  {entry.capabilities.map((c) => capabilityWord(t, c)).join(", ")}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-shell-muted">
        <span className="font-medium">{t.sources.add.missingTitle}</span>{" "}
        {t.sources.add.missingBody}
      </p>
    </section>
  );
}

// ── 2. The connection ───────────────────────────────────────────────────────

type Values = {
  display_name: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
};

function SettingsStep({
  entry,
  source,
  onBack,
  onSaved,
}: {
  entry: CatalogEntry;
  source: Source | null;
  onBack?: () => void;
  onSaved: (source: Source) => void;
}) {
  const t = useDictionary();
  const configFields = useMemo(() => fieldsOf(entry.config_schema), [entry]);
  const secretFields = useMemo(() => fieldsOf(entry.credentials_schema), [entry]);
  const scopeField = scopeFieldOf(entry.config_schema);
  const editing = source !== null;
  const save = useSourceMutation(async (values: Values) => {
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
        configFields.map((f) => [
          f.name,
          typeof current[f.name] === "string" ? String(current[f.name]) : f.default,
        ]),
      ),
      credentials: defaultsOf(secretFields),
    },
    onSubmit: async (values) => onSaved(await save.mutateAsync(values)),
  });

  return (
    <FormProvider {...form}>
      <form onSubmit={form.submit} className="flex flex-col gap-4" noValidate>
        <FormAlert<Values> />
        <div className="flex items-center gap-2">
          <SourceLogo kind={entry.key} className="size-6" />
          <span className="font-medium text-brand-navy">{entry.display_name}</span>
        </div>
        <TextField<Values, "display_name">
          name="display_name"
          label={t.sources.add.name}
          description={t.sources.add.nameHelp}
        />
        {secretFields.map((field) => (
          <SchemaField key={field.name} field={field} part="credentials" keepSecret={editing} />
        ))}
        {configFields.map((field) => (
          <SchemaField key={field.name} field={field} part="config" />
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
  field,
  part,
  keepSecret = false,
}: {
  field: FieldSpec;
  part: "config" | "credentials";
  keepSecret?: boolean;
}) {
  const t = useDictionary();
  const known = (t.sources.fields as Record<string, { label: string; help: string }>)[field.name];
  const help = [
    known?.help,
    keepSecret && field.kind === "password" ? t.sources.add.keepSecret : null,
  ]
    .filter(Boolean)
    .join(" ");
  const name = `${part}.${field.name}` as `config.${string}`;
  return (
    <TextField<Values, typeof name>
      name={name}
      label={known?.label ?? field.title}
      description={help || undefined}
      optional={!field.required || (keepSecret && field.kind === "password")}
      type={field.kind}
      autoComplete={field.kind === "password" ? "off" : undefined}
    />
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
                className="absolute top-2.5 left-2.5 size-4 text-shell-muted"
                aria-hidden="true"
              />
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder={t.sources.add.scopeSearch}
                aria-label={t.sources.add.scopeSearch}
                className="pl-8"
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
    return (
      <div className="flex flex-col gap-3">
        <ErrorAlert
          title={t.sources.add.testFailed}
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
              list: result.capabilities.map((c) => capabilityWord(t, c)).join(", "),
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
