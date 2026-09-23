"use client";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { AppShell } from "@/components/shell/app-shell";
import { DocumentTitle } from "@/components/shell/document-title";
import { RouteGuard } from "@/components/shell/route-guard";
import { useNavBadges } from "@/lib/nav-badges";
import { ShellProvider } from "@/components/shell/shell-provider";
import { Toaster } from "@/components/ui/toast";

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
  const badges = useNavBadges();

  return (
    <ShellProvider>
      {/* Both mounted once, here, for the same reason: a second toast
          viewport competes for the same corner, and a second confirm
          dialog means two focus traps fighting over the keyboard. */}
      <Toaster />
      <DocumentTitle />
      {/* TODO LEKA-390 for the counts, and notifications have no ticket yet:
          the shell is handed numbers rather than asking for them. */}
      <ConfirmProvider>
        <AppShell badges={badges} notificationCount={1}>
          <RouteGuard>{children}</RouteGuard>
        </AppShell>
      </ConfirmProvider>
    </ShellProvider>
  );
}
