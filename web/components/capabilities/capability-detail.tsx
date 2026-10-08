"use client";

import {
  ArrowLeft,
  Bot,
  CircleCheck,
  CircleDashed,
  FileOutput,
  History,
  Lightbulb,
  ListChecks,
  MessageSquareQuote,
  Plug,
  SearchX,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import {
  CATEGORY_ICON,
  CATEGORY_TONE,
  reasonSaid,
  summaryOf,
  titleOf,
} from "@/components/capabilities/catalogue";
import { Card, IconTile } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { hasSourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import type { CapabilityDetail } from "@/lib/capabilities";
import { useCapability } from "@/lib/capabilities-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { useNamePage } from "@/lib/navigation/page-name";

/**
 * One capability (LEKA-393): what it is for, what it takes and delivers,
 * what it needs and whether it is there, who may use it, whether it can be
 * used here now and why not — its versions and its history, and its week.
 * An agent's instructions stay on the server: what it is, is said.
 */

const FORMAT_LABEL: Record<string, string> = {
  json: "JSON",
  markdown: "Markdown",
  pptx: "PowerPoint (.pptx)",
  pdf: "PDF",
  docx: "Word (.docx)",
  xlsx: "Excel (.xlsx)",
  csv: "CSV",
};

function Facts({ capability }: { capability: CapabilityDetail }) {
  const t = useDictionary();
  const w = t.catalogue.detail;
  const rows: [string, React.ReactNode][] = [
    [w.mode, (w.modes as Record<string, string>)[capability.mode] ?? capability.mode],
    [w.risk, (w.risks as Record<string, string>)[capability.risk] ?? capability.risk],
    [w.permission, <code key="p" className="text-xs">{capability.permission}</code>],
    [
      w.origin,
      capability.origin.startsWith("vendor:") ? w.origins.vendor : w.origins.internal,
    ],
  ];
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-shell-muted">{label}</dt>
          <dd className="text-brand-navy">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CapabilityScreen() {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.catalogue.detail;
  const params = useParams<{ capabilityId: string }>();
  const pathname = usePathname() ?? "/";
  const key = params.capabilityId ?? "";
  const query = useCapability(key);
  const data = query.data;
  const title = data ? titleOf(t, data) : undefined;
  const crumbs = buildBreadcrumb(pathname, t, title ? () => title : undefined);
  useNamePage(pathname, title);

  let body: React.ReactNode;
  if (query.error instanceof ApiError && query.error.status === 404) {
    body = (
      <StatePanel
        icon={SearchX}
        title={t.catalogue.empty}
        actions={
          <Link href={routes.capabilities()} className={buttonVariants({ variant: "outline" })}>
            {w.back}
          </Link>
        }
      />
    );
  } else if (query.isError) {
    body = <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  } else if (!data) {
    body = <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else {
    const Icon = data.kind === "agent" ? Bot : (CATEGORY_ICON[data.category] ?? Lightbulb);
    body = (
      <div className="flex flex-col gap-4" data-testid="capability" data-key={data.key}>
        <section className="flex flex-wrap items-start gap-4 rounded-xl border border-shell-line bg-white p-5">
          <IconTile icon={Icon} tone={CATEGORY_TONE[data.category] ?? "neutral"} />
          <div className="min-w-0 flex-1">
            <p className="text-[0.9375rem] text-brand-navy">{summaryOf(t, data)}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Pill tone={CATEGORY_TONE[data.category] ?? "neutral"}>
                {(t.catalogue.categories as Record<string, string>)[data.category] ?? data.category}
              </Pill>
              <Pill tone="neutral">{t.catalogue.kinds[data.kind]}</Pill>
              <Pill tone="neutral">v{data.version}</Pill>
              <Pill tone={data.lifecycle === "active" ? "success" : "warning"}>
                {t.catalogue.lifecycles[data.lifecycle]}
              </Pill>
            </div>
          </div>
          <div className="w-full md:w-auto" data-testid="capability-availability">
            {data.available ? (
              <Pill tone="success" dot>
                {t.catalogue.available}
              </Pill>
            ) : (
              <div className="flex flex-col gap-1">
                <Pill tone="warning">{t.catalogue.unavailable}</Pill>
                <ul className="text-xs text-state-warning">
                  {data.reasons.map((reason) => (
                    <li key={reason.code}>{reasonSaid(t, reason)}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <Card title={w.contract} icon={<ListChecks className="size-4 text-shell-muted" aria-hidden="true" />}>
              {data.inputs.length ? (
                <ul className="space-y-2 text-[0.8125rem]" data-testid="capability-inputs">
                  {data.inputs.map((input) => (
                    <li key={input.name} className="flex flex-col">
                      <span className="font-medium text-brand-navy">
                        {input.name}{" "}
                        <span className="font-normal text-shell-muted">
                          · {input.required ? w.required : w.optional}
                        </span>
                      </span>
                      {input.description ? (
                        <span className="text-shell-muted">{input.description}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[0.8125rem] text-shell-muted">{w.noInputs}</p>
              )}
            </Card>
            <Card title={w.delivers} icon={<FileOutput className="size-4 text-shell-muted" aria-hidden="true" />}>
              <p className="text-[0.875rem] text-brand-navy">
                {(w.outputs as Record<string, string>)[data.output] ?? data.output}
              </p>
              <ul className="mt-2 flex flex-wrap gap-2" data-testid="capability-formats">
                {data.formats.map((format) => (
                  <li key={format}>
                    <Pill tone="violet">{FORMAT_LABEL[format] ?? format}</Pill>
                  </li>
                ))}
              </ul>
            </Card>
            {data.examples.length ? (
              <Card title={w.examples} icon={<MessageSquareQuote className="size-4 text-shell-muted" aria-hidden="true" />}>
                <ul className="space-y-1 text-[0.8125rem] text-brand-navy">
                  {data.examples.map((example) => (
                    <li key={example}>« {example} »</li>
                  ))}
                </ul>
              </Card>
            ) : null}
          </div>
          <div className="flex flex-col gap-4">
            <Card title={w.needs} icon={<Plug className="size-4 text-shell-muted" aria-hidden="true" />}>
              <ul className="space-y-2 text-[0.8125rem]" data-testid="capability-needs">
                {data.sources.map((need) => (
                  <li key={need.any_of.join("|")} className="flex items-center gap-2">
                    {need.connected ? (
                      <CircleCheck className="size-4 text-state-success" aria-hidden="true" />
                    ) : (
                      <CircleDashed className="size-4 text-state-warning" aria-hidden="true" />
                    )}
                    <span className="text-brand-navy">
                      {fill(w.source, {
                        sources: need.any_of
                          .map((k) => (hasSourceLogo(k) ? sourceTitle(k) : k))
                          .join(t.catalogue.or),
                      })}
                    </span>
                    <span className="text-shell-muted">
                      {" · "}
                      {need.connected ? w.connected : w.notConnected}
                    </span>
                  </li>
                ))}
                {data.model ? (
                  <li className="flex items-center gap-2">
                    <Sparkles className="size-4 text-state-warning" aria-hidden="true" />
                    <span className="text-brand-navy">{w.model}</span>
                    <span className="text-shell-muted">
                      {" · "}
                      {data.reasons.some((r) => r.code === "no_model") ? w.modelWaiting : w.connected}
                    </span>
                  </li>
                ) : null}
              </ul>
              <div className="mt-3">
                <Facts capability={data} />
              </div>
            </Card>
            <Card title={w.week} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
              <p className="text-[0.875rem] text-brand-navy" data-testid="capability-week">
                {data.usage.runs
                  ? fill(t.catalogue.runs, { count: data.usage.runs })
                  : t.catalogue.noRun}
              </p>
              {data.usage.average_ms !== null ? (
                <p className="text-xs text-shell-muted">
                  {fill(w.average, { ms: data.usage.average_ms })}
                  {data.usage.failures ? ` · ${fill(w.failures, { count: data.usage.failures })}` : ""}
                </p>
              ) : null}
            </Card>
            <Card title={w.history} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
              <ul className="space-y-1 text-[0.8125rem]" data-testid="capability-versions">
                {data.history.map((version) => (
                  <li key={version.version} className="flex items-center gap-2">
                    <span className="font-medium text-brand-navy">v{version.version}</span>
                    <span className="text-shell-muted">
                      · {(t.catalogue.lifecycles as Record<string, string>)[version.lifecycle] ?? version.lifecycle}{" "}
                      · {exactDate(locale, version.registered_at)}
                    </span>
                  </li>
                ))}
              </ul>
              {data.events.length ? (
                <>
                  <p className="mt-3 mb-1 text-xs font-semibold text-shell-muted">{w.events}</p>
                  <ol className="space-y-1 text-xs" data-testid="capability-events">
                    {data.events.map((event) => (
                      <li key={event.id} className="text-brand-navy">
                        {fill((w.eventKinds as Record<string, string>)[event.kind] ?? event.kind, {
                          from:
                            (t.catalogue.lifecycles as Record<string, string>)[event.from_lifecycle ?? ""] ?? "",
                          to: (t.catalogue.lifecycles as Record<string, string>)[event.to_lifecycle ?? ""] ?? "",
                        })}{" "}
                        <span className="text-shell-muted">
                          · v{event.version} · {exactDate(locale, event.at)}
                        </span>
                      </li>
                    ))}
                  </ol>
                </>
              ) : null}
            </Card>
          </div>
        </div>
      </div>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title={title ?? t.nav.capabilityDetail}
        breadcrumb={crumbs}
        actions={
          <Link href={routes.capabilities()} className={buttonVariants({ variant: "outline" })}>
            <ArrowLeft className="size-4" aria-hidden="true" />
            {w.back}
          </Link>
        }
      />
      {body}
    </PageContainer>
  );
}
