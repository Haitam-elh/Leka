"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether the browser believes it has a network connection.
 *
 * "Believes": `navigator.onLine` is false only when there is certainly no
 * connection — no network interface, airplane mode, a cable pulled. It can
 * be true on a captive portal or behind a dead router. So `false` is a fact
 * worth telling someone, and `true` is not a promise; a request that fails
 * while this says true is classified by what the request said.
 *
 * Online on the server, and on the first render in the browser: the HTML
 * the server sent was built without knowing, and assuming the worst would
 * flash an offline banner at everyone on every page load.
 */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribe, readOnline, () => true);
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

function readOnline(): boolean {
  return navigator.onLine;
}
