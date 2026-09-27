"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Pencil, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { capabilityWord } from "@/components/sources/source-panel";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import type { Source } from "@/lib/sources";
import { sourceKeys, useCatalog, useSourceMutation } from "@/lib/sources-queries";
import {
  ENTITY_TYPES,
  type Finding,
  type LineError,
  type SettingsDraft,
  type SettingsSaved,
  type SourceSettings,
  fromDraft,
  hasMapping,
  sourceSettings,
  toDraft,
} from "@/lib/source-settings";

/**
 * A source's scope rules and mapping (LEKA-351): read by everyone, changed
 * by a manager, versioned by the API.
 *
 * The editor writes lines — a pattern per line, `acme/pay* → billing` —
 * and says which one it cannot read before anything is sent. "Check" asks
 * the API what is wrong or doubtful — against what the credentials can
 * see — without saving; "Save" makes a version, or refuses it with every
 * error named.
 */
export function SourceSettingsSection({ source }: { source: Source }) {
  const t = useDictionary();
  const w = t.sources.settings;
  const canManage = usePermissions()?.includes("source:manage") ?? false;
  // Checked against the connector: none, nothing to check against.
  const hasConnector = useCatalog().data?.some((entry) => entry.key === source.type) ?? false;
  const [editing, setEditing] = useState(false);
  const settings = useQuery({
    queryKey: [...sourceKeys.all, "settings", source.id],
    queryFn: () => sourceSettings.get(source.id),
  });
  const latest = useQuery({
    queryKey: [...sourceKeys.all, "settings-versions", source.id],
    queryFn: async () => (await sourceSettings.versions(source.id, 1)).data[0] ?? null,
  });

  const read = settings.data;
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-brand-navy">{w.title}</h2>
          {read && read.version > 0 ? (
            <p className="text-sm text-shell-muted">
              {latest.data
                ? fill(w.changedBy, {
                    version: read.version,
                    date: new Date(latest.data.created_at).toLocaleDateString(),
                  })
                : fill(w.version, { version: read.version })}
            </p>
          ) : null}
        </div>
        {canManage && hasConnector && read ? (
          <Button variant="outline" onClick={() => setEditing(true)}>
            <Pencil aria-hidden="true" />
            {w.edit}
          </Button>
        ) : null}
      </div>
      {read ? <Summary settings={read.settings} never={read.version === 0} /> : null}
      {editing && read ? (
        <SettingsDialog
          source={source}
          settings={read.settings}
          onClose={() => setEditing(false)}
        />
      ) : null}
    </section>
  );
}

function Summary({ settings, never }: { settings: SourceSettings; never: boolean }) {
  const t = useDictionary();
  const w = t.sources.settings;
  if (never) return <p className="text-sm text-shell-muted">{w.never}</p>;
  const scope = settings.scope ?? { include: [], exclude: [] };
  const m = settings.mapping ?? {};
  const rows: [string, string][] = [
    [w.include, (scope.include ?? []).join(", ") || w.everything],
    [w.exclude, (scope.exclude ?? []).join(", ") || w.none],
  ];
  if (hasMapping(settings)) {
    const table = (entries?: Record<string, string>) =>
      Object.entries(entries ?? {})
        .map(([k, v]) => `${k} → ${v}`)
        .join(", ");
    const mapped: [string, string][] = [
      [
        w.entityTypes,
        Object.entries(m.entity_types ?? {})
          .map(([capability, type]) => `${capabilityWord(t, capability)} → ${type}`)
          .join(", "),
      ],
      [w.services, (m.services ?? []).map((r) => `${r.match} → ${r.service}`).join(", ")],
      [w.owners, (m.owners ?? []).map((r) => `${r.match} → ${r.team}`).join(", ")],
      [
        w.tagKeys,
        [
          ...(m.tag_keys?.environment ?? []),
          ...(m.tag_keys?.service ?? []),
          ...(m.tag_keys?.owner ?? []),
        ].join(", "),
      ],
      [w.states, table(m.states)],
      [w.priorities, table(m.priorities)],
      [w.environments, table(m.environments)],
    ];
    rows.push(...mapped.filter(([, value]) => value.length > 0));
  } else {
    rows.push([w.mapping, w.noMapping]);
  }
  return (
    <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-shell-muted">{label}</dt>
          <dd className="break-words text-brand-navy">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── The editor ──────────────────────────────────────────────────────────────

const TEXT_FIELDS: { field: keyof SettingsDraft; help: string; rows: number }[] = [
  { field: "include", help: "includeHelp", rows: 3 },
  { field: "exclude", help: "excludeHelp", rows: 3 },
  { field: "services", help: "servicesHelp", rows: 3 },
  { field: "owners", help: "ownersHelp", rows: 3 },
  { field: "states", help: "statesHelp", rows: 3 },
  { field: "priorities", help: "prioritiesHelp", rows: 2 },
  { field: "environments", help: "environmentsHelp", rows: 2 },
];
const TAG_FIELDS: (keyof SettingsDraft)[] = ["tagEnvironment", "tagService", "tagOwner"];

function SettingsDialog({
  source,
  settings,
  onClose,
}: {
  source: Source;
  settings: SourceSettings;
  onClose: () => void;
}) {
  const t = useDictionary();
  const w = t.sources.settings;
  const words = w as Record<string, string>;
  const [draft, setDraft] = useState<SettingsDraft>(() => toDraft(settings));
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [lineErrors, setLineErrors] = useState<LineError[]>([]);
  const run = useSourceMutation(async (action: () => Promise<unknown>) => action());

  const set = (field: keyof SettingsDraft, value: string) =>
    setDraft((current) => ({ ...current, [field]: value }));

  function parsed(): SourceSettings | null {
    const read = fromDraft(draft);
    setLineErrors(read.errors);
    return read.settings;
  }

  async function check() {
    const wanted = parsed();
    if (!wanted) return;
    const answer = await run.mutateAsync(() => sourceSettings.check(source.id, wanted));
    setFindings((answer as { findings: Finding[] }).findings);
  }

  async function save() {
    const wanted = parsed();
    if (!wanted) return;
    try {
      const saved = (await run.mutateAsync(() =>
        sourceSettings.save(source.id, wanted),
      )) as SettingsSaved;
      notify.success({
        title: saved.changed.length > 0 ? fill(w.saved, { version: saved.version }) : w.unchanged,
        description: saved.full_sync_queued ? w.fullSync : undefined,
      });
      onClose();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422 && caught.fieldErrors) {
        setFindings(
          Object.entries(caught.fieldErrors).map(([path, message]) => ({
            level: "error",
            path,
            message,
          })),
        );
        notify.error({ title: w.refused });
      } else {
        notify.error({ title: w.failed });
      }
    }
  }

  const busy = run.isPending;
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogTitle>{fill(w.editTitle, { name: source.display_name })}</DialogTitle>
        <DialogDescription>{w.editBody}</DialogDescription>

        <div className="grid gap-4 sm:grid-cols-2">
          {TEXT_FIELDS.map(({ field, help, rows }) => (
            <div key={field} className="flex flex-col gap-1.5">
              <Label htmlFor={`settings-${field}`}>{words[field]}</Label>
              <Textarea
                id={`settings-${field}`}
                rows={rows}
                value={draft[field] as string}
                onChange={(event) => set(field, event.target.value)}
                aria-describedby={`settings-${field}-help`}
                className="font-mono text-sm"
              />
              <p id={`settings-${field}-help`} className="text-xs text-shell-muted">
                {words[help]}
              </p>
            </div>
          ))}
          {TAG_FIELDS.map((field) => (
            <div key={field} className="flex flex-col gap-1.5">
              <Label htmlFor={`settings-${field}`}>{words[field]}</Label>
              <Input
                id={`settings-${field}`}
                value={draft[field] as string}
                onChange={(event) => set(field, event.target.value)}
              />
              <p className="text-xs text-shell-muted">{w.tagsHelp}</p>
            </div>
          ))}
        </div>

        {source.capabilities.length > 0 ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium text-brand-navy">{w.entityTypes}</legend>
            {source.capabilities.map((capability) => (
              <div key={capability} className="flex items-center gap-3 text-sm">
                <label htmlFor={`settings-type-${capability}`} className="w-40 text-shell-muted">
                  {capabilityWord(t, capability)}
                </label>
                <select
                  id={`settings-type-${capability}`}
                  className="h-8 rounded-md border border-shell-line bg-white px-2 text-sm"
                  value={draft.entityTypes[capability] ?? ""}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      entityTypes: { ...current.entityTypes, [capability]: event.target.value },
                    }))
                  }
                >
                  <option value="">{w.entityDefault}</option>
                  {ENTITY_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </fieldset>
        ) : null}

        <Findings findings={findings} lineErrors={lineErrors} />

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {w.cancel}
          </Button>
          <Button variant="outline" onClick={() => void check()} disabled={busy}>
            {w.check}
          </Button>
          <Button onClick={() => void save()} disabled={busy}>
            {w.save}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Findings({
  findings,
  lineErrors,
}: {
  findings: Finding[] | null;
  lineErrors: LineError[];
}) {
  const t = useDictionary();
  const w = t.sources.settings;
  const words = w as Record<string, string>;
  if (lineErrors.length > 0) {
    return (
      <ul role="alert" className="flex flex-col gap-1 text-sm text-state-danger">
        {lineErrors.map((e) => (
          <li key={`${e.field}-${e.line}`} className="flex items-center gap-2">
            <CircleAlert className="size-4" aria-hidden="true" />
            {fill(w.lineError, { field: words[e.field] ?? e.field, line: e.line })}
          </li>
        ))}
      </ul>
    );
  }
  if (findings === null) return null;
  if (findings.length === 0) return <p className="text-sm text-state-success">{w.checked}</p>;
  return (
    <ul role="status" className="flex flex-col gap-1 text-sm">
      {findings.map((f, index) => (
        <li
          key={`${f.path}-${index}`}
          className={
            f.level === "error" ? "flex gap-2 text-state-danger" : "flex gap-2 text-state-warning"
          }
        >
          {f.level === "error" ? (
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          ) : (
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          )}
          <span>
            <span className="font-medium">{f.level === "error" ? w.error : w.warning}</span> ·{" "}
            <code className="text-xs">{f.path}</code> — {f.message}
          </span>
        </li>
      ))}
    </ul>
  );
}
