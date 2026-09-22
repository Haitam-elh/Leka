"use client";

import { usePathname } from "next/navigation";

import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { RouteState } from "@/components/shell/route-state";
import { RouteTabs } from "@/components/shell/route-tabs";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { matchRoute } from "@/lib/navigation/active";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A page with nothing in it yet, described entirely by the registry.
 *
 * Every screen of the product is one of these until the ticket that owns it
 * arrives. They are what proves the frame: the same shell, the right entry
 * marked, the right trail, the right tabs and the right title on every
 * route — including the dynamic ones, which print the identifier they were
 * handed so a link can be checked before the real page exists.
 *
 * A page whose feature is not built says so, with the state that fits:
 * "bientôt" for what is coming, a lock for what a plan includes.
 */
export function PlaceholderPage() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const match = matchRoute(pathname);

  if (match === undefined) {
    return (
      <PageContainer>
        <RouteState variant="not-found" />
      </PageContainer>
    );
  }

  const { route, params } = match;
  const crumbs = buildBreadcrumb(pathname, t);
  const parameters = Object.entries(params);
  const title = crumbs.at(-1)?.label ?? t.nav[route.labelKey];

  return (
    <PageContainer>
      <PageHeader title={title} breadcrumb={crumbs} />
      <RouteTabs />

      {route.availability === "soon" && <RouteState variant="unavailable" />}
      {route.availability === "plan-gated" && <RouteState variant="plan-gated" />}

      {(route.availability ?? "available") === "available" && (
        <>
          <p className="text-sm text-shell-muted">{t.shell.emptyPage}</p>
          {parameters.length > 0 && (
            <dl className="mt-4 grid max-w-md grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              {parameters.map(([name, value]) => (
                <div key={name} className="contents">
                  <dt className="text-shell-muted">{name}</dt>
                  <dd className="font-medium text-shell-nav" data-testid={`param-${name}`}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </>
      )}
    </PageContainer>
  );
}
