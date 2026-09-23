import type { IntentionRequest } from "@/lib/validation/intentions";

/**
 * Submitting an intention — the shape of it, not the thing.
 *
 * There is no endpoint yet: LEKA-384 builds the pipeline this feeds. What
 * exists here is the signature every screen will keep using, so that the
 * day it becomes an apiFetch call nothing above it changes.
 *
 * It is deliberately a function that takes time and can fail, rather than
 * one that returns instantly. A submit path that has never waited has never
 * had its loading state looked at, and a submit path that has never failed
 * has never had its error state looked at either.
 *
 * TODO LEKA-384: replace the body with
 * `apiFetch<IntentionRead>("/intentions", { method: "POST", body })`.
 * TODO: attachments are names here. Uploading them is a separate call to
 * object storage, and the request should carry the ids it returns.
 */

/** Long enough to see the button change, short enough not to annoy. */
const MOCK_DELAY_MS = 900;

export interface SubmittedIntention {
  id: string;
}

export async function submitIntention(request: IntentionRequest): Promise<SubmittedIntention> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  // Not a random id: a stable one makes the mocked step 2 addressable, and
  // a test can assert where it landed.
  return { id: `draft-${request.text.length}` };
}
