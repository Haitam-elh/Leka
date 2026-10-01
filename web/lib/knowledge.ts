/**
 * The shapes the knowledge components display (LEKA-340).
 *
 * The entity and relationship kinds MIRROR leka/knowledge/models.py. The
 * company model's routes (LEKA-361) put them in lib/api-types.ts as unions;
 * these are the same kinds as lists, which a union cannot be iterated as.
 * api/tests/test_knowledge_mirror.py fails if either side changes without
 * the other.
 *
 * Everything the backend does not know yet — an entity's operational
 * status, its owner, its metrics — is optional here. A component shows what
 * it is given and says nothing about what it is not.
 */

import type { SourceKind } from "@/lib/sources";

export const ENTITY_TYPES = [
  "service",
  "repository",
  "incident",
  "deployment",
  "person",
  "document",
  "infra_resource",
  "database",
  "team",
  "project",
  "issue",
  "pull_request",
  "commit",
  "release",
  "application",
  "environment",
  "cloud_account",
  "resource_group",
] as const;
export type EntityType = (typeof ENTITY_TYPES)[number];

export const RELATIONSHIP_TYPES = [
  "depends_on",
  "owns",
  "deployed_to",
  "mentions",
  "caused_by",
  "member_of",
  "part_of",
  "owned_by",
  "maintained_by",
  "authored_by",
  "assigned_to",
  "reviewed_by",
  "reported_by",
  "led_by",
  "affects",
  "resolves",
  "implements",
  "merges",
  "child_of",
  "in_network",
  "runs_in",
] as const;
export type RelationshipType = (typeof RELATIONSHIP_TYPES)[number];

/** The legend of mockup 10: Opérationnel, Attention, Incident, Non surveillé. */
export type EntityStatus = "operational" | "attention" | "incident" | "unmonitored" | "unknown";

/** Where a piece of knowledge came from. `kind` picks the logo. */
export interface Provenance {
  kind: SourceKind;
  /** The source's own name: "acme/backend", "OPS board". */
  name?: string;
  /** When LEKA last heard from it. ISO 8601. */
  syncedAt?: string | null;
}

export interface KnowledgeEntity {
  id: string;
  type: EntityType;
  name: string;
  description?: string;
  status?: EntityStatus;
  owner?: { name: string; role?: string };
  tags?: readonly string[];
  /** ISO 8601 — the entity's last_seen_at. */
  lastUpdated?: string | null;
  /** 0 to 1, as the backend stores it on every entity. */
  confidence?: number;
  source?: Provenance;
}

export interface KnowledgeRelationship {
  id: string;
  from: string;
  to: string;
  type: RelationshipType;
  /** Colours the edge: an incident travels along a dependency. */
  status?: EntityStatus;
  confidence?: number;
}

/** The mockups speak in percentages; the backend stores 0–1. */
export function confidenceToScore(confidence: number): number {
  return Math.round(Math.min(1, Math.max(0, confidence)) * 100);
}
