"use client";

import { AppShell } from "@/components/shell/app-shell";
import { ShellProvider } from "@/components/shell/shell-provider";

/**
 * Everything behind the sign-in page.
 *
 * The route group is what separates the two worlds: pages under (app) get
 * the shell and the session check, the ones under (auth) get neither — a
 * sidebar on the login screen would be a sidebar for someone with no
 * workspace to navigate.
 *
 * The session is checked HERE, once, rather than in each page. Before this,
 * app/page.tsx did it for itself; the twelfth page to copy that would have
 * been the first to forget it.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ShellProvider>
      {/* TODO LEKA-338: real counts. The mockup shows three decisions waiting
          and one unread notification; until the features that produce those
          numbers exist, the shell is handed them. */}
      <AppShell badges={{ approvals: 3 }} notificationCount={1}>
        {children}
      </AppShell>
    </ShellProvider>
  );
}
