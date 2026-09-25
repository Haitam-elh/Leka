# 014 — Where LEKA runs

**Status:** accepted, amended 2026-09-24 (see the first section)
**Date:** 2026-09-23
**Ticket:** LEKA-336

## Amendment, 2026-09-24 — production, on RDS, with the web app

What changed, and the reason for each. The rest of this record is the
original decision; where it says "staging", read "production".

- **One environment online, named `production`.** Not staging plus
  production: two environments on this budget means two boxes, two
  databases and two sets of secrets for two part-time developers, and the
  second one is looked after by nobody. What stands in for staging is CI, the
  browser suite, and `deploy.sh` putting the previous release back. The
  cost, said plainly: nothing is tried online before users see it.
- **PostgreSQL moves from Neon to Amazon RDS.** Same region, same account
  as S3 and the instance: one provider to watch, one bill, backups the
  account itself holds (7 days, point in time), and a database that is not
  reachable from the internet at all — only from the instance's security
  group. The cost: RDS bills by the hour where Neon's free plan did not, and
  the Neon drill in `runbook.md` has to be redone on RDS.
- **The web app is deployed** — `output: "standalone"`, its own image built
  from the same commit as the API, `app.` and `api.` as two blocks of one
  Caddyfile. The two names share `leka-core.com`, which is what ADR 009
  requires.
- **Production starts on the free plan's credits** (decided 2026-09-25),
  and the account moves to the paid plan when they are nearly spent — and
  before the first customer's data, whichever comes first. Running out on
  the free plan closes the account rather than billing it (see "What this
  costs" below, and `runbook.md`), so the upgrade is watched for monthly,
  not waited for.
- **One instance, now in production.** Below, "What we give up" called one
  point of failure acceptable on staging and not in production. It is
  accepted in production for the launch, knowingly: a handful of users, and
  a box rebuilt from Git and `production.env` in ten minutes. A deployment
  drops the requests in flight. The day either matters, the answer is still
  the one below — two instances and a balancer.

## The decision

Staging runs on **one EC2 instance in `eu-central-1`**, with Docker Compose:
the API, the RQ worker and its scheduler, Redis and Caddy. PostgreSQL stays on **Neon**, object
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
looks after it at 9pm". One instance, a handful of containers and a compose file is a
thing either of us can rebuild from scratch in ten minutes.

### Not a database on the box

Neon already runs PostgreSQL, managed, in `aws-eu-central-1` — the same
region. A database on the instance would be the one thing on it that cannot
be thrown away and rebuilt, which is exactly what we want the instance to be.

Worth knowing: the Neon project is on the **free plan**, which retains six
hours of history. That is the real recovery window, and `docs/runbook.md`
measures what restoring costs.

## What this costs

S3 for the volumes involved is cents. Sentry, GHCR and Neon are on free
plans. A budget alarm is set — an alert, not a cap, and it does not stop
anything from being billed.

**The account is not on the classic 12-month free tier.** It is on the plan
that gives up to $200 of credit and lasts **six months, or until the credit
runs out, whichever comes first** — estimated around **March 2027**. At that
point the account **closes itself**, and the data in it is deleted ninety
days later.

Two consequences, and neither is optional:

- **No customer data goes on this account** until it is converted to a paid
  one. The S3 bucket is a validation bucket. Staging runs on seeded data and
  nothing else.
- **The expiry is a date in the runbook**, not a thing to remember. An
  account that deletes itself is not a billing event, it is data loss with a
  calendar entry, and the calendar entry is the only warning there is.

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
else that runs a container is a different `production.env` and a different SSH
target — not a rewrite. That was a condition of choosing anything at all this
early.
