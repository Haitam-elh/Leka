"use client";

import { useState } from "react";

import {
  DependencyGraph,
  DependencyList,
  EntityCard,
  EntityDetailPanel,
  EventTimeline,
  FreshnessIndicator,
  KnowledgeTable,
  type KnowledgeColumn,
  MetadataPanel,
  ProvenanceBadge,
  QualityIndicator,
  STATUS_VARIANTS,
  StatusBadge,
} from "@/components/knowledge";
import { Button } from "@/components/ui/button";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { confidenceToScore } from "@/lib/knowledge";

import {
  BARE,
  LARGE_ENTITIES,
  LARGE_LINKS,
  MANY_DEPENDENCIES,
  MANY_EVENTS,
  MAP_ENTITIES,
  MAP_LINKS,
  PAYMENT_API,
  ROWS,
} from "./fixtures";

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 rounded-xl border border-shell-line bg-white p-5">
      <h2 className="text-sm font-semibold tracking-wide text-shell-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-shell-muted">{label}</p>
      {children}
    </div>
  );
}

type Row = (typeof ROWS)[number];

export function KnowledgeGallery() {
  const t = useDictionary();
  const [selected, setSelected] = useState<string>("payment");

  const columns: KnowledgeColumn<Row>[] = [
    { id: "name", header: "Nom", cell: (row) => row.name, sortValue: (row) => row.name },
    {
      id: "type",
      header: "Type",
      cell: (row) => t.knowledge.entityTypes[row.type],
      sortValue: (row) => t.knowledge.entityTypes[row.type],
    },
    {
      id: "status",
      header: "Statut",
      cell: (row) => <StatusBadge variant={`entity.${row.status}`} size="sm" />,
      sortValue: (row) => row.status,
    },
    {
      id: "quality",
      header: "Qualité",
      cell: (row) => <QualityIndicator score={confidenceToScore(row.confidence)} />,
      sortValue: (row) => row.confidence,
    },
    {
      id: "freshness",
      header: "Fraîcheur",
      cell: (row) => <FreshnessIndicator lastUpdated={row.lastUpdated} showLabel={false} />,
      sortValue: (row) => row.lastUpdated,
    },
  ];

  const families = [...new Set(STATUS_VARIANTS.map((variant) => variant.split(".")[0]))];

  return (
    <main className="mx-auto max-w-6xl space-y-6 bg-shell-page p-8">
      <header>
        <h1 className="text-2xl font-bold text-brand-navy">Composants knowledge — LEKA-340</h1>
        <p className="text-sm text-shell-muted">
          Chaque composant avec des données complètes, partielles, vides et volumineuses. Données
          d&apos;exemple, inspirées des maquettes 10 et 11.
        </p>
      </header>

      <Section title="StatusBadge — tous les états">
        {families.map((family) => (
          <div key={family} className="flex flex-wrap items-center gap-2">
            <span className="w-20 text-xs text-shell-muted">{family}</span>
            {STATUS_VARIANTS.filter((variant) => variant.startsWith(`${family}.`)).map(
              (variant) => (
                <StatusBadge key={variant} variant={variant} />
              ),
            )}
          </div>
        ))}
        <Labelled label="Avec une pastille, en petit (légendes, nœuds)">
          <div className="flex flex-wrap gap-2">
            {(["operational", "attention", "incident", "unmonitored"] as const).map((status) => (
              <StatusBadge key={status} variant={`entity.${status}`} dot size="sm" />
            ))}
          </div>
        </Labelled>
      </Section>

      <Section title="Qualité, fraîcheur, provenance">
        <div className="flex flex-wrap items-center gap-4">
          <QualityIndicator score={32} />
          <QualityIndicator score={65} />
          <QualityIndicator score={92} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FreshnessIndicator lastUpdated={hoursAgo(0.2)} />
          <FreshnessIndicator lastUpdated={hoursAgo(30)} />
          <FreshnessIndicator lastUpdated={hoursAgo(24 * 9)} />
          <FreshnessIndicator lastUpdated={null} />
          <FreshnessIndicator
            lastUpdated={hoursAgo(3)}
            thresholds={{ agingAfterHours: 1, staleAfterHours: 2 }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ProvenanceBadge
            source={{ kind: "github", name: "acme/backend", syncedAt: hoursAgo(0.1) }}
            quality={91}
          />
          <ProvenanceBadge source={{ kind: "jira", name: "OPS board", syncedAt: hoursAgo(40) }} />
          <ProvenanceBadge source={{ kind: "confluence" }} />
          <ProvenanceBadge source={{ kind: "aws", syncedAt: hoursAgo(1) }} showLabel={false} />
        </div>
      </Section>

      <Section title="EntityCard">
        <div className="grid gap-4 md:grid-cols-2">
          <Labelled label="Complète, cliquable">
            <EntityCard {...PAYMENT_API} onClick={() => undefined} />
          </Labelled>
          <Labelled label="Partielle : ce que l'API donne seule">
            <EntityCard {...BARE} />
          </Labelled>
          <Labelled label="Compacte, sélectionnée">
            <EntityCard {...PAYMENT_API} compact selected onClick={() => undefined} />
          </Labelled>
          <Labelled label="Nom très long">
            <EntityCard
              id="long"
              type="document"
              name="Runbook — procédure de retour arrière de la base de paiement en cas d'incident majeur"
              status="unmonitored"
            />
          </Labelled>
        </div>
      </Section>

      <Section title="DependencyList et EventTimeline">
        <div className="grid gap-6 md:grid-cols-2">
          <Labelled label="Dépendances (maquette 11)">
            <DependencyList items={PAYMENT_API.dependencies ?? []} onSelect={() => undefined} />
          </Labelled>
          <Labelled label="Derniers événements">
            <EventTimeline
              events={[...(PAYMENT_API.changes ?? []), ...(PAYMENT_API.incidents ?? [])]}
            />
          </Labelled>
          <Labelled label="60 dépendances, 5 visibles">
            <DependencyList items={MANY_DEPENDENCIES} />
          </Labelled>
          <Labelled label="500 événements, compact, 6 visibles">
            <EventTimeline events={MANY_EVENTS} compact maxVisible={6} />
          </Labelled>
          <Labelled label="Vides">
            <DependencyList items={[]} />
            <EventTimeline events={[]} />
          </Labelled>
        </div>
      </Section>

      <Section title="MetadataPanel">
        <div className="grid gap-6 md:grid-cols-2">
          <MetadataPanel sections={PAYMENT_API.sections ?? []} copyable />
          <MetadataPanel
            columns={2}
            sections={[
              {
                title: "Déploiement",
                items: [
                  { label: "Cluster", value: "eks-prod" },
                  { label: "Région", value: "eu-west-1" },
                ],
              },
              {
                title: "Données",
                items: [
                  { label: "Moteur", value: "PostgreSQL 16" },
                  { label: "Taille", value: "500 Go" },
                ],
              },
            ]}
          />
        </div>
      </Section>

      <Section title="KnowledgeTable">
        <Labelled label="500 lignes, triées et paginées dans le navigateur">
          <KnowledgeTable
            caption="Services de l'exemple"
            columns={columns}
            rows={ROWS}
            rowKey={(row) => row.id}
            onRowClick={() => undefined}
          />
        </Labelled>
        <div className="grid gap-6 md:grid-cols-2">
          <Labelled label="Chargement">
            <KnowledgeTable
              caption="Chargement"
              columns={columns}
              rows={[]}
              rowKey={(row) => row.id}
              loading
            />
          </Labelled>
          <Labelled label="Vide, avec la marche à suivre">
            <KnowledgeTable
              caption="Vide"
              columns={columns}
              rows={[]}
              rowKey={(row) => row.id}
              empty={{
                title: "Aucun service découvert",
                description: "Connectez une source pour que LEKA cartographie vos services.",
                action: <Button variant="outline">Ajouter une source</Button>,
              }}
            />
          </Labelled>
        </div>
      </Section>

      <Section title="EntityDetailPanel">
        <Labelled label="Pleine page (maquette 11)">
          <EntityDetailPanel
            entity={PAYMENT_API}
            mode="full"
            onAskLeka={() => undefined}
            onSelectEntity={() => undefined}
          />
        </Labelled>
        <div className="max-w-md">
          <Labelled label="Panneau latéral, données partielles">
            <EntityDetailPanel entity={BARE} onClose={() => undefined} />
          </Labelled>
        </div>
      </Section>

      <Section title="DependencyGraph">
        <Labelled label="Cartographie (maquette 10) — cliquez un nœud">
          <DependencyGraph
            entities={MAP_ENTITIES}
            relationships={MAP_LINKS}
            selectedId={selected}
            onNodeClick={setSelected}
            height={560}
          />
        </Labelled>
        <Labelled label="120 nœuds">
          <DependencyGraph entities={LARGE_ENTITIES} relationships={LARGE_LINKS} height={420} />
        </Labelled>
        <Labelled label="Vide">
          <DependencyGraph entities={[]} relationships={[]} />
        </Labelled>
      </Section>
    </main>
  );
}
