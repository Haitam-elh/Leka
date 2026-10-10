"use client";

import { Archive, Download, ScrollText } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { permissionSaid } from "@/components/governance/governance-screen";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AUDIT_CATEGORIES,
  audit,
  type AuditCategory,
  type AuditEvent,
  type AuditFilters,
  type AuditOutcome,
  type Period,
} from "@/lib/audit";
import {
  useAuditEvent,
  useAuditRetention,
  useAuditSettings,
  useAuditTrail,
} from "@/lib/audit-queries";
import { ApiError } from "@/lib/api";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { personName } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";

/**
 * The audit trail (LEKA-407): every event that matters, searched — by
 * category, outcome, person, period, words — a page at a time; one read with
 * what else its request did; exported as CSV. And how long it is kept, the
 * owner's to change. Nothing here changes an event: nothing can.
 */

const SELECT = "h-9 rounded-md border border-shell-line bg-white px-2 text-sm";
const OUTCOME_TONE = {
  success: "success",
  failure: "warning",
  denied: "danger",
} as const;
const RETENTIONS = [90, 180, 365, 730, 1095, 1825, 2555] as const;

/** What was done, in words: the trail's own actions by name; an access
 * decision by its permission; a change to a role, a policy, an AI control by
 * what changed and how; what an AI control did by its outcome. */
export function actionSaid(t: Dictionary, action: string): string {
  const g = t.governance;
  const known = (g.audit.actions as Record<string, string>)[action];
  if (known) return known;
  const [subject, verb] = action.split(".");
  if (subject === "ai_control" && verb) {
    const outcome = (g.ai.outcomes as Record<string, string>)[verb];
    if (outcome) return `${g.ai.controls} · ${outcome}`;
  }
  const what = (g.subjects as Record<string, string>)[subject ?? ""];
  const how = (g.kinds as Record<string, string>)[verb ?? ""];
  if (what && how) return `${what} ${how}`;
  return permissionSaid(t, action);
}

function durationSaid(t: Dictionary, days: number): string {
  const w = t.governance.audit;
  return days % 365 === 0
    ? fill(w.years, { years: days / 365 })
    : fill(w.days, { days });
}

function Who({
  event,
  names,
}: {
  event: AuditEvent;
  names: Map<string, string>;
}) {
  const t = useDictionary();
  const w = t.governance.audit;
  if (event.actor_type === "system") {
    const forWhom =
      typeof event.detail.for === "string"
        ? names.get(event.detail.for)
        : undefined;
    return (
      <>
        {forWhom
          ? `${w.leka} · ${fill(w.forPerson, { name: forWhom })}`
          : w.leka}
      </>
    );
  }
  return <>{(event.actor_id && names.get(event.actor_id)) || w.formerMember}</>;
}

function Detail({ id, names }: { id: string; names: Map<string, string> }) {
  const t = useDictionary();
  const w = t.governance.audit;
  const { locale } = useLocale();
  const { data } = useAuditEvent(id);
  if (!data)
    return (
      <div
        className="mt-2 h-10 animate-pulse rounded bg-shell-canvas"
        aria-hidden="true"
      />
    );
  const said = Object.entries(data.detail).filter(
    ([, v]) => v !== null && v !== "",
  );
  return (
    <div
      className="mt-2 flex flex-col gap-2 rounded-lg bg-shell-canvas p-3 text-xs"
      data-testid="audit-detail"
    >
      <p className="text-shell-muted">
        {[
          data.ip ? fill(w.from, { ip: data.ip }) : null,
          data.request_id ? fill(w.request, { id: data.request_id }) : null,
          data.user_agent,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {said.length ? (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
          {said.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="font-medium text-brand-navy">{key}</dt>
              <dd className="break-all text-shell-muted">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {data.related.length ? (
        <div>
          <p className="font-medium text-brand-navy">{w.related}</p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {data.related.map((r) => (
              <li key={r.id} className="text-shell-muted">
                {actionSaid(t, r.action)} · <Who event={r} names={names} /> ·{" "}
                {exactDate(locale, r.at)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function AuditLogCard() {
  const t = useDictionary();
  const w = t.governance.audit;
  const { locale } = useLocale();
  const members = useTeamMembers();
  const names = new Map(
    (members.data ?? []).map((m) => [m.user_id, personName(m)]),
  );
  const [category, setCategory] = useState<AuditCategory | "">("");
  const [outcome, setOutcome] = useState<AuditOutcome | "">("");
  const [actor, setActor] = useState("");
  const [period, setPeriod] = useState<Period>("month");
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const filters: AuditFilters = { category, outcome, actor, period, q };
  const trail = useAuditTrail(filters);
  const events = trail.data?.pages.flatMap((p) => p.events) ?? [];

  return (
    <Card
      title={w.title}
      icon={
        <ScrollText className="size-4 text-shell-muted" aria-hidden="true" />
      }
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.said}</p>
      <form
        className="mb-3 grid gap-2 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(typed);
        }}
        data-testid="audit-filters"
      >
        <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
          {w.category}
          <select
            className={SELECT}
            value={category}
            onChange={(e) => setCategory(e.target.value as AuditCategory | "")}
          >
            <option value="">{w.all}</option>
            {AUDIT_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {w.categories[c]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
          {w.outcome}
          <select
            className={SELECT}
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as AuditOutcome | "")}
          >
            <option value="">{w.all}</option>
            <option value="success">{w.outcomes.success}</option>
            <option value="failure">{w.outcomes.failure}</option>
            <option value="denied">{w.outcomes.denied}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
          {w.person}
          <select
            className={SELECT}
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          >
            <option value="">{w.anyone}</option>
            {(members.data ?? []).map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {personName(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
          {w.period}
          <select
            className={SELECT}
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
          >
            {(["day", "week", "month", "quarter", "all"] as const).map((p) => (
              <option key={p} value={p}>
                {w.periods[p]}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <Input
            aria-label={w.search}
            placeholder={w.searchPlaceholder}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <Button type="submit" variant="outline">
            {w.search}
          </Button>
          <a
            href={audit.exportAddress(filters)}
            download
            className={buttonVariants({ variant: "outline" })}
          >
            <Download className="size-3.5" aria-hidden="true" />
            {w.export}
          </a>
        </div>
      </form>
      {events.length ? (
        <ul className="flex flex-col gap-1.5" data-testid="audit-events">
          {events.map((e) => (
            <li
              key={e.id}
              className="border-t border-shell-line pt-2 text-[0.8125rem]"
              data-action={e.action}
            >
              <button
                type="button"
                className="flex w-full flex-col gap-0.5 text-left"
                aria-expanded={open === e.id}
                onClick={() => setOpen(open === e.id ? null : e.id)}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <Pill tone={OUTCOME_TONE[e.outcome]}>
                    {w.outcomes[e.outcome]}
                  </Pill>
                  <span className="font-medium text-brand-navy">
                    {actionSaid(t, e.action)}
                  </span>
                  {e.target_label ? (
                    <span className="text-shell-muted">· {e.target_label}</span>
                  ) : null}
                </span>
                <span className="text-xs text-shell-muted">
                  <Who event={e} names={names} />
                  {e.actor_role
                    ? ` · ${(t.governance.roles as Record<string, string>)[e.actor_role] ?? e.actor_role}`
                    : ""}
                  {` · ${w.categories[e.category]} · ${exactDate(locale, e.at)}`}
                </span>
              </button>
              {open === e.id ? <Detail id={e.id} names={names} /> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">
          {trail.isLoading ? "…" : w.none}
        </p>
      )}
      {trail.hasNextPage ? (
        <Button
          type="button"
          variant="outline"
          className="mt-3"
          disabled={trail.isFetchingNextPage}
          onClick={() => void trail.fetchNextPage()}
        >
          {w.more}
        </Button>
      ) : null}
    </Card>
  );
}

export function AuditRetentionCard({ canChange }: { canChange: boolean }) {
  const t = useDictionary();
  const w = t.governance.audit;
  const { locale } = useLocale();
  const { data } = useAuditSettings();
  const keep = useAuditRetention();
  const [days, setDays] = useState<number | null>(null);
  if (!data) return null;
  const chosen = days ?? data.retention_days;

  async function save() {
    try {
      await keep.mutateAsync(chosen);
      notify.success({ title: w.kept });
      setDays(null);
    } catch (error) {
      notify.error({
        title: error instanceof ApiError ? error.message : t.governance.failed,
      });
    }
  }

  return (
    <Card
      title={w.retention}
      icon={<Archive className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <p className="mb-2 text-[0.8125rem] text-shell-muted">
        {w.retentionSaid}
      </p>
      <p
        className="text-[0.8125rem] text-brand-navy"
        data-testid="audit-retention"
      >
        {fill(w.keptFor, { days: data.retention_days })}
        {data.oldest
          ? ` · ${fill(w.oldest, { date: exactDate(locale, data.oldest) })}`
          : ""}
      </p>
      {canChange ? (
        <div className="mt-3 flex gap-2">
          <select
            aria-label={w.retention}
            className={SELECT}
            value={chosen}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[...new Set<number>([...RETENTIONS, data.retention_days])]
              .sort((a, b) => a - b)
              .map((d) => (
              <option key={d} value={d}>
                {durationSaid(t, d)}
              </option>
            ))}
          </select>
          <Button
            type="button"
            disabled={chosen === data.retention_days || keep.isPending}
            onClick={() => void save()}
          >
            {w.keep}
          </Button>
        </div>
      ) : (
        <p className="mt-2 text-xs text-shell-muted">{w.ownerOnly}</p>
      )}
    </Card>
  );
}
