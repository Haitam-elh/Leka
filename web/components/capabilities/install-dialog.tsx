"use client";

import { Check, ChevronRight, Copy, Download, FileCode2, Lock, PackageOpen } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiAddress } from "@/lib/api";
import {
  EMPTY_SETUP,
  installer,
  installerName,
  MANUAL,
  MODELS,
  type ModelKind,
  runCommand,
  type Setup,
  type System,
} from "@/lib/architect-install";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * « Installer dans votre environnement » (2026-10-25): the architect on the
 * organisation's own machines, its own model, its own Confluence — nothing
 * through LEKA. Three steps (2026-10-25: « personne va le faire »):
 *
 *   1. its details — Confluence, the model —, optional, each with where to
 *      find it; they stay in this browser, never sent to LEKA;
 *   2. two downloads: the agent (authenticated, refused to an organisation it
 *      is not dedicated to) and its installer, made here with those details;
 *   3. one command to paste: Python checked, the agent unzipped in
 *      ~/architecte and installed, .env written, Copilot set up, « Lancer
 *      l'architecte » made — to double-click.
 *
 * Every « Détail » says where to click, for Windows, macOS or Linux. By hand,
 * the same steps as numbered blocks — for a computer that refuses scripts.
 */

/** The agents a customer may install: their package is built from LEKA's own code. */
export const INSTALLABLE: ReadonlySet<string> = new Set(["application-architecture"]);

const SYSTEMS: readonly System[] = ["windows", "macos", "linux"];
const MODEL_KINDS: readonly ModelKind[] = ["copilot", "azure", "anthropic", "gemini", "mistral", "openai", "other"];

/** The system of this browser — a guess, changed in one click. */
function systemOf(agent: string): System {
  if (/Windows/i.test(agent)) return "windows";
  if (/Mac|darwin/i.test(agent)) return "macos";
  return "linux";
}

// ── Parts ───────────────────────────────────────────────────────────────

/** Its words, each address in them a link — opened apart. */
function Linked({ text }: { text: string }) {
  const parts = text.split(/(https:\/\/[^\s),]+[^\s),.])/g);
  return (
    <>
      {parts.map((part, n) =>
        part.startsWith("https://") ? (
          <a
            key={n}
            href={part}
            target="_blank"
            rel="noreferrer"
            className="font-medium break-all text-shell-nav-active underline underline-offset-2"
          >
            {part}
          </a>
        ) : (
          <span key={n}>{part}</span>
        ),
      )}
    </>
  );
}

/** A « Détail »: closed until asked, its steps numbered. */
function Detail({ title, steps, testId, children }: { title: string; steps?: readonly string[]; testId?: string; children?: React.ReactNode }) {
  return (
    <details className="group rounded-lg border border-shell-line bg-shell-canvas/50 px-3 py-2" data-testid={testId}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[0.8125rem] font-medium text-shell-nav-active outline-none select-none focus-visible:ring-2 focus-visible:ring-brand-violet/40 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 shrink-0 transition-transform group-open:rotate-90" aria-hidden="true" />
        {title}
      </summary>
      <div className="mt-2 flex flex-col gap-2 text-[0.8125rem] text-brand-navy">
        {steps ? (
          <ol className="list-decimal space-y-1 ps-5">
            {steps.map((step) => (
              <li key={step}>
                <Linked text={step} />
              </li>
            ))}
          </ol>
        ) : null}
        {children}
      </div>
    </details>
  );
}

function Copyable({ text, label }: { text: string; label?: string }) {
  const t = useDictionary();
  const w = t.catalogue.install;
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-brand-navy">{label}</span>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            } catch {
              setCopied(false);
            }
          }}
          data-testid="install-copy"
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? w.copied : w.copy}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-lg bg-brand-navy px-3 py-2 text-[0.75rem] leading-relaxed text-white">
        <code>{text}</code>
      </pre>
    </div>
  );
}

function Step({ n, title, lead, children }: { n: number; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section className="flex gap-3" aria-labelledby={`install-step-${n}`} data-testid={`install-step-${n}`}>
      <span
        className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-navy text-[0.8125rem] font-bold text-white"
        aria-hidden="true"
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div>
          <h3 id={`install-step-${n}`} className="text-[0.9375rem] font-semibold text-brand-navy">
            {title}
          </h3>
          {lead ? <p className="mt-0.5 text-[0.8125rem] text-shell-muted">{lead}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "password" | "email" | "url";
  testId: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-brand-navy">
      {label}
      <Input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        data-testid={testId}
      />
    </label>
  );
}

/** The installer, written here and saved — nothing sent anywhere. */
function save(system: System, setup: Setup): void {
  const blob = new Blob([installer(system, setup)], { type: "text/plain;charset=utf-8" });
  const address = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = address;
  link.download = installerName(system);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(address), 1000);
}

// ── The dialog ──────────────────────────────────────────────────────────

export function InstallAgent({ agentKey, className }: { agentKey: string; className?: string }) {
  const t = useDictionary();
  const w = t.catalogue.install;
  const [open, setOpen] = useState(false);
  const [system, setSystem] = useState<System>(() =>
    systemOf(typeof navigator === "undefined" ? "" : navigator.userAgent),
  );
  const [setup, setSetup] = useState<Setup>(EMPTY_SETUP);
  if (!INSTALLABLE.has(agentKey)) return null;
  const terminal = w.terminals[system];
  const kind = setup.model;
  const set = (patch: Partial<Setup>) => setSetup((current) => ({ ...current, ...patch }));
  const choose = (model: ModelKind) =>
    set({ model, modelName: MODELS[model].name, modelUrl: MODELS[model].url, modelKey: "" });

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className={className}
        onClick={() => setOpen(true)}
        data-testid="install-open"
      >
        <PackageOpen aria-hidden="true" />
        {w.open}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          // Closed, its details are forgotten: nothing kept of a token.
          if (!next) setSetup(EMPTY_SETUP);
        }}
      >
        <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-2xl" data-testid="install-dialog">
          <DialogHeader>
            <DialogTitle>{w.title}</DialogTitle>
            <DialogDescription>{w.lead}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={w.system}>
            <span className="text-xs font-medium text-shell-muted">{w.system}</span>
            {SYSTEMS.map((name) => (
              <button
                key={name}
                type="button"
                role="radio"
                aria-checked={system === name}
                onClick={() => setSystem(name)}
                className={
                  system === name
                    ? "rounded-full bg-brand-navy px-3 py-1 text-xs font-medium text-white"
                    : "rounded-full bg-shell-canvas px-3 py-1 text-xs font-medium text-brand-navy hover:bg-brand-violet-soft/60"
                }
                data-testid={`install-system-${name}`}
              >
                {w.systems[name]}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-6">
            <Step n={1} title={w.step1} lead={w.step1Lead}>
              <fieldset className="flex flex-col gap-2 rounded-xl border border-shell-line p-3">
                <legend className="px-1 text-xs font-semibold text-brand-navy">{w.confluence}</legend>
                <Field
                  label={w.url}
                  value={setup.confluenceUrl}
                  onChange={(confluenceUrl) => set({ confluenceUrl })}
                  placeholder={w.urlPlaceholder}
                  type="url"
                  testId="install-confluence-url"
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field
                    label={w.email}
                    value={setup.confluenceEmail}
                    onChange={(confluenceEmail) => set({ confluenceEmail })}
                    placeholder={w.emailPlaceholder}
                    type="email"
                    testId="install-confluence-email"
                  />
                  <Field
                    label={w.token}
                    value={setup.confluenceToken}
                    onChange={(confluenceToken) => set({ confluenceToken })}
                    type="password"
                    testId="install-confluence-token"
                  />
                </div>
                <Detail title={w.urlHow.title} steps={w.urlHow.steps} />
                <Detail title={w.tokenHow.title} steps={w.tokenHow.steps} testId="install-token-how" />
              </fieldset>

              <fieldset className="flex flex-col gap-2 rounded-xl border border-shell-line p-3">
                <legend className="px-1 text-xs font-semibold text-brand-navy">{w.model}</legend>
                <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={w.model}>
                  {MODEL_KINDS.map((name) => (
                    <button
                      key={name}
                      type="button"
                      role="radio"
                      aria-checked={kind === name}
                      onClick={() => choose(name)}
                      className={cn(
                        "rounded-lg border px-2.5 py-1 text-xs font-medium",
                        kind === name
                          ? "border-brand-navy bg-brand-navy text-white"
                          : "border-shell-line bg-white text-brand-navy hover:bg-brand-violet-soft/60",
                      )}
                      data-testid={`install-model-${name}`}
                    >
                      {w.models[name]}
                    </button>
                  ))}
                </div>
                {kind === "copilot" ? (
                  <p className="text-[0.8125rem] text-shell-muted">{w.copilotSaid}</p>
                ) : (
                  <>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Field
                        label={kind === "azure" ? w.modelNameAzure : w.modelName}
                        value={setup.modelName}
                        onChange={(modelName) => set({ modelName })}
                        testId="install-model-name"
                      />
                      <Field
                        label={w.modelKey}
                        value={setup.modelKey}
                        onChange={(modelKey) => set({ modelKey })}
                        type="password"
                        testId="install-model-key"
                      />
                    </div>
                    {kind === "azure" || kind === "other" ? (
                      <Field
                        label={kind === "azure" ? w.modelUrlAzure : w.modelUrl}
                        value={setup.modelUrl}
                        onChange={(modelUrl) => set({ modelUrl })}
                        placeholder={kind === "azure" ? "https://votre-ressource.openai.azure.com" : "https://…/v1"}
                        type="url"
                        testId="install-model-url"
                      />
                    ) : null}
                    <Detail title={w.keyHow.title} steps={w.keyHow[kind]} testId="install-key-how" />
                  </>
                )}
              </fieldset>
              <p className="flex items-start gap-1.5 text-xs text-shell-muted" data-testid="install-stay">
                <Lock className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                {w.stay}
              </p>
            </Step>

            <Step n={2} title={w.step2} lead={w.step2Lead}>
              <div className="flex flex-wrap gap-2">
                <a
                  href={apiAddress(`/capabilities/${encodeURIComponent(agentKey)}/package`)}
                  className={buttonVariants({ size: "sm" })}
                  download
                  data-testid="install-download"
                >
                  <Download aria-hidden="true" />
                  {w.downloadAgent}
                </a>
                <Button type="button" size="sm" onClick={() => save(system, setup)} data-testid="install-installer">
                  <FileCode2 aria-hidden="true" />
                  {w.downloadInstaller}
                </Button>
              </div>
              <Detail title={w.filesHow.title} steps={w.filesHow.steps} />
            </Step>

            <Step n={3} title={w.step3} lead={fill(w.step3Lead, { terminal })}>
              <Detail title={fill(w.openHow.title, { terminal })} steps={w.openHow[system]} testId="install-open-how" />
              <Copyable text={runCommand(system)} />
              <ul className="list-disc space-y-0.5 ps-5 text-[0.8125rem] text-shell-muted">
                {w.does.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p className="rounded-lg bg-brand-violet-soft/50 px-3 py-2 text-[0.8125rem] font-medium text-brand-navy" data-testid="install-launch">
                {w.launch}
              </p>
              <Detail title={w.copilotHow.title} steps={w.copilotHow.steps} testId="install-copilot-how" />
              <Detail title={w.laterHow.title} steps={w.laterHow.steps} />
              <Detail title={w.problemsHow.title} steps={w.problemsHow.steps} />
              <Detail title={w.manualHow.title} testId="install-manual">
                <p className="text-shell-muted">{fill(w.manualHow.lead, { terminal })}</p>
                <Copyable label={`1. ${w.manualInstall}`} text={MANUAL[system].install} />
                <Copyable label={`2. ${w.manualEnv}`} text={MANUAL[system].env} />
                <Copyable label={`3. ${w.manualCheck}`} text={MANUAL[system].check} />
                <Copyable label={`4. ${w.manualRun}`} text={MANUAL[system].run} />
              </Detail>
            </Step>
          </div>
          <p className="text-xs text-shell-muted">{w.private}</p>
        </DialogContent>
      </Dialog>
    </>
  );
}
