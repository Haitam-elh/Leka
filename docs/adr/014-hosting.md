# 014 — Where LEKA runs

**Status:** accepted
**Date:** 2026-09-23
**Ticket:** LEKA-336

## The decision

Staging runs on **one EC2 instance in `eu-central-1`**, with Docker Compose:
the API, the RQ worker, Redis and Caddy. PostgreSQL stays on **Neon**, object
storage is **Amazon S3**, errors go to **Sentry** on its EU region. The image
is built by GitHub Actions and kept in **GHCR**, tagged with the commit sha.

No production environment yet, and no load balancer, no managed cache, no
orchestrator.

## Why this and not the obvious alternatives

### Not AWS App Runner

App Runner was the first choice on paper — a managed container service with
HTTPS included, no load balancer to pay for. Two things ruled it out, and the
first is decisive:

> "AWS App Runner is no longer open to new customers. Existing customers can
> continue to use the service as normal."
> — *AWS App Runner Developer Guide, September 2026*

The AWS account for LEKA was created in September 2026. The service is not
available to us at all.

It would have failed anyway. App Runner deploys "a scalable and secure **web
application**" — HTTP services. The worker is `rq worker`, a process that
connects to Redis and never serves a request, and there is nowhere to put it.
Nor is there a way to run Redis beside it: App Runner gives each service an
HTTPS endpoint, not a private TCP network.

### Not ECS/Fargate with a load balancer

An Application Load Balancer is billed by the hour whether or not anyone
visits. On a staging environment with two users it is the largest line on the
bill, and it exists to solve a problem — distributing traffic across
instances — that one instance does not have.

### Not ElastiCache

Same reasoning, and worse: a managed Redis with no free tier, for a queue
whose contents are disposable by design. LEKA-334 keeps what must survive in
`events` and `job_runs`, in PostgreSQL, and re-dispatches from there. Redis
here is a work queue, not a database.

### Not Kubernetes, and nothing that needs an operator

`docs/architecture.md` sets the constraint: two developers, part time. The
question for every piece of infrastructure is not "does it scale" but "who
looks after it at 9pm". One instance, four containers and a compose file is a
thing either of us can rebuild from scratch in ten minutes.

### Not a database on the box

Neon already runs PostgreSQL, managed, in `aws-eu-central-1` — the same
region. A database on the instance would be the one thing on it that cannot
be thrown away and rebuilt, which is exactly what we want the instance to be.

Worth knowing: the Neon project is on the **free plan**, which retains six
hours of history. That is the real recovery window, and `docs/runbook.md`
measures what restoring costs.

## What this costs

The instance is inside the 12-month free tier; the $100 of AWS credit covers
the rest several times over. S3 for the volumes involved is cents. Sentry,
GHCR and Neon are on free plans. A budget alarm at €20 is set before anything
is provisioned — not because the bill is expected, but because a forgotten
resource is discovered a month late otherwise.

## What we give up, said plainly

- **One instance is one point of failure.** Staging going down costs nobody
  anything, which is why this is acceptable here and will not be in
  production.
- **Deploying restarts the API.** Requests in flight are dropped. Acceptable
  on staging; production needs two instances and a real balancer, and that is
  the day the ALB becomes worth its price.
- **Redis loses its memory on restart.** By design, see above, but it does
  mean a job dispatched in that second is re-dispatched rather than resumed.
- **The web application is not deployed yet.** Scoped out of this pass. It
  needs `output: "standalone"` in `web/next.config.ts`, its own small
  Dockerfile and a second block in the Caddyfile; the compose file has a
  comment where it goes. Until then, staging verifies the API and the
  browser-level cookie behaviour that only a real HTTPS domain exposes —
  which is most of why staging exists this early.

## What made this reversible

The application reads everything from `LEKA_*` environment variables and
nothing from a host's metadata. Object storage already speaks S3, R2 or MinIO
through one endpoint variable (ADR 010). Moving to Scaleway, Fly or anywhere
else that runs a container is a different `staging.env` and a different SSH
target — not a rewrite. That was a condition of choosing anything at all this
early.
