"use client";

import { Bell, Plus } from "lucide-react";
import { createContext, useContext, useState } from "react";

import { cn } from "cn";

import { Card, CardLink, IconTile } from "@/components/environment/parts";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { routes } from "@/config/routes";
import { type AlertRule, type AlertRules, usable } from "@/lib/alert-rules";
import { ApiError } from "@/lib/api";
import { useAlertRuleChange, useAlertRules, useMonitoring } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { useTeamMembers } from "@/lib/team-queries";

/**
 * The alerts a person sets on Mon environnement (LEKA-477): « Créer une
 * alerte » from the screen's head, or on a thing from its panel; the rules
 * where the screen's settings are. Everything offered is what the server
 * says may be: what a source reads (with its freshness), its troubles, the
 * channels — each said where it stands, never « opérationnel » before a
 * delivery went —, the plan's limit. The server checks it all again.
 */

type Opening = { rule?: AlertRule; subject?: string };
const OpenAlert = createContext<((opening: Opening) => void) | null>(null);

/** Opens the dialog — null outside Mon environnement, or for who may not. */
export function useOpenAlert(): ((opening: Opening) => void) | null {
  const open = useContext(OpenAlert);
  const may = usePermissions()?.includes("source:manage") ?? false;
  return may ? open : null;
}

export function AlertRuleProvider({ children }: { children: React.ReactNode }) {
  const [opening, setOpening] = useState<Opening | null>(null);
  return (
    <OpenAlert.Provider value={setOpening}>
      {children}
      {opening ? (
        <AlertRuleDialog
          rule={opening.rule}
          subject={opening.subject}
          onClose={() => setOpening(null)}
        />
      ) : null}
    </OpenAlert.Provider>
  );
}

export function CreateAlertButton() {
  const t = useDictionary();
  const open = useOpenAlert();
  if (!open) return null;
  return (
    <Button type="button" variant="outline" onClick={() => open({})} data-testid="alert-create">
      <Bell aria-hidden="true" />
      {t.environment.twin.alerts.rules.create}
    </Button>
  );
}

/** On a thing's panel: only when its state is read — a rule may be set on it.
 * Nothing outside Mon environnement (the board alone, in its tests). */
export function AlertOnThing({ entityId }: { entityId: string | null }) {
  if (!useContext(OpenAlert) || !entityId) return null;
  return <AlertOn entityId={entityId} />;
}

function AlertOn({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const open = useOpenAlert();
  const watched = useAlertRules(Boolean(open)).data?.watchable.some((w) => w.subject_id === entityId);
  if (!open || !watched) return null;
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => open({ subject: `entity:${entityId}` })}
      data-testid="alert-create-on"
    >
      <Bell aria-hidden="true" />
      {t.environment.twin.alerts.rules.createOn}
    </Button>
  );
}

const CONFIRMS = ["0", "5", "15", "30", "60"] as const;
const REPEATS = ["once", "1", "4", "24"] as const;
type Repeat = (typeof REPEATS)[number];

const keyOf = (type: string, id: string) => `${type}:${id}`;

function quotaWords(w: ReturnType<typeof useDictionary>["environment"]["twin"]["alerts"]["rules"], data: AlertRules) {
  return data.limit === null ? fill(w.quotaNone, { used: data.used }) : fill(w.quota, { used: data.used, limit: data.limit });
}

function AlertRuleDialog({
  rule,
  subject,
  onClose,
}: {
  rule?: AlertRule;
  subject?: string;
  onClose: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.twin.alerts.rules;
  const kinds = t.environment.twin.alerts.kinds;
  const data = useAlertRules().data;
  const plan = useMonitoring().data?.entitlement.plan;
  const members = useTeamMembers().data ?? [];
  const me = useCurrentUser();
  const { create, change } = useAlertRuleChange();
  const [name, setName] = useState(rule?.name ?? "");
  const [chosen, setChosen] = useState(
    rule ? keyOf(rule.subject_type, rule.subject_id) : (subject ?? ""),
  );
  const [conditions, setConditions] = useState<string[]>(rule?.conditions ?? []);
  const [severity, setSeverity] = useState<string>(rule?.severity ?? "medium");
  const [confirm, setConfirm] = useState(String(rule?.confirm_minutes ?? 0));
  const [repeat, setRepeat] = useState<Repeat>(
    rule?.repeat_hours ? (String(rule.repeat_hours) as Repeat) : "once",
  );
  const [channels, setChannels] = useState<string[]>(rule?.channels ?? []);
  const [recipients, setRecipients] = useState<string[]>(rule?.recipients ?? (me?.id ? [me.id] : []));
  const [error, setError] = useState<string | null>(null);

  const watchable = data?.watchable ?? [];
  const target = watchable.find((each) => keyOf(each.subject_type, each.subject_id) === chosen);
  // A first choice: its troubles all, in LEKA at least, its name said.
  const shownConditions = conditions.length || !target ? conditions : [...target.conditions];
  const offered = (data?.channels ?? []).filter(usable).map((c) => c.key as string);
  const shownChannels = channels.length || rule ? channels : offered.includes("in_app") ? ["in_app"] : [];
  const atLimit = !rule && data !== undefined && data.limit !== null && data.used >= data.limit;
  const pending = create.isPending || change.isPending;

  function toggle(list: string[], value: string, on: boolean): string[] {
    return on ? [...new Set([...list, value])] : list.filter((each) => each !== value);
  }

  function failed(problem: unknown) {
    if (problem instanceof ApiError) {
      const code = problem.fieldErrors?.rule;
      setError((code && (w.refused as Record<string, string>)[code]) || problem.message);
    } else setError(t.states.errorTitle);
  }

  function save() {
    if (!target) return;
    const body = {
      name: name.trim() || target.name,
      conditions: shownConditions as AlertRule["conditions"],
      severity: severity as AlertRule["severity"],
      confirm_minutes: Number(confirm),
      repeat_hours: repeat === "once" ? null : Number(repeat),
      channels: shownChannels as AlertRule["channels"],
      recipients: shownChannels.includes("email") ? recipients : [],
    };
    const done = { onSuccess: () => (notify.success({ title: w.saved }), onClose()), onError: failed };
    if (rule) change.mutate({ id: rule.id, body }, done);
    else
      create.mutate(
        { ...body, subject_type: target.subject_type, subject_id: target.subject_id, enabled: true },
        done,
      );
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg" data-testid="alert-dialog">
        <DialogHeader>
          <DialogTitle>{rule ? w.dialogEdit : w.dialogTitle}</DialogTitle>
          <DialogDescription>{w.dialogBody}</DialogDescription>
        </DialogHeader>
        {data ? (
          <p className="text-xs text-shell-muted" data-testid="alert-quota">
            {quotaWords(w, data)}
          </p>
        ) : null}
        {atLimit && data ? (
          <div className="space-y-1 rounded-lg bg-state-warning/10 px-3 py-2 text-[0.8125rem] text-brand-navy" role="status" data-testid="alert-limit">
            <p>{fill(w.atLimit, { plan: capital(plan), limit: data.limit ?? 0 })}</p>
            {data.upgrade ? <p>{fill(w.atLimitUpgrade, { upgrade: capital(data.upgrade) })}</p> : null}
            <CardLink href={routes.billingPlans()}>{t.environment.twin.alerts.limitAction}</CardLink>
          </div>
        ) : watchable.length === 0 && data ? (
          <p className="text-[0.8125rem] text-shell-muted">{w.nothingWatchable}</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <Label id="alert-subject-label">{w.subject}</Label>
              <Select
                value={chosen || null}
                onValueChange={(value) => {
                  setChosen(String(value ?? ""));
                  setConditions([]);
                }}
                items={watchable.map((each) => ({ value: keyOf(each.subject_type, each.subject_id), label: each.name }))}
                disabled={Boolean(rule)}
              >
                <SelectTrigger className="w-full" aria-labelledby="alert-subject-label" data-testid="alert-subject">
                  <SelectValue placeholder={w.subjectPick} />
                </SelectTrigger>
                <SelectContent>
                  {watchable.map((each) => (
                    <SelectItem key={keyOf(each.subject_type, each.subject_id)} value={keyOf(each.subject_type, each.subject_id)}>
                      {each.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alert-name">{w.name}</Label>
              <Input
                id="alert-name"
                value={name}
                maxLength={120}
                placeholder={target?.name ?? w.namePlaceholder}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            {target ? (
              <fieldset className="space-y-1.5">
                <legend className="text-sm font-medium">{w.conditions}</legend>
                {target.conditions.map((condition) => (
                  <label key={condition} className="flex items-center gap-2 text-[0.875rem]">
                    <Checkbox
                      checked={shownConditions.includes(condition)}
                      onCheckedChange={(on) => setConditions(toggle(shownConditions, condition, on))}
                      data-testid={`alert-condition-${condition}`}
                    />
                    {kinds[condition]}
                  </label>
                ))}
              </fieldset>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <Choice label={w.severity} value={severity} onChange={setSeverity} options={(["high", "medium", "low"] as const).map((key) => ({ value: key, label: w.severities[key] }))} />
              <Choice label={w.confirm} value={confirm} onChange={setConfirm} options={CONFIRMS.map((key) => ({ value: key, label: w.confirms[key] }))} />
              <Choice className="sm:col-span-2" label={w.repeat} value={repeat} onChange={(value) => setRepeat(value as Repeat)} options={REPEATS.map((key) => ({ value: key, label: w.repeats[key] }))} />
            </div>
            {repeat !== "once" ? <p className="-mt-2 text-xs text-shell-muted">{w.repeatHint}</p> : null}
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">{w.channels}</legend>
              {(data?.channels ?? []).map((channel) => (
                <label key={channel.key} className="flex items-center gap-2 text-[0.875rem]" data-testid={`alert-channel-${channel.key}`} data-status={channel.status}>
                  <Checkbox
                    checked={shownChannels.includes(channel.key)}
                    disabled={!usable(channel)}
                    onCheckedChange={(on) => setChannels(toggle(shownChannels, channel.key, on))}
                  />
                  <span className={usable(channel) ? "text-brand-navy" : "text-shell-muted"}>
                    {w.channelNames[channel.key]}
                  </span>
                  <span className={channel.status === "failing" ? "text-xs text-state-danger" : "text-xs text-shell-muted"}>
                    · {w.channelStatus[channel.status]}
                  </span>
                </label>
              ))}
            </fieldset>
            {shownChannels.includes("email") ? (
              <fieldset className="space-y-1.5">
                <legend className="text-sm font-medium">{w.recipients}</legend>
                {members.map((member) => (
                  <label key={member.user_id} className="flex items-center gap-2 text-[0.875rem]">
                    <Checkbox
                      checked={recipients.includes(member.user_id)}
                      onCheckedChange={(on) => setRecipients(toggle(recipients, member.user_id, on))}
                    />
                    {[member.first_name, member.last_name].filter(Boolean).join(" ") || member.email}
                    {member.first_name || member.last_name ? (
                      <span className="truncate text-xs text-shell-muted">{member.email}</span>
                    ) : null}
                  </label>
                ))}
              </fieldset>
            ) : null}
          </div>
        )}
        {error ? (
          <p className="text-[0.8125rem] text-state-danger" role="alert" data-testid="alert-error">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {w.cancel}
          </Button>
          <Button
            type="button"
            onClick={save}
            disabled={pending || atLimit || !target || !shownConditions.length || !shownChannels.length}
            data-testid="alert-save"
          >
            {w.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const capital = (word: string | undefined) => (word ? word.charAt(0).toUpperCase() + word.slice(1) : "—");

function Choice({
  label,
  value,
  onChange,
  options,
  className,
}: {
  className?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  const id = `alert-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label id={id}>{label}</Label>
      <Select value={value} onValueChange={(next) => onChange(String(next ?? value))} items={options}>
        <SelectTrigger className="w-full" aria-labelledby={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** The rules, where the screen's settings are: each on what, when, how —
 * on or off, its last telling (a failure said), tried, changed, removed. */
export function AlertRulesCard() {
  const t = useDictionary();
  const w = t.environment.twin.alerts.rules;
  const kinds = t.environment.twin.alerts.kinds;
  const data = useAlertRules().data;
  const open = useOpenAlert();
  const { change, remove, test } = useAlertRuleChange();
  const confirm = useConfirm();
  if (!data) return null;
  const failed = (problem: unknown) =>
    notify.error({ title: problem instanceof ApiError ? problem.message : t.states.errorTitle });

  return (
    <Card
      title={w.title}
      icon={<IconTile icon={Bell} tone="violet" className="size-9" />}
      action={
        <span className="flex items-center gap-2">
          <span className="text-xs text-shell-muted" data-testid="alert-rules-quota">
            {quotaWords(w, data)}
          </span>
          {open ? (
            <Button type="button" size="sm" onClick={() => open({})}>
              <Plus aria-hidden="true" />
              {w.create}
            </Button>
          ) : null}
        </span>
      }
    >
      {data.rules.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.noneYet}</p>
      ) : (
        <ul className="divide-y divide-shell-line/60" data-testid="alert-rules">
          {data.rules.map((rule) => {
            const last = rule.deliveries?.[0];
            return (
              <li key={rule.id} className="space-y-1 py-2.5" data-testid="alert-rule" data-enabled={rule.enabled || undefined}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 font-medium text-brand-navy">
                    {rule.name}
                    <span className={rule.enabled ? "ms-2 text-xs text-state-success" : "ms-2 text-xs text-shell-muted"}>
                      {rule.enabled ? w.on : w.off}
                    </span>
                  </p>
                  {open ? (
                    <span className="flex flex-wrap gap-1">
                      <Button type="button" size="sm" variant="ghost" disabled={test.isPending} onClick={() => test.mutate(rule.id, { onSuccess: () => notify.success({ title: w.tested }), onError: failed })}>
                        {w.test}
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => open({ rule })}>
                        {w.edit}
                      </Button>
                      <Button type="button" size="sm" variant="ghost" disabled={change.isPending} onClick={() => change.mutate({ id: rule.id, body: { enabled: !rule.enabled } }, { onError: failed })} data-testid="alert-rule-toggle">
                        {rule.enabled ? w.disable : w.enable}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          const ok = await confirm({ title: fill(w.removeTitle, { name: rule.name }), description: w.removeBody, confirmLabel: w.remove, destructive: true });
                          if (ok) remove.mutate(rule.id, { onSuccess: () => notify.success({ title: w.removed }), onError: failed });
                        }}
                      >
                        {w.remove}
                      </Button>
                    </span>
                  ) : null}
                </div>
                <p className="text-xs text-shell-muted">
                  {[rule.subject_name, rule.conditions.map((c) => kinds[c]).join(", "), rule.channels.map((c) => w.channelNames[c]).join(", ")].join(" · ")}
                </p>
                <p className={last?.status === "failed" ? "text-xs text-state-danger" : "text-xs text-shell-muted"} data-testid="alert-rule-last">
                  {!last
                    ? w.never
                    : fill(last.status === "failed" ? w.lastFailed : w.lastSent, {
                        channel: w.channelNames[last.channel],
                        ago: timeAgo(t, last.at).toLowerCase(),
                        error: last.error ?? "",
                      })}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
