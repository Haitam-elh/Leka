import { z } from "@/lib/validation";

/**
 * What an intention has to be before LEKA is asked to spend money on it.
 *
 * THE MINIMUM IS NOT ARBITRARY. An analysis reads repositories, tickets and
 * metrics; "slow?" gives it nothing to go on and produces an answer nobody
 * can act on. Ten characters is the shortest thing that can carry a subject
 * and a verb.
 *
 * THE MAXIMUM IS THE MOCKUP'S. Two thousand characters is the counter drawn
 * in "Nouvelle intention", and it is generous enough that nobody writing in
 * good faith meets it.
 */

export const INTENTION_MIN = 10;
export const INTENTION_MAX = 2000;

/** Just the text: what the compact composer on the overview validates. */
export const intentionDraftSchema = z.object({
  text: z.string().trim().min(INTENTION_MIN).max(INTENTION_MAX),
});

export type IntentionDraft = z.infer<typeof intentionDraftSchema>;

export const PERIOD_PRESETS = ["24h", "7d", "30d", "custom"] as const;

/**
 * The whole request: the text, what to read, and where to look.
 *
 * Sources cannot be empty. An analysis with nothing to read is not a
 * cheaper analysis, it is a guess — and the mockup ticks GitHub and Jira by
 * default precisely so that nobody has to think about it.
 */
export const intentionRequestSchema = z.object({
  text: z.string().trim().min(INTENTION_MIN).max(INTENTION_MAX),
  sources: z.array(z.string()).min(1),
  environment: z.string().min(1),
  period: z.object({
    preset: z.enum(PERIOD_PRESETS),
    range: z.object({ from: z.string(), to: z.string() }),
  }),
  /** Narrowing, not filtering: empty means "wherever it leads". */
  services: z.array(z.string()),
  /** Names only. The files themselves never reach the schema. */
  attachments: z.array(z.string()),
});

export type IntentionRequest = z.infer<typeof intentionRequestSchema>;
