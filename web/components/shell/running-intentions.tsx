"use client";

import { CircleAlert, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { cn } from "cn";
import { JourneyPill } from "@/components/intentions/journey";
import { usePermissions } from "@/components/shell/shell-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Intention } from "@/lib/intentions/api";
import { working } from "@/lib/intentions/journey";
import { useMyActiveIntentions } from "@/lib/intentions/queries";

/**
 * What you asked LEKA that is not settled yet, from every page (LEKA-475).
 * All of it is the API's: the list is its « active » phase, so a row leaves
 * only at a terminal state (answered, done, rejected, cancelled); who acts
 * next is its journey's `by`. LEKA at it: said at work. A person to act —
 * failed, a decision, a question, or LEKA late: said to be dealt with, in
 * its own colour. No step, no percentage: nothing here measures them.
 */

const FAILED = new Set(["analysis_failed", "action_failed"]);

/** Whether it waits on a person, or on LEKA past its time. */
const toDeal = (row: Intention) => !working(row.journey) || row.journey.late;

const TRIGGER =
  "inline-flex h-9 max-w-64 min-w-0 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-brand-violet/40";

export function RunningIntentions() {
  const readable = usePermissions()?.includes("intention:read") ?? false;
  const query = useMyActiveIntentions(readable);
  const rows = query.data?.data ?? [];
  return (
    // Always there, so what appears in it is said, to whoever does not see it.
    <div aria-live="polite" className="min-w-0 empty:hidden">
      {rows.length ? <Indicator rows={rows} more={Boolean(query.data?.next_cursor)} /> : null}
    </div>
  );
}

function Indicator({ rows, more }: { rows: Intention[]; more: boolean }) {
  const t = useDictionary();
  const w = t.shell.running;
  const states = t.intentions.journey.states;
  const router = useRouter();

  const dealt = rows.filter(toDeal);
  const failed = rows.some((row) => FAILED.has(row.journey.state));
  const tone = failed
    ? "bg-state-danger/10 text-state-danger hover:bg-state-danger/15"
    : dealt.length
      ? "bg-state-warning/10 text-state-warning hover:bg-state-warning/15"
      : "bg-brand-violet-soft/60 text-shell-nav-active hover:bg-brand-violet-soft";
  const icon = dealt.length ? (
    <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
  ) : (
    <LoaderCircle className="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
  );
  const stateOf = (row: Intention) =>
    row.journey.late ? `${states[row.journey.state]} · ${w.late}` : states[row.journey.state];
  const count = more ? `${rows.length}+` : String(rows.length);

  if (rows.length === 1) {
    const [row] = rows;
    return (
      <Link
          href={routes.intention(row.id)}
          className={cn(TRIGGER, tone)}
          data-testid="running-intentions"
          data-state={row.journey.state}
          aria-label={`${stateOf(row)} — ${row.title}`}
        >
          {icon}
          <span className="hidden truncate sm:inline">
            {stateOf(row)} · {row.title}
          </span>
      </Link>
    );
  }

  const said = dealt.length
    ? `${fill(w.count, { count })} · ${fill(w.toDeal, { count: dealt.length })}`
    : fill(w.count, { count });
  return (
    <DropdownMenu>
        <DropdownMenuTrigger
          className={cn(TRIGGER, tone)}
          data-testid="running-intentions"
          data-count={rows.length}
          aria-label={said}
        >
          {icon}
          <span className="tabular-nums sm:hidden">{count}</span>
          <span className="hidden truncate sm:inline">{said}</span>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-80">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="font-normal text-shell-muted">{w.label}</DropdownMenuLabel>
            {rows.map((row) => (
              <DropdownMenuItem
                key={row.id}
                onClick={() => router.push(routes.intention(row.id))}
                className="flex-col items-start gap-1"
                data-testid="running-intention"
                data-intention={row.id}
                data-state={row.journey.state}
              >
                <span className="w-full truncate font-medium text-brand-navy">{row.title}</span>
                <span className="flex items-center gap-1.5">
                  <JourneyPill journey={row.journey} />
                  {row.journey.late ? (
                    <span className="text-xs font-medium text-state-warning">{w.late}</span>
                  ) : null}
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => router.push(routes.intentions())} data-testid="running-all">
            {w.all}
          </DropdownMenuItem>
        </DropdownMenuContent>
    </DropdownMenu>
  );
}
