"use client";

import {
  CircleAlert,
  CircleCheck,
  FileText,
  ImageIcon,
  LoaderCircle,
  Paperclip,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  ACCEPT,
  MAX_BYTES,
  MAX_FILES,
  mediaOf,
  removeAttachment,
  uploadAttachment,
} from "@/lib/intentions/attachments";

/**
 * The files of an intention being written — the home's paperclip and the
 * full step's: each sent as soon as it is chosen, shown with its name, its
 * type, its size and where it stands — on its way, kept, refused and why,
 * failed and tried again — and removable until the intention is asked.
 *
 * Only a file the server kept is said attached, and only its id goes with
 * the intention. Nothing is asked while one is on its way. A failure keeps
 * the words and the other files: tried again, it is sent again.
 */

export type AttachmentStatus = "uploading" | "kept" | "failed" | "refused";

export type AttachmentItem = {
  key: string;
  file: File;
  name: string;
  media: string | null;
  size: number;
  status: AttachmentStatus;
  /** The server's id, once kept. */
  id?: string;
  /** Why it failed or was refused: a code said in words below. */
  error?: string;
};

export type Attachments = {
  items: readonly AttachmentItem[];
  add: (files: FileList | readonly File[]) => void;
  remove: (key: string) => void;
  retry: (key: string) => void;
  /** A file still on its way: nothing is asked meanwhile. */
  uploading: boolean;
  /** The files kept — the only ones said attached. */
  ids: string[];
  /** Asked: the files are the intention's now. */
  clear: () => void;
};

/** A file's size, in the reader's words: « 12,3 ko », « 1,2 Mo ». */
export function sizeOf(bytes: number, format: string): string {
  const mega = bytes >= 1024 * 1024;
  return new Intl.NumberFormat(format, {
    style: "unit",
    unit: mega ? "megabyte" : "kilobyte",
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(mega ? bytes / (1024 * 1024) : Math.max(bytes / 1024, 0.1));
}

/** What can be tried again: the network, the server — never a refusal,
 * which the same file would meet again. */
const RETRYABLE = new Set(["network", "server"]);

function codeOf(error: unknown): string {
  if (error instanceof ApiError) {
    const said = error.fieldErrors?.file;
    if (said) return said;
    if (error.status === 0) return "network";
    if (error.status === 413) return "file_too_large";
    if (error.status === 415) return "file_type_refused";
  }
  return "server";
}

export function useAttachments(): Attachments {
  // The list lives in a ref, changed at once; the state only redraws. An
  // upload's answer and a removal never race over a stale copy.
  const list = useRef<AttachmentItem[]>([]);
  const [version, setVersion] = useState(0);
  const controllers = useRef(new Map<string, AbortController>());

  const commit = useCallback((next: AttachmentItem[]) => {
    list.current = next;
    setVersion((v) => v + 1);
  }, []);

  const patch = useCallback(
    (key: string, change: Partial<AttachmentItem>) => {
      if (!list.current.some((item) => item.key === key)) return;
      commit(list.current.map((item) => (item.key === key ? { ...item, ...change } : item)));
    },
    [commit],
  );

  const send = useCallback(
    (item: AttachmentItem) => {
      if (!item.media) return;
      const controller = new AbortController();
      controllers.current.set(item.key, controller);
      uploadAttachment(item.file, item.media, controller.signal)
        .then(
          (kept) => {
            if (!controller.signal.aborted) patch(item.key, { status: "kept", id: kept.id, error: undefined });
          },
          (error: unknown) => {
            if (!controller.signal.aborted) patch(item.key, { status: "failed", error: codeOf(error) });
          },
        )
        .finally(() => controllers.current.delete(item.key));
    },
    [patch],
  );

  const add = useCallback(
    (files: FileList | readonly File[]) => {
      let room = MAX_FILES - list.current.filter((item) => item.status !== "refused").length;
      const added: AttachmentItem[] = [];
      for (const file of Array.from(files)) {
        const media = mediaOf(file);
        const base: AttachmentItem = {
          key: crypto.randomUUID(),
          file,
          name: file.name,
          media,
          size: file.size,
          status: "uploading",
        };
        // Refused here, before it travels — the server would say the same.
        const refused = !media
          ? "file_type_refused"
          : file.size > MAX_BYTES
            ? "file_too_large"
            : file.size === 0
              ? "file_empty"
              : room <= 0
                ? "too_many"
                : null;
        if (refused) {
          added.push({ ...base, status: "refused", error: refused });
          continue;
        }
        room -= 1;
        added.push(base);
      }
      commit([...list.current, ...added]);
      for (const item of added) if (item.status === "uploading") send(item);
    },
    [commit, send],
  );

  const remove = useCallback(
    (key: string) => {
      const item = list.current.find((one) => one.key === key);
      if (!item) return;
      controllers.current.get(key)?.abort();
      // Kept and not asked with: removed on the server too. Should that
      // fail, nobody's file is purged within a day.
      if (item.status === "kept" && item.id) void removeAttachment(item.id).catch(() => undefined);
      commit(list.current.filter((one) => one.key !== key));
    },
    [commit],
  );

  const retry = useCallback(
    (key: string) => {
      const item = list.current.find((one) => one.key === key);
      if (!item || item.status !== "failed" || !RETRYABLE.has(item.error ?? "")) return;
      const again = { ...item, status: "uploading" as const, error: undefined };
      commit(list.current.map((one) => (one.key === key ? again : one)));
      send(again);
    },
    [commit, send],
  );

  const clear = useCallback(() => commit([]), [commit]);

  // Leaving the page mid-way: what was on its way is let go.
  useEffect(() => {
    const running = controllers.current;
    return () => {
      for (const controller of running.values()) controller.abort();
    };
  }, []);

  return useMemo(() => {
    const items = list.current;
    return {
      items,
      add,
      remove,
      retry,
      clear,
      uploading: items.some((item) => item.status === "uploading"),
      ids: items.filter((item) => item.status === "kept" && item.id).map((item) => item.id as string),
    };
    // `version` redraws: the list itself is the ref's.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, add, remove, retry, clear]);
}

/** The paperclip: opens the file picker — a real button, by mouse or by
 * keyboard. */
export function AttachmentPicker({ files, compact = false }: { files: Attachments; compact?: boolean }) {
  const t = useDictionary();
  const input = useRef<HTMLInputElement | null>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="attachment-input"
        onChange={(event) => {
          if (event.target.files) files.add(event.target.files);
          // The same file chosen again is a choice again.
          event.target.value = "";
        }}
      />
      {compact ? (
        <button
          type="button"
          onClick={() => input.current?.click()}
          aria-label={t.composer.attach}
          title={t.composer.attach}
          className="rounded p-1 text-shell-icon outline-none hover:text-shell-nav-active focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          data-testid="attachment-pick"
        >
          <Paperclip className="size-[18px]" aria-hidden="true" />
        </button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => input.current?.click()}
          data-testid="attachment-pick"
        >
          <Paperclip className="size-4" aria-hidden="true" />
          {t.composer.attach}
        </Button>
      )}
    </>
  );
}

/** The files chosen: each its name, type, size and where it stands. */
export function AttachmentList({ files, className }: { files: Attachments; className?: string }) {
  const t = useDictionary();
  const w = t.composer.files;
  const { format } = useLocale();
  if (!files.items.length) return null;
  const kinds = w.kinds as Record<string, string>;
  const errors = w.errors as Record<string, string>;
  const size = (bytes: number) => sizeOf(bytes, format);
  return (
    <ul className={cn("flex flex-wrap gap-2", className)} aria-label={w.label} data-testid="attachments">
      {files.items.map((item) => {
        const failed = item.status === "failed" || item.status === "refused";
        const Icon = item.media?.startsWith("image/") ? ImageIcon : FileText;
        return (
          <li
            key={item.key}
            className={cn(
              "flex max-w-full min-w-0 items-center gap-2 rounded-lg border bg-white px-2.5 py-1.5 text-xs",
              failed ? "border-state-danger/40" : "border-shell-line",
            )}
            data-testid="attachment"
            data-status={item.status}
          >
            <Icon className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
            <span className="min-w-0">
              <span className="block max-w-[14rem] truncate font-medium text-brand-navy" title={item.name}>
                {item.name}
              </span>
              <span className="block text-shell-muted">
                {(item.media && kinds[item.media]) || w.unknownKind} · {size(item.size)}
              </span>
            </span>
            {/* Where it stands, said to whoever does not see it change. */}
            <span className="flex items-center gap-1" role="status">
              {item.status === "uploading" ? (
                <>
                  <LoaderCircle className="size-3.5 animate-spin text-brand-violet motion-reduce:animate-none" aria-hidden="true" />
                  <span className="text-shell-muted">{w.uploading}</span>
                </>
              ) : item.status === "kept" ? (
                <>
                  <CircleCheck className="size-3.5 text-state-success" aria-hidden="true" />
                  <span className="sr-only">{w.kept}</span>
                </>
              ) : (
                <>
                  <CircleAlert className="size-3.5 shrink-0 text-state-danger" aria-hidden="true" />
                  <span className="text-state-danger" data-testid="attachment-error">
                    {errors[item.error ?? "server"] ?? errors.server}
                  </span>
                </>
              )}
            </span>
            {item.status === "failed" && RETRYABLE.has(item.error ?? "") ? (
              <button
                type="button"
                onClick={() => files.retry(item.key)}
                className="inline-flex items-center gap-1 rounded px-1 font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                data-testid="attachment-retry"
              >
                <RotateCw className="size-3" aria-hidden="true" />
                {w.retry}
              </button>
            ) : null}
            <button
              type="button"
              aria-label={fill(t.composer.removeFile, { name: item.name })}
              onClick={() => files.remove(item.key)}
              className="rounded p-0.5 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              data-testid="attachment-remove"
            >
              <X className="size-3.5" aria-hidden="true" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
