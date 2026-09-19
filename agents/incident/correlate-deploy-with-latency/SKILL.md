---
name: correlate-deploy-with-latency
description: Use when a service's latency or error rate degrades and a recent deployment to that service, or to something it depends on, may explain the timing.
version: 0.1.0
entity_types: [service, deployment, incident]
requires: [datadog, github]
mode: read_only
risk: low
outputs: finding
origin: internal
---

Placeholder. The instructions for this agent are product work, not
architecture — see [../../README.md](../../README.md) for the format.
