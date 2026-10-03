/**
 * LEKA's own architecture, as GET /knowledge/architecture answers it: the
 * tests' (architecture.test.tsx, environment.test.tsx,
 * graph-explorer.test.tsx). Its repository and what its code runs — a
 * proxy, a web app, the API, a worker — its PostgreSQL and Redis, the AWS
 * machine and RDS they run on, OVH's mail outside. The API's state is
 * deduced: nothing watches it, its machine runs.
 */

import type {
  Architecture,
  ArchitectureBundle,
  ArchitectureCard,
  ArchitectureLink,
} from "@/lib/knowledge-graph";

export const REPO = "10000000-0000-4000-8000-000000000001";
export const CADDY = "10000000-0000-4000-8000-000000000002";
export const WEB = "10000000-0000-4000-8000-000000000003";
export const API = "10000000-0000-4000-8000-000000000004";
export const WORKER = "10000000-0000-4000-8000-000000000005";
export const POSTGRES = "10000000-0000-4000-8000-000000000006";
export const REDIS = "10000000-0000-4000-8000-000000000007";
export const BOX = "10000000-0000-4000-8000-000000000008";
export const RDS = "10000000-0000-4000-8000-000000000009";
export const OVH = "10000000-0000-4000-8000-00000000000a";

export function card(
  id: string,
  column: string,
  kind: string,
  name: string,
  more: Partial<ArchitectureCard> = {},
): ArchitectureCard {
  const type =
    column === "code"
      ? "repository"
      : column === "data"
        ? "database"
        : column === "cloud"
          ? kind === "database"
            ? "database"
            : "infra_resource"
          : "service";
  return {
    id,
    column,
    group: column === "code" ? "github" : column === "cloud" ? "aws" : column,
    kind,
    type,
    name,
    entity_id: id,
    key: `${type}:${name.toLowerCase()}`,
    status: column === "code" ? null : "operational",
    deduced: false,
    why: null,
    technology: [],
    description: null,
    environment: column === "code" ? null : "production",
    region: column === "cloud" ? "eu-central-1" : null,
    url: null,
    team: null,
    repository_id: null,
    host_id: null,
    deployment: null,
    stats: {},
    evidence: [],
    sources: column === "cloud" ? ["aws"] : ["github"],
    ...more,
  };
}

function link(
  from: string,
  role: string,
  to: string,
  more: Partial<ArchitectureLink> = {},
): ArchitectureLink {
  return {
    from_id: from,
    to_id: to,
    role,
    origin: "stated",
    confidence: 0.9,
    evidence: null,
    status: "operational",
    ...more,
  };
}

function bundle(
  from: string,
  column: string,
  roles: string[],
  targets: string[],
): ArchitectureBundle {
  return { from_id: from, column, role: roles[0], roles, targets };
}

function group(column: string, name: string, total: number) {
  return { id: `${column}:${name}`, column, name, regions: [], total, shown: total };
}

export const ARCHITECTURE: Architecture = {
  built_at: new Date().toISOString(),
  environment: null,
  environments: ["production"],
  groups: [
    group("code", "github", 1),
    group("services", "services", 4),
    group("data", "data", 2),
    { ...group("cloud", "aws", 2), regions: ["eu-central-1"] },
    group("external", "external", 1),
  ],
  cards: [
    card(REPO, "code", "repository", "Haitam-elh/Leka", {
      url: "https://github.com/haitam-elh/leka",
      stats: { commits: 247, pull_requests: 12 },
    }),
    card(CADDY, "services", "proxy", "Leka Caddy", { technology: ["Caddy"] }),
    card(WEB, "services", "web", "Leka Web", {
      technology: ["TypeScript", "Next.js"],
      status: "attention",
      url: "https://leka-core.com",
    }),
    card(API, "services", "api", "Leka API", {
      technology: ["Python", "FastAPI"],
      deduced: true,
      why: "leka-prod is running; its last deployment succeeded",
      url: "https://api.leka-core.com",
      repository_id: REPO,
      host_id: BOX,
      deployment: "succeeded",
      evidence: ["deploy/docker-compose.production.yml:24 — api"],
    }),
    card(WORKER, "services", "worker", "Leka Worker", {
      technology: ["Python", "RQ"],
      status: "incident",
    }),
    card(POSTGRES, "data", "database", "PostgreSQL", {
      technology: ["PostgreSQL"],
      host_id: RDS,
      stats: { tables: 36, size_bytes: 2_400_000 },
    }),
    card(REDIS, "data", "cache", "Redis", { technology: ["Redis"] }),
    card(BOX, "cloud", "instance", "leka-prod"),
    card(RDS, "cloud", "database", "leka", { technology: ["PostgreSQL"] }),
    card(OVH, "external", "email", "OVH (e-mail)", { status: "unmonitored", environment: null }),
  ],
  links: [
    link(REPO, "source_code", API),
    link(CADDY, "routes", API),
    link(WEB, "calls", API, { confidence: 0.8 }),
    link(API, "stores", POSTGRES),
    link(API, "queue", REDIS),
    link(WORKER, "stores", POSTGRES),
    link(API, "deployed_on", BOX, { origin: "inferred" }),
    link(WORKER, "deployed_on", BOX, { origin: "inferred" }),
    link(POSTGRES, "hosted_on", RDS, { origin: "inferred" }),
    link(API, "email", OVH),
  ],
  bundles: [
    bundle(REPO, "services", ["source_code"], [API]),
    bundle(API, "data", ["stores", "queue"], [POSTGRES, REDIS]),
    bundle(API, "cloud", ["deployed_on"], [BOX]),
    bundle(API, "external", ["email"], [OVH]),
    bundle(WORKER, "data", ["stores"], [POSTGRES]),
    bundle(WORKER, "cloud", ["deployed_on"], [BOX]),
    bundle(POSTGRES, "cloud", ["hosted_on"], [RDS]),
  ],
  figures: {
    services: 4,
    applications: 0,
    repositories: 1,
    databases: 2,
    stores: 0,
    cloud_resources: 2,
    providers: { aws: 2 },
    external: 1,
    teams: 0,
    tables: 36,
  },
  health: { operational: 6, attention: 1, incident: 1, unmonitored: 0 },
  services_by_status: { incident: 1, attention: 1, operational: 2, unmonitored: 0 },
  top_dependencies: [
    { card_id: BOX, name: "leka-prod", kind: "instance", count: 2 },
    { card_id: POSTGRES, name: "PostgreSQL", kind: "database", count: 2 },
  ],
};

/** Nothing connected yet: no card, every figure nought. */
export const NOTHING: Architecture = {
  ...ARCHITECTURE,
  environments: [],
  groups: [],
  cards: [],
  links: [],
  bundles: [],
  figures: {
    services: 0,
    applications: 0,
    repositories: 0,
    databases: 0,
    stores: 0,
    cloud_resources: 0,
    providers: {},
    external: 0,
    teams: 0,
    tables: 0,
  },
  health: { operational: 0, attention: 0, incident: 0, unmonitored: 0 },
  services_by_status: { incident: 0, attention: 0, operational: 0, unmonitored: 0 },
  top_dependencies: [],
};
