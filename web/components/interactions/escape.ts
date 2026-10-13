import type React from "react";

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
