"use client";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Clock,
  CornerDownLeft,
  Database,
  ExternalLink,
  Layers,
  Radio,
  Server,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";
import { PageContainer } from "@/components/shell/page-container";
import { routes } from "@/config/routes";

interface DecisionItem {
  id: string;
  title: string;
  status: "validate" | "conflict";
  statusLabel: string;
  description: string;
  meta: string;
  actionLabel: string;
  href: string;
}

const DECISIONS: DecisionItem[] = [
  {
    id: "pay-api",
    title: "Schéma API Paiements",
    status: "validate",
    statusLabel: "À valider",
    description: "Modifications proposées par l'agent Contrats : Confiance 95 %",
    meta: "Requis pour release v2.4",
    actionLabel: "Examiner",
    href: routes.approvals(),
  },
  {
    id: "pg-conflict",
    title: "Conflit version PostgreSQL",
    status: "conflict",
    statusLabel: "Conflit",
    description: "Incohérence détectée entre Dockerfile (v15) et Helm chart (v16)",
    meta: "Impact 2 déploiements",
    actionLabel: "Arbitrer",
    href: routes.approvals(),
  },
  {
    id: "iam-merge",
    title: "Fusion services IAM",
    status: "validate",
    statusLabel: "À valider",
    description: "Rapprochement d'annuaires recommandé : Confiance 88 %",
    meta: "Sécurité & accès",
    actionLabel: "Examiner",
    href: routes.approvals(),
  },
];

export function OperationalOverview() {
  const [prompt, setPrompt] = useState("");

  return (
    <PageContainer>
      <div className="space-y-6 py-2">
        {/* Hero : Question et compositeur d'intention */}
        <section aria-labelledby="overview-hero-heading" className="space-y-3">
          <h1
            id="overview-hero-heading"
            className="text-2xl font-bold tracking-tight text-brand-navy md:text-3xl"
          >
            Que voulez-vous accomplir aujourd&apos;hui ?
          </h1>
          <p className="max-w-3xl text-sm text-shell-muted">
            Formulez une intention technique, interrogez le jumeau numérique ou déclenchez une analyse ciblée sur l&apos;ensemble de votre écosystème.
          </p>

          <div className="relative mt-2 rounded-xl border border-shell-line bg-white p-2 shadow-sm transition-focus focus-within:border-brand-violet focus-within:ring-2 focus-within:ring-brand-violet/20">
            <div className="flex items-center gap-2 px-2">
              <span className="text-lg font-light text-brand-violet">+</span>
              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ex. Analyser la résilience de la passerelle API et l'impact de PostgreSQL 16..."
                className="w-full bg-transparent text-sm text-brand-navy placeholder:text-shell-muted focus:outline-none"
              />
              <div className="flex shrink-0 items-center gap-2">
                <span className="hidden text-xs text-shell-muted md:inline">
                  Appuyez sur <kbd className="rounded border border-shell-line bg-shell-canvas px-1 text-[10px]">↵</kbd> pour soumettre
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-brand-violet px-3.5 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-brand-violet/90"
                >
                  Lancer l&apos;analyse
                </button>
              </div>
            </div>
          </div>

          {/* Ruban synthétique */}
          <div className="flex flex-wrap items-center gap-4 text-xs text-shell-muted">
            <div className="flex items-center gap-1.5">
              <Clock className="size-3.5 text-shell-nav-active" aria-hidden="true" />
              <span>Historique des intentions : <strong className="font-semibold text-brand-navy">14 terminées</strong></span>
            </div>
            <span className="text-shell-line">•</span>
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="size-3.5 text-state-success" aria-hidden="true" />
              <span><strong className="font-semibold text-brand-navy">2/2</strong> étapes configurées</span>
            </div>
            <span className="text-shell-line">•</span>
            <div className="flex items-center gap-1.5">
              <Radio className="size-3.5 text-state-success" aria-hidden="true" />
              <span><strong className="font-semibold text-brand-navy">8</strong> sources actives</span>
            </div>
          </div>
        </section>

        {/* Carte principale : Mon environnement - Jumeau numérique */}
        <section
          aria-labelledby="env-twin-title"
          className="rounded-2xl border border-shell-line bg-white p-5 shadow-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-shell-line pb-4">
            <div className="flex items-center gap-2">
              <div className="flex size-7 items-center justify-center rounded-lg bg-brand-violet-soft text-brand-violet">
                <Layers className="size-4" aria-hidden="true" />
              </div>
              <h2 id="env-twin-title" className="text-base font-semibold text-brand-navy">
                Mon environnement : Jumeau numérique
              </h2>
            </div>
            <Link
              href={routes.environment()}
              className="inline-flex items-center gap-1 text-xs font-medium text-shell-nav-active hover:underline"
            >
              Explorer la cartographie
              <ChevronRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
            </Link>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Indicateur circulaire et santé globale */}
            <div className="flex items-center gap-4 lg:col-span-4">
              <div className="flex size-16 shrink-0 items-center justify-center rounded-full border-4 border-state-success/30 bg-state-success-soft text-base font-bold tabular-nums text-state-success">
                94 %
              </div>
              <div className="space-y-0.5">
                <div className="inline-flex items-center gap-1.5 rounded-full bg-state-success-soft px-2.5 py-0.5 text-xs font-semibold text-state-success">
                  <span className="size-1.5 rounded-full bg-state-success" aria-hidden="true" />
                  Santé globale stable
                </div>
                <p className="text-xs text-shell-muted">
                  Dernière synchronisation : il y a 8 min (14:28)
                </p>
              </div>
            </div>

            {/* 3 colonnes de métriques */}
            <div className="grid grid-cols-3 divide-x divide-shell-line border-t border-shell-line pt-4 lg:col-span-8 lg:border-t-0 lg:pt-0">
              <div className="px-3 first:pl-0">
                <span className="block text-[11px] font-semibold tracking-wider text-shell-muted uppercase">
                  Services surveillés
                </span>
                <span className="mt-1 block text-base font-bold text-brand-navy">
                  42 applications
                </span>
              </div>
              <div className="px-3">
                <span className="block text-[11px] font-semibold tracking-wider text-shell-muted uppercase">
                  Infrastructure
                </span>
                <span className="mt-1 block text-base font-bold text-brand-navy">
                  4 clusters nominaux
                </span>
              </div>
              <div className="px-3">
                <span className="block text-[11px] font-semibold tracking-wider text-shell-muted uppercase">
                  Sources de données
                </span>
                <span className="mt-1 block text-base font-bold text-brand-navy">
                  8/8 synchronisées
                </span>
              </div>
            </div>
          </div>

          {/* Bandeau de couverture */}
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-shell-canvas p-2.5 text-xs text-shell-muted">
            <CheckCircle2 className="size-4 shrink-0 text-state-success" aria-hidden="true" />
            <span>
              <strong className="font-medium text-brand-navy">Couverture 100 %</strong> : GitHub, Jira, AWS, Kubernetes, Confluence et Datadog sont actifs sans anomalie.
            </span>
          </div>
        </section>

        {/* Grille opérationnelle inférieure : Activité et Décisions */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Activité récente de l'infrastructure */}
          <section
            aria-labelledby="recent-activity-title"
            className="flex flex-col rounded-2xl border border-shell-line bg-white p-5 shadow-sm"
          >
            <div className="flex items-center justify-between border-b border-shell-line pb-3">
              <div className="flex items-center gap-2">
                <Server className="size-4 text-brand-violet" aria-hidden="true" />
                <h2 id="recent-activity-title" className="text-base font-semibold text-brand-navy">
                  Activité récente de l&apos;infrastructure
                </h2>
              </div>
              <Link
                href={routes.activity()}
                className="inline-flex items-center gap-1 text-xs font-medium text-shell-nav-active hover:underline"
              >
                Tout l&apos;historique
                <ChevronRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
              </Link>
            </div>

            <div className="mt-3 flex-1 space-y-3">
              <div className="flex items-start justify-between gap-3 rounded-lg border border-shell-line bg-shell-canvas/50 p-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-brand-navy">
                      Synchronisation GitHub (api-core)
                    </span>
                  </div>
                  <p className="text-xs text-shell-muted">
                    14 nouveaux commits analysés : Dépendances vérifiées sans faille
                  </p>
                </div>
                <div className="text-right">
                  <span className="block text-xs font-medium text-brand-navy">14:28</span>
                  <span className="text-[11px] text-shell-nav-active">Action</span>
                </div>
              </div>
            </div>
          </section>

          {/* Décisions à trancher */}
          <section
            aria-labelledby="pending-decisions-title"
            className="flex flex-col rounded-2xl border border-shell-line bg-white p-5 shadow-sm"
          >
            <div className="flex items-center justify-between border-b border-shell-line pb-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-brand-violet" aria-hidden="true" />
                <h2 id="pending-decisions-title" className="text-base font-semibold text-brand-navy">
                  Décisions à trancher
                </h2>
                <span className="rounded-full bg-state-warning-soft px-2 py-0.5 text-xs font-semibold text-state-warning">
                  3 en attente
                </span>
              </div>
            </div>

            <ul className="mt-3 space-y-3">
              {DECISIONS.map((item) => (
                <li
                  key={item.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-shell-line bg-white p-3 shadow-xs hover:border-brand-violet/40"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-brand-navy">{item.title}</span>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.2 text-[10px] font-semibold",
                          item.status === "conflict"
                            ? "bg-state-danger-soft text-state-danger"
                            : "bg-state-warning-soft text-state-warning",
                        )}
                      >
                        {item.statusLabel}
                      </span>
                    </div>
                    <p className="text-xs text-shell-muted">{item.description}</p>
                    <p className="text-[11px] font-medium text-shell-accent-muted">{item.meta}</p>
                  </div>

                  <Link
                    href={item.href}
                    className="mt-1 inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-shell-nav-active hover:underline"
                  >
                    {item.actionLabel}
                    <ChevronRight className="size-3 rtl:-scale-x-100" aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </PageContainer>
  );
}
