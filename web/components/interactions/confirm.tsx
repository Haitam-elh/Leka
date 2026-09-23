"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Asking before doing, without a piece of state per question.
 *
 * WHY IMPERATIVE. The usual shape — an `open` state, the pending action in
 * another state, an `onConfirm` that reads it — is four lines of wiring at
 * every call site, and each copy is a chance to forget one. `await
 * confirm({…})` reads the way the code means it: stop here, ask, carry on
 * if they said yes.
 *
 * ONE DIALOG, AT THE LAYOUT. Rendered once, so two confirmations cannot be
 * on screen together and the focus trap has a single owner.
 *
 * THE BUTTON SAYS WHAT IT DOES. "OK" confirms nothing. Someone who reads
 * only the buttons — which is most people, most of the time — learns what
 * is about to happen from "Lancer l'analyse" and nothing at all from
 * "Oui". The title asks the question, the description gives the
 * consequence, the button is the verb.
 */

export interface ConfirmOptions {
  title: string;
  /** One sentence: what happens if they go ahead. */
  description?: string;
  /** The verb. Never "OK", never "Oui". */
  confirmLabel: string;
  cancelLabel?: string;
  /** Red button, focus on Cancel, impact shown. For anything hard to undo. */
  destructive?: boolean;
  /** Lines like "3 services concernés · Rollback disponible". */
  impact?: readonly string[];
  /**
   * The exact text to type before the action can be confirmed.
   *
   * For the few things that cannot be undone at all — deleting a workspace,
   * removing a source and its history. Anything less and it is friction
   * dressed as safety, which teaches people to type past it.
   */
  requireTypedConfirmation?: string;
}

type Ask = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Ask | null>(null);

/** `const confirm = useConfirm(); if (await confirm({…})) …` */
export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext);
  if (ask === null) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return ask;
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const t = useDictionary();
  const [pending, setPending] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState("");
  const settle = useRef<((confirmed: boolean) => void) | null>(null);
  /**
   * Whatever had the keyboard when the question was asked.
   *
   * A dialog opened from a trigger element gets this for free; one opened
   * by calling a function has no trigger to hand it back to, and focus
   * lands on the document — which for anyone using a keyboard means
   * starting again from the top of the page.
   */
  const opener = useRef<HTMLElement | null>(null);

  const ask = useCallback<Ask>((options) => {
    opener.current = document.activeElement as HTMLElement | null;
    setTyped("");
    setPending(options);
    return new Promise<boolean>((resolve) => {
      settle.current = resolve;
    });
  }, []);

  function close(confirmed: boolean) {
    settle.current?.(confirmed);
    settle.current = null;
    setPending(null);
  }

  const needsTyping = pending?.requireTypedConfirmation;
  const blocked = needsTyping !== undefined && typed.trim() !== needsTyping;

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      <AlertDialog
        open={pending !== null}
        // Escape and the overlay both mean cancel. A dialog that closes
        // without answering leaves the promise pending for ever, and the
        // screen that awaited it never moves again.
        onOpenChange={(open) => {
          if (!open) close(false);
        }}
      >
        {pending ? (
          <AlertDialogContent finalFocus={opener}>
            <AlertDialogHeader>
              <AlertDialogTitle>{pending.title}</AlertDialogTitle>
              {pending.description ? (
                <AlertDialogDescription>{pending.description}</AlertDialogDescription>
              ) : null}
            </AlertDialogHeader>

            {pending.impact && pending.impact.length > 0 ? (
              <div className="rounded-lg bg-shell-canvas p-3">
                <p className="text-xs font-medium text-shell-muted">{t.interactions.impactTitle}</p>
                <ul className="mt-1 space-y-0.5">
                  {pending.impact.map((line) => (
                    <li key={line} className="text-sm text-shell-nav">
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {needsTyping ? (
              <label className="block space-y-1.5">
                <span className="text-sm text-shell-nav">
                  {fill(t.interactions.typeToConfirm, { name: needsTyping })}
                </span>
                <Input
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                  autoComplete="off"
                />
              </label>
            ) : null}

            <AlertDialogFooter>
              {/* Focus starts here when the action is destructive: the
                  dangerous button must not be one stray Enter away. */}
              <AlertDialogCancel autoFocus={pending.destructive} onClick={() => close(false)}>
                {pending.cancelLabel ?? t.interactions.cancel}
              </AlertDialogCancel>
              <AlertDialogAction
                autoFocus={!pending.destructive}
                disabled={blocked}
                variant={pending.destructive ? "destructive" : "default"}
                onClick={() => close(true)}
              >
                {pending.confirmLabel}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        ) : null}
      </AlertDialog>
    </ConfirmContext.Provider>
  );
}
