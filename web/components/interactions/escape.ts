import type React from "react";
import { useEffect, useRef } from "react";

/**
 * A detail panel beside a list closes on Escape as its ✕ does (LEKA-438),
 * from wherever the focus is inside it. What handled Escape first — a menu,
 * a select open in the panel — keeps it: its event comes defaultPrevented.
 */
export function closeOnEscape(close: () => void) {
  return (event: React.KeyboardEvent) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    close();
  };
}

/**
 * When the panel closes — Escape or ✕ — the focus goes back to what opened
 * it, the row of the list, instead of falling to the page's top. `opened`
 * is what the panel shows: another row opened in the same panel is the one
 * the focus goes back to.
 */
export function useReturnFocus(opened: unknown) {
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body) opener.current = active;
  }, [opened]);
  useEffect(
    () => () => {
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );
}
