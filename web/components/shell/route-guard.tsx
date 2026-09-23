"use client";

import { usePathname } from "next/navigation";

import { PageContainer } from "@/components/shell/page-container";
import { RouteState } from "@/components/shell/route-state";
import { usePermissions } from "@/components/shell/shell-provider";
import { canOpen } from "@/lib/navigation/access";
import { matchRoute } from "@/lib/navigation/active";

/**
 * Stands between the shell and every page inside it.
 *
 * Someone who types the address of a page their role does not open sees the
 * refusal, in the shell, with a way out — not a 404 that suggests the page
 * does not exist, and not a silent redirect that suggests they misclicked.
 *
 * It is a courtesy, not a defence: the data lives behind the API, which
 * checks the same permission and refuses regardless of what this renders.
 */
export function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const permissions = usePermissions();
  const match = matchRoute(pathname);

  // An unknown address is the catch-all page's business, not this one's.
  if (match !== undefined && !canOpen(match.route, permissions)) {
    return (
      <PageContainer>
        <RouteState variant="forbidden" />
      </PageContainer>
    );
  }

  return <>{children}</>;
}
