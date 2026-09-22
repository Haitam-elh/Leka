"use client";

import { usePathname } from "next/navigation";

import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { matchRoute } from "@/lib/navigation/active";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A page with nothing in it yet, titled by the registry.
 *
 * Every screen of the product is one of these until the ticket that owns it
 * arrives. They exist to prove the frame: the same shell, the right entry
 * marked, the right title, on every route — including the dynamic ones,
 * which print the identifier they were given so a link can be checked.
 */
export function PlaceholderPage() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const match = matchRoute(pathname);
  const parameters = Object.entries(match?.params ?? {});

  return (
    <PageContainer>
      <PageHeader title={match ? t.nav[match.route.labelKey] : t.shell.notFoundTitle} />
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
    </PageContainer>
  );
}
