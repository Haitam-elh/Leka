"use client";

import {
  CircleHelp,
  type LucideIcon,
  OctagonAlert,
  ScrollText,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { cn } from "cn";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { ConfidenceBadge } from "@/components/intelligence/confidence";
import { EvidenceButton, EvidenceList } from "@/components/intelligence/evidence";
import { Pill } from "@/components/intelligence/pill";
import { useDictionary } from "@/lib/i18n/locale-provider";
import {
  type CauseTag,
  causeTag,
  type EvidenceRef,
  type Finding,
  type ProbableCause,
} from "@/lib/intelligence";

/**
 * What is known, and what is thought (LEKA-341), as mockup 03's "Premiers
 * constats" draws them: a tinted line each — its icon, what it is about, a
 * tag saying what kind of statement it is, a line of explanation, and
 * "Voir les éléments" opening its evidence in place.
 *
 *     Constat          a fact: a source said it, LEKA observed it
 *     Cause déclarée   a source says it caused it
 *     Cause probable   LEKA thinks so, fairly sure — and says how sure
 *     À confirmer      LEKA only suspects it: someone should check
 *
 * A hypothesis is never written as a fact: its tag and its confidence go
 * with it wherever it is drawn.
 */

const ROW_TONES: Record<TileTone, string> = {
  danger: "border-state-danger/20 bg-linear-to-r from-state-danger-soft/70 to-white",
  warning: "border-state-warning/20 bg-linear-to-r from-state-warning-soft/70 to-white",
  info: "border-state-info/20 bg-linear-to-r from-state-info-soft/70 to-white",
  violet: "border-brand-violet/20 bg-linear-to-r from-brand-violet-soft/70 to-white",
  success: "border-shell-line bg-white",
  neutral: "border-shell-line bg-white",
};

const CAUSE_LOOK: Record<CauseTag, { icon: LucideIcon; tone: TileTone }> = {
  stated: { icon: OctagonAlert, tone: "danger" },
  probable: { icon: TriangleAlert, tone: "danger" },
  toConfirm: { icon: CircleHelp, tone: "violet" },
};

function InsightRow({
  icon,
  tone,
  title,
  href,
  tag,
  aside,
  description,
  evidence,
  testId,
}: {
  icon: LucideIcon;
  tone: TileTone;
  title: string;
  href?: string | null;
  tag: string;
  aside?: React.ReactNode;
  description?: React.ReactNode;
  evidence: readonly EvidenceRef[];
  testId: string;
}) {
  const [open, setOpen] = useState(false);
  const list = useId();
  return (
    <li className={cn("rounded-lg border p-3", ROW_TONES[tone])} data-testid={testId}>
      <div className="flex flex-wrap items-start gap-3 sm:flex-nowrap">
        <IconTile icon={icon} tone={tone} />
        <div className="min-w-0 flex-1 basis-48">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {href ? (
              <Link
                href={href}
                className="text-[0.9375rem] font-semibold text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {title}
              </Link>
            ) : (
              <span className="text-[0.9375rem] font-semibold text-brand-navy">{title}</span>
            )}
            <Pill tone={tone} data-testid="statement-tag">
              {tag}
            </Pill>
            {aside}
          </div>
          {description ? (
            <div className="mt-0.5 text-[0.8125rem] text-shell-muted">{description}</div>
          ) : null}
        </div>
        {evidence.length > 0 ? (
          <EvidenceButton
            count={evidence.length}
            open={open}
            controls={list}
            onClick={() => setOpen(!open)}
          />
        ) : null}
      </div>
      {open ? <EvidenceList id={list} items={evidence} className="mt-3 sm:ms-13" /> : null}
    </li>
  );
}

export function FindingList({ findings }: { findings: readonly Finding[] }) {
  const t = useDictionary();
  const w = t.intelligence;
  if (findings.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.findings.none}</p>;
  }
  return (
    <ul className="space-y-2" data-testid="findings">
      {findings.map((finding) => (
        <InsightRow
          key={finding.id}
          icon={ScrollText}
          tone="info"
          title={finding.title ?? finding.statement}
          tag={w.tags.fact}
          description={finding.title ? finding.statement : null}
          evidence={finding.evidence}
          testId="finding"
        />
      ))}
    </ul>
  );
}

export function ProbableCauseList({ causes }: { causes: readonly ProbableCause[] }) {
  const t = useDictionary();
  const w = t.intelligence;
  if (causes.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.causes.none}</p>;
  }
  return (
    <ol className="space-y-2" data-testid="probable-causes">
      {causes.map((cause) => {
        const tag = causeTag(cause);
        const { icon, tone } = CAUSE_LOOK[tag];
        return (
          <InsightRow
            key={cause.id}
            icon={icon}
            tone={tone}
            title={cause.label}
            href={cause.href}
            tag={w.tags[tag]}
            aside={<ConfidenceBadge score={cause.confidence} basis={cause.basis} />}
            description={
              <p>
                {cause.kind ? <span className="text-brand-navy">{cause.kind} · </span> : null}
                <span className="font-medium text-brand-navy">{w.causes.why} </span>
                {cause.why}
              </p>
            }
            evidence={cause.evidence}
            testId="probable-cause"
          />
        );
      })}
    </ol>
  );
}
