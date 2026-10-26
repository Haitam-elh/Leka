"use client";

/**
 * The demonstration (LEKA-449): opened from the welcome screen or the first
 * steps, said on every page while one is in it, left in one click.
 *
 * Nova Retail is a workspace of the person's own, marked a demonstration by
 * the API (`demo`), whose data is fictive and whose sources reach nothing:
 * this only opens it, says so, and leaves it.
 */

import { FlaskConical } from "lucide-react";
import { useState } from "react";

import { useCurrentWorkspace, useWorkspaces } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { useEnterprise } from "@/lib/contract";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { workspace } from "@/lib/workspace";

/** Open my demonstration — afresh when asked — and go to its overview,
 * the whole page drawn again: everything shown is now Nova Retail's. */
function useOpenDemo(): { open: (fresh?: boolean) => Promise<void>; busy: boolean; failed: boolean } {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  async function open(fresh = false) {
    setBusy(true);
    setFailed(false);
    try {
      await workspace.openDemo(fresh);
      window.location.assign(routes.overview());
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }
  return { open, busy, failed };
}

export function ExploreDemoButton({ variant = "outline" }: { variant?: "default" | "outline" }) {
  const t = useDictionary();
  const { open, busy, failed } = useOpenDemo();
  // A customer's own organisation (2026-10-25): its data only, no demonstration.
  const enterprise = useEnterprise();
  if (enterprise) return null;
  return (
    <span className="inline-flex flex-col gap-1">
      <Button
        type="button"
        variant={variant}
        disabled={busy}
        onClick={() => void open()}
        data-testid="explore-demo"
      >
        <FlaskConical aria-hidden="true" />
        {busy ? t.demo.opening : t.demo.explore}
      </Button>
      {failed ? (
        <span role="alert" className="text-xs text-state-danger">
          {t.demo.failed}
        </span>
      ) : null}
    </span>
  );
}

/** Said on every page of a demonstration: fictive, reaches nothing — and
 * the way out, to one's own workspace or to connecting one's tools. */
export function DemoBanner() {
  const t = useDictionary();
  const current = useCurrentWorkspace();
  const workspaces = useWorkspaces();
  const { open, busy } = useOpenDemo();
  const [leaving, setLeaving] = useState(false);
  if (!current?.demo) return null;
  const mine = workspaces.find((w) => !w.demo);

  async function leave(to: string) {
    if (!mine) return;
    setLeaving(true);
    try {
      await workspace.enter(mine.id);
      // Drawn again from the start: nothing of Nova Retail's stays on screen.
      window.location.assign(to);
    } catch {
      setLeaving(false);
    }
  }

  return (
    <div
      role="status"
      data-testid="demo-banner"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-brand-violet/30 bg-brand-violet-soft px-4 py-2 text-[0.8125rem] text-brand-navy sm:px-6 lg:px-8"
    >
      <FlaskConical className="size-4 shrink-0 text-brand-violet" aria-hidden="true" />
      <p className="min-w-0 flex-1">{t.demo.banner}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void open(true)}>
          {t.demo.restart}
        </Button>
        {mine ? (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={leaving}
              onClick={() => void leave(routes.welcome())}
            >
              {t.demo.connect}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={leaving}
              onClick={() => void leave(routes.overview())}
              data-testid="leave-demo"
            >
              {t.demo.leave}
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}
