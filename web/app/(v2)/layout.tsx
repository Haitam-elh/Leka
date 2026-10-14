"use client";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ShellProvider } from "@/components/shell/shell-provider";
import { WorkspaceGate } from "@/components/shell/workspace-gate";
import { Toaster } from "@/components/ui/toast";
import { V2Shell } from "@/components/v2/shell";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { QueryProvider } from "@/lib/query";

/**
 * The new interface (2026-10-14, the product call's Lot 6), at /v2: beside
 * the current one, so the two can be shown and compared; nothing of the
 * current one changes. The same session, the same workspace, the same API —
 * its own frame.
 */
export default function V2Layout({ children }: { children: React.ReactNode }) {
  const t = useDictionary();
  return (
    <QueryProvider>
      <ShellProvider>
        <Toaster closeLabel={t.interactions.dismiss} />
        <ConfirmProvider>
          <V2Shell>
            <WorkspaceGate>{children}</WorkspaceGate>
          </V2Shell>
        </ConfirmProvider>
      </ShellProvider>
    </QueryProvider>
  );
}
