"use client";

import { useEffect } from "react";

import { useConfirm } from "@/components/interactions/confirm";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Stops a half-filled form from disappearing on a misclick.
 *
 * TWO EXITS, TWO MECHANISMS. Closing the tab is the browser's to refuse,
 * and it only listens to `beforeunload` — which cannot be customised, so
 * the wording there is the browser's own. Clicking a link inside the app is
 * ours, and that one gets the real question.
 *
 * WHY LINK CLICKS RATHER THAN A ROUTER HOOK. The App Router has no
 * navigation blocker; `useRouter` offers no way to refuse a push. So the
 * guard listens for clicks on anchors during the capture phase, before
 * Next's own handler sees them, asks, and re-issues the navigation if the
 * answer is yes. It covers the way people actually leave a page — the
 * sidebar, the breadcrumb, a card — and it does not cover a programmatic
 * `router.push`, which a screen chooses deliberately and can ask for
 * itself. TODO: revisit if Next grows a blocker.
 */
export function useUnsavedChangesGuard(isDirty: boolean): void {
  const t = useDictionary();
  const confirm = useConfirm();

  useEffect(() => {
    if (!isDirty) return;

    function onBeforeUnload(event: BeforeUnloadEvent) {
      // Setting returnValue is what asks the browser to prompt; the string
      // is ignored by every current browser, which show their own wording.
      event.preventDefault();
      event.returnValue = "";
    }

    function onClick(event: MouseEvent) {
      // A modified click opens elsewhere and leaves this page alone.
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const anchor = (event.target as HTMLElement | null)?.closest("a");
      const href = anchor?.getAttribute("href");
      if (!anchor || !href || href.startsWith("#")) return;
      if (anchor.target === "_blank") return;
      // Another origin is a real page load, which beforeunload already
      // covers. Asking twice is worse than asking once.
      if (new URL(anchor.href, window.location.href).origin !== window.location.origin) return;

      event.preventDefault();
      event.stopPropagation();
      void confirm({
        title: t.forms.unsavedTitle,
        description: t.forms.unsavedBody,
        confirmLabel: t.forms.unsavedLeave,
        cancelLabel: t.forms.unsavedStay,
      }).then((leave) => {
        // The guard is gone by then — it only runs while the form is dirty
        // — so a plain navigation is enough and cannot ask again.
        if (leave) window.location.assign(anchor.href);
      });
    }

    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [isDirty, confirm, t]);
}
