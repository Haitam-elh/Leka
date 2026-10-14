/** Between two things said in one exchange (2026-10-14, the new home): the
 * request, then each detail given — kept in the intention's own words, read
 * back as a thread. */
export const SAID = "\n\n";

/** What was said, in the order it was: the request, then each detail. */
export function splitSaid(text: string): string[] {
  return text
    .split(SAID)
    .map((part) => part.trim())
    .filter(Boolean);
}
