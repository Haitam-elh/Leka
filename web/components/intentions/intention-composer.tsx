"use client";

import { Mic, Paperclip, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { cn } from "cn";
import { useConfirm } from "@/components/interactions/confirm";
import { useCurrentWorkspace } from "@/components/shell/shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
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

/** Files a person can reasonably attach to a question about their systems. */
const ACCEPTED_TYPES = [
  "text/plain",
  "text/csv",
  "application/json",
  "application/pdf",
  "image/png",
  "image/jpeg",
] as const;

const MAX_FILE_MB = 10;

/** Dictation is designed and not built. The flag is what says so. */
const DICTATION_ENABLED = false;

export interface Attachment {
  name: string;
  /** Kept in memory only. TODO upload (S3/storage), see lib/intentions/api.ts. */
  file: File;
}

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
  attachments = [],
  onAttachmentsChange,
  onSubmit,
  submitting = false,
  className,
}: {
  /** The field in the surrounding form. */
  name?: string;
  variant?: "full" | "compact";
  attachments?: readonly Attachment[];
  onAttachmentsChange?: (next: Attachment[]) => void;
  onSubmit: () => void;
  submitting?: boolean;
  className?: string;
}) {
  const t = useDictionary();
  const confirm = useConfirm();
  const workspace = useCurrentWorkspace();
  const { setValue, getValues } = useFormContext();
  const value = (useWatch({ name }) as string | undefined) ?? "";
  const box = useRef<HTMLTextAreaElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
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
  const compact = variant === "compact";

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

  function addFiles(files: FileList | null) {
    if (files === null || onAttachmentsChange === undefined) return;
    const accepted: Attachment[] = [];

    for (const file of Array.from(files)) {
      if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
        notify.error({ title: fill(t.composer.fileTypeRefused, { name: file.name }) });
        continue;
      }
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        notify.error({ title: fill(t.composer.fileTooBig, { name: file.name, max: MAX_FILE_MB }) });
        continue;
      }
      accepted.push({ name: file.name, file });
    }

    if (accepted.length > 0) onAttachmentsChange([...attachments, ...accepted]);
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div
        data-testid="composer-dropzone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          addFiles(event.dataTransfer.files);
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

        {attachments.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {attachments.map((attachment) => (
              <li
                key={attachment.name}
                className="flex items-center gap-1 rounded-md bg-shell-canvas px-2 py-1 text-xs text-shell-nav"
              >
                {attachment.name}
                <button
                  type="button"
                  aria-label={fill(t.composer.removeFile, { name: attachment.name })}
                  onClick={() =>
                    onAttachmentsChange?.(
                      attachments.filter((current) => current.name !== attachment.name),
                    )
                  }
                  className="rounded p-0.5 opacity-60 outline-none hover:opacity-100 focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  <X className="size-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-2 flex items-center gap-2">
          {compact ? null : (
            <>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept={ACCEPTED_TYPES.join(",")}
                className="hidden"
                onChange={(event) => {
                  addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => fileInput.current?.click()}
              >
                <Paperclip className="size-4" aria-hidden="true" />
                {t.composer.attach}
              </Button>
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

          <span className="flex-1" />

          <span
            className={cn(
              "text-xs tabular-nums",
              tooLong ? "text-shell-badge-foreground" : "text-shell-muted",
            )}
          >
            {fill(t.forms.charCount, { count: value.length, max: INTENTION_MAX })}
          </span>
          <span className="hidden text-xs text-shell-muted sm:inline">{t.composer.submitHint}</span>
          <Button
            type="button"
            size="sm"
            onClick={onSubmit}
            // Below the minimum there is nothing to analyse, past the
            // maximum there is nothing we would send. Both are refusals the
            // person can see before pressing.
            disabled={empty || tooLong || value.trim().length < INTENTION_MIN || submitting}
            data-testid="intention-submit"
          >
            <Send className="size-4" aria-hidden="true" />
            {t.composer.submit}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-shell-muted">{t.composer.suggestions}</span>
        {[
          { label: t.composer.suggestIncident, template: t.composer.suggestIncidentTemplate },
          { label: t.composer.suggestChange, template: t.composer.suggestChangeTemplate },
          { label: t.composer.suggestRisk, template: t.composer.suggestRiskTemplate },
        ].map((suggestion) => (
          <Button
            key={suggestion.label}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void applySuggestion(suggestion.template)}
          >
            {suggestion.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
