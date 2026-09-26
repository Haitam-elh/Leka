/**
 * The knowledge components (LEKA-340): how an entity, its relationships,
 * where it came from and how far to trust it look, on every screen.
 *
 * Everything arrives by props — no component here fetches. See
 * docs/frontend/knowledge-components.md for which to use when.
 */

export { DependencyGraph, graphEdges, layeredPositions } from "./dependency-graph";
export type { DependencyGraphProps } from "./dependency-graph";
export { type Dependency, DependencyList } from "./dependency-list";
export type { DependencyListProps } from "./dependency-list";
export { EntityCard, EntityIcon, ENTITY_ICONS } from "./entity-card";
export type { EntityCardProps } from "./entity-card";
export {
  type EntityDetail,
  EntityDetailPanel,
  type EntityMetric,
  Sparkline,
} from "./entity-detail-panel";
export type { EntityDetailPanelProps } from "./entity-detail-panel";
export {
  EVENT_TYPES,
  EventTimeline,
  type TimelineEvent,
  type TimelineEventType,
} from "./event-timeline";
export type { EventTimelineProps } from "./event-timeline";
export {
  DEFAULT_FRESHNESS,
  type Freshness,
  FreshnessIndicator,
  freshnessOf,
  type FreshnessThresholds,
  QualityIndicator,
  qualityLevel,
} from "./indicators";
export { type KnowledgeColumn, KnowledgeTable } from "./knowledge-table";
export type { KnowledgeTableProps } from "./knowledge-table";
export { type MetadataItem, MetadataPanel, type MetadataSection } from "./metadata-panel";
export { ProvenanceBadge } from "./provenance-badge";
export {
  STATUS_VARIANTS,
  type StatusFamily,
  statusLabel,
  statusLook,
  type StatusVariant,
  TONES,
  type Tone,
} from "./status";
export { StatusBadge } from "./status-badge";
export type { StatusBadgeProps } from "./status-badge";
