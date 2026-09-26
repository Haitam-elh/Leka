/**
 * Example data for the knowledge gallery — three shapes every component
 * must survive: complete (mockups 10 and 11, the Payment API incident),
 * partial (what the backend's EntityRead alone gives) and large (hundreds
 * of rows, a hundred-node graph). Development only, never shown to a
 * customer as theirs.
 */

import type { Dependency } from "@/components/knowledge/dependency-list";
import type { EntityDetail } from "@/components/knowledge/entity-detail-panel";
import { EVENT_TYPES, type TimelineEvent } from "@/components/knowledge/event-timeline";
import type {
  EntityStatus,
  EntityType,
  KnowledgeEntity,
  KnowledgeRelationship,
} from "@/lib/knowledge";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

export const PAYMENT_API: EntityDetail = {
  id: "svc-payment-api",
  type: "service",
  name: "Payment API",
  description: "Service de traitement des paiements qui gère l'ensemble du flux de transaction.",
  status: "incident",
  version: "v2.8.4",
  environment: "Production",
  owner: { name: "Thomas Martin", role: "Tech Lead · Payments" },
  tags: ["payments", "python", "critique"],
  lastUpdated: minutesAgo(4),
  confidence: 0.91,
  source: { kind: "datadog", name: "acme-eu", syncedAt: minutesAgo(4) },
  metrics: [
    {
      id: "p95",
      label: "Latence (p95)",
      value: "520 ms",
      delta: { value: "+68 %", direction: "up", good: false },
      series: [310, 305, 320, 300, 315, 330, 480, 505, 520],
    },
    {
      id: "errors",
      label: "Taux d'erreur",
      value: "4,2 %",
      delta: { value: "+3,1 %", direction: "up", good: false },
      series: [0.8, 0.9, 0.7, 1.1, 1.0, 2.8, 3.9, 4.2],
    },
    {
      id: "rpm",
      label: "Requêtes / min",
      value: "1 240",
      delta: { value: "−12 %", direction: "down", good: false },
      series: [1400, 1420, 1390, 1410, 1300, 1260, 1240],
    },
    {
      id: "uptime",
      label: "Disponibilité",
      value: "95,1 %",
      delta: { value: "−2,4 %", direction: "down", good: false },
      series: [99.9, 99.9, 99.8, 99.9, 97.5, 96.0, 95.1],
    },
  ],
  dependencies: [
    {
      entity: { id: "svc-auth", type: "service", name: "Auth Service" },
      direction: "upstream",
      status: "attention",
      detail: "Impacte la latence",
    },
    {
      entity: { id: "svc-user", type: "service", name: "User Service" },
      direction: "upstream",
      status: "operational",
      detail: "Aucun impact détecté",
    },
    {
      entity: { id: "svc-order", type: "service", name: "Order Service" },
      direction: "downstream",
      status: "attention",
      detail: "Temps de réponse",
    },
    {
      entity: { id: "svc-notif", type: "service", name: "Notification Service" },
      direction: "downstream",
      status: "operational",
      detail: "Aucun impact détecté",
    },
    {
      entity: { id: "db-payment", type: "database", name: "Payment DB" },
      direction: "upstream",
      status: "operational",
      detail: "Aucun impact détecté",
    },
  ],
  changes: [
    {
      id: "c1",
      type: "deployment",
      title: "Déploiement v2.8.4",
      subtitle: "GitHub · Commit a1b3c4d",
      at: minutesAgo(132),
    },
    {
      id: "c2",
      type: "change",
      title: "Modification de configuration",
      subtitle: "AWS · Parameter Store",
      at: minutesAgo(120),
    },
    {
      id: "c3",
      type: "leka_analysis",
      title: "Analyse LEKA terminée",
      subtitle: "Pourquoi l'API de paiement est-elle lente ?",
      at: minutesAgo(30),
    },
  ],
  incidents: [
    {
      id: "i1",
      type: "incident",
      title: "Incident INC-2841",
      subtitle: "Jira · Ticket",
      at: minutesAgo(127),
    },
    {
      id: "i2",
      type: "health_change",
      title: "Hausse de la latence (p95)",
      subtitle: "Datadog · Alerte",
      at: minutesAgo(129),
    },
  ],
  sections: [
    {
      title: "Informations générales",
      items: [
        { label: "Environnement", value: "Production" },
        { label: "Version actuelle", value: "v2.8.4", copyValue: "v2.8.4" },
        { label: "Infrastructure", value: "EKS · AWS (eu-west-1)" },
        { label: "Données", value: "PostgreSQL (500 Go)" },
        { label: "Runbook", value: null },
      ],
    },
  ],
};

/** What the backend's EntityRead alone gives: no status, no owner, no metrics. */
export const BARE: KnowledgeEntity = {
  id: "repo-backend",
  type: "repository",
  name: "acme/backend",
  lastUpdated: minutesAgo(60 * 30),
  confidence: 0.64,
  source: { kind: "github", name: "acme/backend", syncedAt: minutesAgo(60 * 30) },
};

const MAP: [string, EntityType, string, EntityStatus][] = [
  ["users", "person", "Utilisateurs", "operational"],
  ["web", "service", "Web App", "operational"],
  ["mobile", "service", "Mobile App", "operational"],
  ["backoffice", "service", "Backoffice", "attention"],
  ["auth", "service", "Auth Service", "attention"],
  ["user", "service", "User Service", "operational"],
  ["payment", "service", "Payment API", "incident"],
  ["order", "service", "Order Service", "operational"],
  ["notif", "service", "Notification", "operational"],
  ["userdb", "database", "User DB", "operational"],
  ["paydb", "database", "Payment DB", "operational"],
  ["orderdb", "database", "Order DB", "attention"],
  ["aws", "infra_resource", "AWS eu-west-1", "operational"],
  ["gcp", "infra_resource", "Google Cloud", "operational"],
  ["stripe", "infra_resource", "Stripe", "unmonitored"],
];

/** Mockup 10's map, trimmed. */
export const MAP_ENTITIES: KnowledgeEntity[] = MAP.map(([id, type, name, status]) => ({
  id,
  type,
  name,
  status,
}));

const link = (
  from: string,
  to: string,
  status?: EntityStatus,
  type: KnowledgeRelationship["type"] = "depends_on",
): KnowledgeRelationship => ({ id: `${from}-${to}`, from, to, type, status });

export const MAP_LINKS: KnowledgeRelationship[] = [
  link("users", "web", "operational"),
  link("users", "mobile", "operational"),
  link("users", "backoffice", "attention"),
  link("web", "auth", "operational"),
  link("web", "payment", "incident"),
  link("mobile", "user", "operational"),
  link("backoffice", "order", "operational"),
  link("payment", "auth", "attention"),
  link("payment", "paydb", "incident"),
  link("order", "orderdb", "attention"),
  link("order", "notif", "operational"),
  link("user", "userdb", "operational"),
  link("userdb", "aws", undefined, "deployed_to"),
  link("paydb", "aws", undefined, "deployed_to"),
  link("orderdb", "gcp", undefined, "deployed_to"),
  link("payment", "stripe", "unmonitored"),
];

const TYPES: EntityType[] = ["service", "service", "database", "repository", "infra_resource"];
const STATUSES: EntityStatus[] = [
  "operational",
  "operational",
  "operational",
  "attention",
  "incident",
  "unmonitored",
];

/** A hundred and twenty nodes: the graph must stay usable. */
export const LARGE_ENTITIES: KnowledgeEntity[] = Array.from({ length: 120 }, (_, i) => ({
  id: `n-${i}`,
  type: TYPES[i % TYPES.length],
  name: `${TYPES[i % TYPES.length] === "database" ? "db" : "svc"}-${String(i).padStart(3, "0")}`,
  status: STATUSES[i % STATUSES.length],
}));

export const LARGE_LINKS: KnowledgeRelationship[] = LARGE_ENTITIES.slice(1).map((entity, i) =>
  link(LARGE_ENTITIES[Math.floor(i / 3)].id, entity.id, entity.status),
);

/** Five hundred rows for the table. */
export const ROWS = Array.from({ length: 500 }, (_, i) => ({
  id: `svc-${i}`,
  name: `service-${String(i).padStart(3, "0")}`,
  type: TYPES[i % TYPES.length],
  status: STATUSES[i % STATUSES.length],
  confidence: ((i * 37) % 100) / 100,
  lastUpdated: minutesAgo((i * 97) % (60 * 24 * 10)),
}));

export const MANY_DEPENDENCIES: Dependency[] = Array.from({ length: 60 }, (_, i) => ({
  entity: { id: `d-${i}`, type: "service", name: `dependency-${i}` },
  direction: i % 2 ? "downstream" : "upstream",
  status: STATUSES[i % STATUSES.length],
}));

export const MANY_EVENTS: TimelineEvent[] = Array.from({ length: 500 }, (_, i) => ({
  id: `e-${i}`,
  type: EVENT_TYPES[i % EVENT_TYPES.length],
  title: `Événement ${i}`,
  subtitle: "GitHub · push",
  at: minutesAgo(i * 13),
}));
