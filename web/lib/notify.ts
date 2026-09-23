import { toast } from "@/components/ui/toast";

/**
 * Telling someone what happened, after the fact.
 *
 * WHICH CHANNEL. A toast is for the result of something asynchronous the
 * person set off and then stopped watching. It is not for a bad value —
 * that belongs on the field, where the correction happens — nor for a
 * refusal that blocks a form, which belongs at the top of it, nor for the
 * state of a whole page, which is RouteState from LEKA-338. A toast that
 * carries any of those is a message that disappears before it is read.
 *
 * HOW LONG. A success goes on its own: it confirms something the person
 * already believes happened, and making them dismiss it is a click for
 * nothing. An error stays until it is dismissed, because a message that
 * leaves on its own takes the only account of the failure with it.
 *
 * The text comes from the caller, which reads it from the dictionary. This
 * module is not a React component and has no locale of its own; giving it
 * one would be a second source of truth for the language in use.
 */

/** Long enough to read twice, short enough not to sit in the corner. */
const SUCCESS_MS = 5_000;

export interface NotifyOptions {
  title: string;
  description?: string;
  /** One way forward: "Voir l'intention", "Annuler". */
  action?: { label: string; onClick: () => void };
}

function add(type: "success" | "error" | "info", { title, description, action }: NotifyOptions) {
  toast.add({
    title,
    description,
    type,
    timeout: type === "error" ? 0 : SUCCESS_MS,
    actionProps: action
      ? { children: action.label, onClick: action.onClick }
      : undefined,
  });
}

export const notify = {
  success: (options: NotifyOptions) => add("success", options),
  error: (options: NotifyOptions) => add("error", options),
  info: (options: NotifyOptions) => add("info", options),
};
