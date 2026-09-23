import { z } from "zod";

import { type Dictionary, fill } from "@/lib/i18n/dictionaries";

/**
 * One wording per rule, for the whole product.
 *
 * THE PROBLEM THIS SOLVES. A message written at the schema — `z.string()
 * .min(10, "Au moins 10 caractères")` — is a French sentence compiled into
 * a validation rule. It cannot be translated, it drifts from the next
 * schema that says the same thing differently, and it puts copy in a file
 * nobody reads for copy.
 *
 * SO THE MAP EMITS A KEY, NOT A SENTENCE. zod produces
 * `leka.validation:tooShortString:{"min":10}`, and the field resolves it
 * against the dictionary of the language in use, at render. The same rule
 * then reads the same way on every screen, in both languages, and a new
 * language is a translation rather than a sweep through the schemas.
 *
 * Anything that does not carry the prefix passes through untouched: that is
 * how a sentence from the API, or a deliberate one-off on a `.refine()`,
 * still reaches the person unchanged.
 */

const PREFIX = "leka.validation:";

type ValidationKey = keyof Dictionary["validation"];

type Params = Record<string, string | number>;

function encode(key: ValidationKey, params: Params = {}): string {
  return `${PREFIX}${key}:${JSON.stringify(params)}`;
}

/** Turn what zod produced into what this person reads. */
export function resolveValidationMessage(t: Dictionary, message: string): string {
  if (!message.startsWith(PREFIX)) return message;

  const rest = message.slice(PREFIX.length);
  const separator = rest.indexOf(":");
  if (separator === -1) return t.validation.invalid;

  const key = rest.slice(0, separator) as ValidationKey;
  const template = t.validation[key];
  if (template === undefined) return t.validation.invalid;

  try {
    return fill(template, JSON.parse(rest.slice(separator + 1)) as Params);
  } catch {
    // A message that cannot be read is still a message: say something
    // useful rather than print the encoding at someone.
    return t.validation.invalid;
  }
}

/**
 * Install the map globally.
 *
 * Called at import time by lib/validation/index.ts, which every schema goes
 * through, so no schema can be parsed before it is in place.
 */
export function installValidationMessages(): void {
  z.config({
    customError: (issue) => {
      switch (issue.code) {
        case "invalid_type":
          // The only type error a form can produce: the control handed over
          // undefined because nothing was filled in. "Expected string,
          // received undefined" is true and useless.
          return encode("required");

        case "too_small": {
          const min = Number(issue.minimum);
          // A minimum of one is not a length rule, it is emptiness — and
          // "at least 1 character" is a strange way to say "fill this in".
          if (min <= 1) return encode("required");
          if (issue.origin === "string") return encode("tooShortString", { min });
          if (issue.origin === "array" || issue.origin === "set")
            return encode("tooFewItems", { min });
          return encode("tooSmallNumber", { min });
        }

        case "too_big": {
          const max = Number(issue.maximum);
          if (issue.origin === "string") return encode("tooLongString", { max });
          if (issue.origin === "array" || issue.origin === "set")
            return encode("tooManyItems", { max });
          return encode("tooBigNumber", { max });
        }

        case "invalid_format":
          if (issue.format === "email") return encode("email");
          if (issue.format === "url") return encode("url");
          return encode("invalidFormat");

        default:
          return encode("invalid");
      }
    },
  });
}
