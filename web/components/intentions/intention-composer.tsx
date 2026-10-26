"use client";

import {
  ArrowUp,
  ChevronRight,
  FileDiff,
  FileSymlink,
  Link2,
  Loader2,
  type LucideIcon,
  Mic,
  Send,
  ShieldCheck,
  Sparkle,
  Sparkles,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { cn } from "cn";
import { IconTile, type TileTone } from "@/components/environment/parts";
import {
  AttachmentList,
  AttachmentPicker,
  type Attachments,
} from "@/components/intentions/attachments";
import { useConfirm } from "@/components/interactions/confirm";
import { useCurrentWorkspace } from "@/components/shell/shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { INTENTION_MAX, INTENTION_MIN } from "@/lib/validation/intentions";

/**
 * The box the whole product is about.
 *
 * ENTER DOES NOT SUBMIT. An intention runs an analysis that costs money and
 * minutes, and it often takes several lines to describe. A newline is what
 * Enter means in a box like this, and ⌘↵ is what submitting means — the
 * same bargain every editor with a send button has made. The shortcut is
 * written next to the button and declared in `aria-keyshortcuts`, because a
 * shortcut nobody is told about is a shortcut nobody uses.
 *
 * SUGGESTIONS FILL IN, THEY DO NOT SEND. They drop a sentence with the
 * cursor sitting where the missing word goes. A suggestion that submitted
 * would be a button that spends money on a sentence the person never read.
 * If there is already text, it asks first: a template silently eating two
 * paragraphs is the kind of loss nobody forgives.
 *
 * THE DRAFT SURVIVES THE PAGE. sessionStorage, one key per workspace, so
 * going to check a service name and coming back does not cost the
 * paragraph. Cleared on submission and on a confirmed abandon. Every access
 * is wrapped: private browsing refuses storage, and the composer has to
 * work anyway.
 */

/** Dictation is designed and not built. The flag is what says so. */
const DICTATION_ENABLED = false;

function draftKeyFor(workspaceId: string | undefined): string {
  return `leka.intention.draft.${workspaceId ?? "unknown"}`;
}

function readDraft(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeDraft(key: string, value: string): void {
  try {
    if (value.trim() === "") window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    // No storage. The composer still works; the draft simply does not
    // outlive the page, which is the behaviour before this existed.
  }
}

export function clearDraft(workspaceId: string | undefined): void {
  try {
    window.sessionStorage.removeItem(draftKeyFor(workspaceId));
  } catch {
    // Nothing to clear if nothing could be stored.
  }
}

/** True when the browser could dictate, whether or not we have built it. */
function canDictate(): boolean {
  if (typeof window === "undefined") return false;
  return "SpeechRecognition" in window || "webkitSpeechRecognition" in window;
}

export function IntentionComposer({
  name = "text",
  variant = "full",
  files,
  onSubmit,
  submitting = false,
  submitLabel,
  suggested = true,
  className,
}: {
  /** The field in the surrounding form. */
  name?: string;
  variant?: "full" | "compact";
  /** Its files (components/intentions/attachments): the paperclip, and
   * what was chosen. Without, nothing to attach. */
  files?: Attachments;
  onSubmit: () => void;
  submitting?: boolean;
  /** What the button says: « Lancer l'analyse » by default. */
  submitLabel?: string;
  /** Its suggestions, under it: not once LEKA has read what was asked. */
  suggested?: boolean;
  className?: string;
}) {
  const t = useDictionary();
  const confirm = useConfirm();
  const workspace = useCurrentWorkspace();
  const { setValue, getValues } = useFormContext();
  const value = (useWatch({ name }) as string | undefined) ?? "";
  const box = useRef<HTMLTextAreaElement | null>(null);
  const [dictatable, setDictatable] = useState(false);

  // Read after mount: the server has no sessionStorage, and a value that
  // differed between the two would be a hydration error rather than a draft.
  const key = draftKeyFor(workspace?.id);
  useEffect(() => {
    setDictatable(canDictate());
    const draft = readDraft(key);
    if (draft !== "" && getValues(name) === "") {
      setValue(name, draft, { shouldDirty: false });
    }
  }, [key, name, getValues, setValue]);

  useEffect(() => {
    writeDraft(key, value);
  }, [key, value]);

  const tooLong = value.length > INTENTION_MAX;
  const empty = value.trim().length === 0;
  // Started, but not yet enough to analyse. The button is disabled, and a
  // disabled button that does not say why reads as broken.
  const missing = empty ? 0 : Math.max(0, INTENTION_MIN - value.trim().length);
  // A file on its way: nothing is asked before it is kept, or let go.
  const waiting = files?.uploading ?? false;
  const compact = variant === "compact";
  const whyDisabled = useId();
  // The card's headings and each suggestion's words, named for their parts.
  const ids = useId();

  // The mockup's four, with their icons. Each fills in a sentence; none sends.
  const suggestions: {
    icon: LucideIcon;
    tone: TileTone;
    label: string;
    hint: string;
    template: string;
  }[] = [
    {
      icon: Link2,
      tone: "danger",
      label: t.composer.suggestIncident,
      hint: t.composer.suggestIncidentHint,
      template: t.composer.suggestIncidentTemplate,
    },
    {
      icon: FileDiff,
      tone: "warning",
      label: t.composer.suggestChange,
      hint: t.composer.suggestChangeHint,
      template: t.composer.suggestChangeTemplate,
    },
    {
      icon: ShieldCheck,
      tone: "success",
      label: t.composer.suggestCompliance,
      hint: t.composer.suggestComplianceHint,
      template: t.composer.suggestComplianceTemplate,
    },
    {
      icon: FileSymlink,
      tone: "info",
      label: t.composer.suggestMigration,
      hint: t.composer.suggestMigrationHint,
      template: t.composer.suggestMigrationTemplate,
    },
  ];

  async function applySuggestion(template: string) {
    if (!empty) {
      const replace = await confirm({
        title: t.composer.replaceTitle,
        description: t.composer.replaceBody,
        confirmLabel: t.composer.replaceConfirm,
      });
      if (!replace) return;
    }
    // `{}` marks where the missing word goes; the cursor lands on it so the
    // next keystroke replaces it rather than appending to a template.
    const caret = template.indexOf("{}");
    const text = template.replace("{}", "");
    setValue(name, text, { shouldDirty: true, shouldValidate: false });
    window.requestAnimationFrame(() => {
      box.current?.focus();
      if (caret >= 0) box.current?.setSelectionRange(caret, caret);
    });
  }

  if (compact) {
    // The home's hero (LEKA-456, the sprint's mockup): the question as the
    // page's title, a white field — the spark, the paperclip, a round
    // violet button to send. No suggestion under it (LEKA-470): the
    // question is one's own.
    return (
      <section aria-labelledby="compact-composer-title" className={cn("text-center", className)}>
        <h1
          id="compact-composer-title"
          className="text-[2rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy md:text-[2.5rem]"
        >
          {t.composer.compactTitle}{" "}
          <span className="bg-gradient-to-r from-brand-navy to-brand-violet bg-clip-text text-transparent">
            {t.composer.compactTitleHighlight}
          </span>
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-[0.9375rem] text-shell-muted md:text-[1.0625rem]">
          {t.composer.compactSubtitle}
        </p>
        <div className="mx-auto mt-6 max-w-4xl text-start">
          <div className="flex items-center gap-3 rounded-2xl border border-shell-line bg-white p-2 ps-3 shadow-sm focus-within:border-brand-violet focus-within:ring-3 focus-within:ring-brand-violet/20">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-violet-soft">
              <Sparkle className="size-4 fill-brand-violet text-brand-violet" aria-hidden="true" />
            </span>
            <Textarea
              ref={box}
              value={value}
              onChange={(event) => setValue(name, event.target.value, { shouldDirty: true })}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
                event.preventDefault();
                onSubmit();
              }}
              aria-label={t.composer.label}
              aria-keyshortcuts="Meta+Enter Control+Enter"
              aria-describedby={missing > 0 ? whyDisabled : undefined}
              placeholder={t.composer.compactPlaceholder}
              rows={1}
              data-testid="intention-input"
              className="min-h-[52px] flex-1 resize-none border-0 bg-transparent px-1 py-3 text-base shadow-none placeholder:text-shell-muted focus-visible:ring-0"
            />
            {files ? <AttachmentPicker files={files} compact /> : null}
            <Button
              type="button"
              onClick={onSubmit}
              disabled={empty || tooLong || missing > 0 || submitting || waiting}
              aria-label={t.composer.submit}
              aria-busy={submitting || undefined}
              data-testid="intention-submit"
              className="size-11 shrink-0 rounded-full bg-brand-violet p-0 text-white transition-transform duration-150 ease-out hover:bg-brand-violet/90 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="size-5 animate-spin" aria-hidden="true" />
              ) : (
                <ArrowUp className="size-5" aria-hidden="true" />
              )}
            </Button>
          </div>
          {files ? <AttachmentList files={files} className="mt-2 ps-1" /> : null}
          {/* Only while it is true: a disabled button that does not say why
              reads as broken. */}
          <p
            id={whyDisabled}
            aria-live="polite"
            className="mt-1.5 ps-4 text-xs text-shell-muted empty:hidden"
          >
            {missing > 0
              ? fill(t.composer.tooShortHint, { count: missing })
              : tooLong
                ? fill(t.forms.charCount, {
                    count: value.length,
                    max: INTENTION_MAX,
                  })
                : waiting
                  ? t.composer.files.waiting
                  : null}
          </p>
        </div>
      </section>
    );
  }

  // Mockup 02: the question in a card — its spark, what to write, the box,
  // what to attach, the button to send — then « Suggestions pour vous », a
  // card each.
  return (
    <div className={cn("space-y-4", className)}>
      <section
        aria-labelledby={`${ids}-title`}
        className="rounded-xl border border-shell-line bg-white p-5"
      >
        <div className="mb-4 flex items-start gap-3">
          <IconTile icon={Sparkles} tone="violet" className="size-11" />
          <div className="min-w-0">
            <h2
              id={`${ids}-title`}
              className="text-[1.25rem] font-semibold tracking-[-0.01em] text-brand-navy"
            >
              {t.composer.question}
            </h2>
            <p className="text-[0.875rem] text-shell-muted">{t.composer.questionLead}</p>
          </div>
        </div>
        <div
          data-testid="composer-dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            files?.add(event.dataTransfer.files);
          }}
          className={cn(
            "rounded-xl border border-shell-line bg-white p-3 transition-colors focus-within:border-brand-violet focus-within:ring-3 focus-within:ring-brand-violet/20",
          )}
        >
          <Textarea
            ref={box}
            value={value}
            onChange={(event) => setValue(name, event.target.value, { shouldDirty: true })}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
              event.preventDefault();
              onSubmit();
            }}
            aria-label={t.composer.label}
            aria-keyshortcuts="Meta+Enter Control+Enter"
            placeholder={t.composer.placeholder}
            rows={compact ? 1 : 6}
            data-testid="intention-input"
            className={cn(
              "resize-none border-0 bg-transparent p-0 shadow-none focus-visible:ring-0",
              compact && "min-h-9",
            )}
          />

          {files ? <AttachmentList files={files} className="mt-2" /> : null}

          {/* Wraps as two groups rather than squeezing words: at 1024px, with
              the rail, "⌘↵ pour lancer" used to break over three lines. */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {compact ? null : (
              <>
                {files ? <AttachmentPicker files={files} /> : null}
                {/* Hidden outright where the browser could not do it anyway:
                    a permanently disabled button on a machine that will never
                    support it is a promise that cannot be kept. */}
                {dictatable ? (
                  <Button type="button" variant="ghost" size="sm" disabled={!DICTATION_ENABLED}>
                    <Mic className="size-4" aria-hidden="true" />
                    {t.composer.dictate}
                    <Badge variant="secondary">{t.composer.soon}</Badge>
                  </Button>
                ) : null}
              </>
            )}

            <div className="ms-auto flex items-center gap-2 whitespace-nowrap">
              {/* Polite, and only while it is true: announced once as the
                  person types past it, not read out on every keystroke. */}
              <span id={whyDisabled} aria-live="polite" className="text-xs text-shell-muted">
                {missing > 0
                  ? fill(t.composer.tooShortHint, { count: missing })
                  : waiting
                    ? t.composer.files.waiting
                    : null}
              </span>
              <span
                className={cn(
                  "text-xs tabular-nums",
                  tooLong ? "text-shell-badge-foreground" : "text-shell-muted",
                )}
              >
                {fill(t.forms.charCount, {
                  count: value.length,
                  max: INTENTION_MAX,
                })}
              </span>
              {missing > 0 ? null : (
                <span className="hidden text-xs text-shell-muted sm:inline">
                  {t.composer.submitHint}
                </span>
              )}
              <Button
                type="button"
                size="sm"
                onClick={onSubmit}
                // Below the minimum there is nothing to analyse, past the
                // maximum there is nothing we would send. Both are refusals the
                // person can see before pressing — and a file on its way.
                disabled={empty || tooLong || missing > 0 || submitting || waiting}
                aria-describedby={missing > 0 ? whyDisabled : undefined}
                data-testid="intention-submit"
              >
                <Send className="size-4" aria-hidden="true" />
                {submitLabel ?? t.composer.submit}
              </Button>
            </div>
          </div>
        </div>

      </section>

      {suggested ? (
        <section
          aria-labelledby={`${ids}-suggestions`}
          className="rounded-xl border border-shell-line bg-white p-4"
        >
          <h2
            id={`${ids}-suggestions`}
            className="mb-3 flex items-center gap-2 text-[1rem] font-semibold text-brand-navy"
          >
            <Sparkles className="size-4 text-brand-violet" aria-hidden="true" />
            {t.composer.suggestionsTitle}
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            {suggestions.map(({ icon, tone, label, hint, template }, index) => (
              <li key={label}>
                <button
                  type="button"
                  onClick={() => void applySuggestion(template)}
                  // Named by its label, described by its hint: a test, or a
                  // screen reader, finds « Analyser un incident récent ».
                  aria-labelledby={`${ids}-s${index}`}
                  aria-describedby={`${ids}-h${index}`}
                  className="group flex h-full w-full flex-col items-start gap-2 rounded-xl border border-shell-line bg-white p-4 text-start transition-colors outline-none hover:border-brand-violet/40 hover:bg-brand-violet-soft/30 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                >
                  <IconTile icon={icon} tone={tone} className="size-10" />
                  <span
                    id={`${ids}-s${index}`}
                    className="text-[0.875rem] font-semibold text-brand-navy"
                  >
                    {label}
                  </span>
                  <span className="flex w-full items-end gap-2">
                    <span
                      id={`${ids}-h${index}`}
                      className="min-w-0 flex-1 text-[0.8125rem] text-shell-muted"
                    >
                      {hint}
                    </span>
                    <ChevronRight
                      className="size-4 shrink-0 text-shell-muted transition-transform group-hover:translate-x-0.5 rtl:-scale-x-100"
                      aria-hidden="true"
                    />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
