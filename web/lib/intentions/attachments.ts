import { apiAddress, apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

/**
 * Files attached to an intention: uploaded on their own, before it is asked,
 * their ids then carried by the intention (leka.intentions.attachments).
 *
 * What LEKA reads, the server says the same: text, CSV, Markdown, JSON,
 * PDF, PNG, JPEG — ten megabytes each, five to an intention. The server
 * also reads what the bytes are; the screen says it first, so a file is
 * refused before it travels.
 */

export type IntentionAttachment = components["schemas"]["IntentionAttachmentRead"];

export const MAX_BYTES = 10 * 1024 * 1024;
export const MAX_FILES = 5;

/** A file's extension, and the type it is sent as. */
const BY_EXTENSION: Record<string, string> = {
  txt: "text/plain",
  csv: "text/csv",
  md: "text/markdown",
  markdown: "text/markdown",
  json: "application/json",
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
};
const ACCEPTED_TYPES = new Set(Object.values(BY_EXTENSION));

/** What the file picker offers: the types, and the extensions a browser
 * gives no type for (a Markdown file often comes with none). */
export const ACCEPT = [...ACCEPTED_TYPES, ...Object.keys(BY_EXTENSION).map((e) => `.${e}`)].join(",");

/** The type a file is sent as: the browser's when LEKA reads it, else its
 * extension's — the server judges its bytes either way. None: not a file
 * LEKA reads. */
export function mediaOf(file: Pick<File, "name" | "type">): string | null {
  const said = file.type.split(";")[0]?.trim().toLowerCase() ?? "";
  if (ACCEPTED_TYPES.has(said)) return said;
  const extension = file.name.includes(".") ? (file.name.split(".").pop() ?? "").toLowerCase() : "";
  return BY_EXTENSION[extension] ?? null;
}

/** A file kept, its id answered — refused, an ApiError whose field `file`
 * says why (file_type_refused, file_content_mismatch, file_too_large,
 * file_empty). */
export function uploadAttachment(
  file: File,
  media: string,
  signal?: AbortSignal,
): Promise<IntentionAttachment> {
  return apiFetch<IntentionAttachment>("/intentions/attachments", {
    method: "POST",
    body: file,
    signal,
    headers: { "Content-Type": media, "X-File-Name": encodeURIComponent(file.name) },
  });
}

/** One's own file, removed before asking. */
export function removeAttachment(id: string): Promise<void> {
  return apiFetch<void>(`/intentions/attachments/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Where an attached file is read, for whoever reads its intention. */
export function attachmentAddress(intentionId: string, attachmentId: string): string {
  return apiAddress(`/intentions/${intentionId}/attachments/${attachmentId}`);
}
