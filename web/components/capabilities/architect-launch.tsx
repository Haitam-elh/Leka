"use client";

import { Lock, Network, Plug, Rocket } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { BackHome, PageContainer } from "@/components/shell/page-container";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { agentRuns } from "@/lib/agent-runs";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { BUDGET } from "@/lib/context";
import { intentions } from "@/lib/intentions/api";
import { notify } from "@/lib/notify";
import { flattened, useSourceTree } from "@/lib/source-tree";
import { useSources } from "@/lib/sources-queries";

/**
 * « Lancer » the application architect (2026-10-25): its perimeter chosen —
 * a Confluence source, a space, a page and everything under it, or the
 * whole space —, the subject it documents first; then an intention asked
 * in its words (« /architecte … ») and the architect started on it, read
 * only. The dossier, structured as ArchiMate, is delivered on the
 * intention's deliverable: PDF, Word, Markdown, each section citing its
 * pages.
 */

export const ARCHITECT = "application-architecture";

const FIELD =
  "h-9 w-full rounded-lg border border-shell-line bg-white px-2.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

export function ArchitectLaunch() {
  const t = useDictionary();
  const w = t.catalogue.architectLaunch;
  const router = useRouter();
  const asked = useSearchParams();
  const listed = useSources().data;
  const confluences = (listed ?? []).filter((source) => source.type === "confluence");
  const [sourceId, setSourceId] = useState<string | null>(asked?.get("source") ?? null);
  const chosenSource = confluences.find((s) => s.id === sourceId) ?? confluences[0] ?? null;
  const tree = useSourceTree(chosenSource?.id ?? null);
  const spaces = tree.data?.spaces ?? [];
  const [spaceKey, setSpaceKey] = useState<string | null>(asked?.get("space") ?? null);
  const space = spaces.find((s) => s.key === spaceKey) ?? spaces[0] ?? null;
  const [root, setRoot] = useState("");
  const [subject, setSubject] = useState("");
  const [perimeter, setPerimeter] = useState("");
  const [busy, setBusy] = useState(false);

  // A space chosen: its name as the subject and the perimeter, unless typed.
  useEffect(() => {
    if (!space) return;
    setSubject((said) => said || space.name);
    setPerimeter((said) => said || fill(w.perimeterSaid, { space: space.name }));
  }, [space, w.perimeterSaid]);

  const pages = space ? flattened(space.nodes) : [];
  const rootPage = pages.find(({ node }) => node.id === root)?.node ?? null;

  async function launch() {
    if (!space || !subject.trim() || !perimeter.trim()) return;
    setBusy(true);
    try {
      const text = fill(w.asked, {
        subject: subject.trim(),
        space: space.key,
        root: rootPage ? fill(w.rootSaid, { title: rootPage.title }) : "",
      });
      const created = await intentions.create(
        { text: text.slice(0, 2000), limit: BUDGET },
        `architect-${space.key}-${root || "all"}-${Date.now()}`,
      );
      const run = await agentRuns.start({
        key: ARCHITECT,
        inputs: {
          parcours: subject.trim(),
          perimetre: perimeter.trim(),
          espace: space.key,
          ...(root ? { page_racine: root } : {}),
        },
        intention_id: created.intention.id,
      });
      router.push(`${routes.intention(created.intention.id, "deliverable")}?run=${encodeURIComponent(run.id)}`);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
      setBusy(false);
    }
  }

  return (
    <PageContainer>
      <BackHome />
      <div className="mx-auto flex max-w-3xl flex-col gap-5" data-testid="architect-launch">
        <header className="flex items-start gap-4">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-brand-violet-soft text-shell-nav-active">
            <Network className="size-6" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-[1.75rem] leading-tight font-bold text-brand-navy">{w.title}</h1>
            <p className="mt-1 text-[0.9375rem] text-shell-muted">{w.lead}</p>
          </div>
        </header>

        {listed && !confluences.length ? (
          <section className="rounded-xl border border-shell-line bg-white p-5" data-testid="architect-no-source">
            <p className="text-[0.9375rem] text-brand-navy">{w.noSource}</p>
            <Link href={`${routes.sources()}?connect=confluence`} className={buttonVariants({ className: "mt-3" })}>
              <Plug aria-hidden="true" />
              {w.connect}
            </Link>
          </section>
        ) : (
          <form
            className="flex flex-col gap-4 rounded-xl border border-shell-line bg-white p-5"
            onSubmit={(event) => {
              event.preventDefault();
              void launch();
            }}
          >
            {confluences.length > 1 ? (
              <label className="flex flex-col gap-1 text-[0.8125rem] font-medium text-brand-navy">
                {w.source}
                <select
                  className={FIELD}
                  value={chosenSource?.id ?? ""}
                  onChange={(event) => {
                    setSourceId(event.target.value);
                    setSpaceKey(null);
                    setRoot("");
                  }}
                  data-testid="architect-source"
                >
                  {confluences.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.display_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-[0.8125rem] font-medium text-brand-navy">{w.space}</legend>
              {tree.data && !spaces.length ? (
                <p className="text-[0.8125rem] text-shell-muted" data-testid="architect-no-space">
                  {w.noSpace}
                </p>
              ) : null}
              {spaces.map((one) => (
                <label
                  key={one.key}
                  className="flex cursor-pointer items-center gap-3 rounded-lg border border-shell-line px-3 py-2 has-checked:border-brand-violet has-checked:bg-brand-violet-soft/40"
                  data-testid="architect-space"
                  data-key={one.key}
                >
                  <input
                    type="radio"
                    name="space"
                    value={one.key}
                    checked={space?.key === one.key}
                    onChange={() => {
                      setSpaceKey(one.key);
                      setRoot("");
                      setSubject(one.name);
                      setPerimeter(fill(w.perimeterSaid, { space: one.name }));
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-brand-navy">
                      {one.name} <span className="font-normal text-shell-muted">({one.key})</span>
                    </span>
                    <span className="text-xs text-shell-muted">
                      {fill(w.pages, { count: one.pages, depth: one.depth })}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>

            {space ? (
              <>
                <label className="flex flex-col gap-1 text-[0.8125rem] font-medium text-brand-navy">
                  {w.root}
                  <select
                    className={FIELD}
                    value={root}
                    onChange={(event) => setRoot(event.target.value)}
                    data-testid="architect-root"
                  >
                    <option value="">{w.rootAll}</option>
                    {pages.map(({ node, depth }) => (
                      <option key={node.id} value={node.id}>
                        {`${"  ".repeat(depth)}${depth ? "└ " : ""}${node.title}`}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-[0.8125rem] font-medium text-brand-navy">
                  {w.subject}
                  <input
                    className={FIELD}
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                    required
                    maxLength={200}
                    data-testid="architect-subject"
                  />
                  <span className="text-xs font-normal text-shell-muted">{w.subjectHint}</span>
                </label>
                <label className="flex flex-col gap-1 text-[0.8125rem] font-medium text-brand-navy">
                  {w.perimeter}
                  <input
                    className={FIELD}
                    value={perimeter}
                    onChange={(event) => setPerimeter(event.target.value)}
                    required
                    maxLength={200}
                    data-testid="architect-perimeter"
                  />
                </label>
              </>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={!space || busy} data-testid="architect-launch-submit">
                <Rocket aria-hidden="true" />
                {busy ? w.launching : w.launch}
              </Button>
              <span className="inline-flex items-center gap-1.5 text-xs text-shell-muted">
                <Lock className="size-3.5" aria-hidden="true" />
                {w.readOnly}
              </span>
            </div>
          </form>
        )}
      </div>
    </PageContainer>
  );
}
