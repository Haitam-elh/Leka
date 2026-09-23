import { installValidationMessages } from "@/lib/validation/messages";

/**
 * The door every schema comes through.
 *
 * Importing this installs the error map (lib/validation/messages.ts) as a
 * side effect, which is why schemas import `z` from here rather than from
 * "zod" directly: a schema parsed before the map is installed produces
 * English sentences from the library, and the bug shows up as one screen
 * out of twenty speaking the wrong language.
 */
installValidationMessages();

export { z } from "zod";
export { resolveValidationMessage } from "@/lib/validation/messages";
