# ADR 015 — One connector framework: Fernet behind a SecretStore, no plugins

**Status:** accepted
**Date:** 2026-09-23
**Ticket:** LEKA-344

## Context

LEKA reads GitHub, Jira, Confluence, AWS, Datadog and more. Each connection
needs credentials stored safely, a way to prove it works before it is used,
a health signal and failures an admin can act on. Written per vendor, that
is six lifecycles, six ways to leak a token and six vocabularies for "it
failed".

## Decision

1. **One contract**, `Connector`, with two methods a vendor implements
   (`test_connection`, `check_health`) and one declared for LEKA-352
   (`iter_resources`). Lifecycle, storage, encryption, permissions and
   history belong to the framework; a connector never touches the database.
2. **The existing `sources` table is the instance**, not a new `connectors`
   table. Ingestion and knowledge already reference it by composite foreign
   key, and the product calls these "sources". A *connector* is the code.
3. **Credentials in their own table, behind `SecretStore`.** Today
   `DatabaseFernetSecretStore`: Fernet through the existing `SecretBox`
   (ADR 005), `LEKA_ENCRYPTION_KEYS` with its rotation, a key version per
   row. Tomorrow AWS KMS or Secrets Manager (LEKA-405) is another class with
   the same three methods — no connector knows where its secret lives.
4. **An explicit registry**: a dictionary filled by `@register_connector`,
   populated by import lines in `leka/connectors/__init__.py`.
5. **One diagnostic shape** for every failure, with stable codes and a
   secret-free detail.

## Why not dynamic plugins

Loading connectors from a directory or from entry points would make "what
code runs against a customer's GitHub, holding their token?" a question
answered at runtime, by whatever is installed. Here it is answered by
reading one file, reviewing one diff, and running one test suite. Adding a
connector is still one package and two lines — the cost dynamic loading
would save is not worth what it hides.

## Why not a new key variable

The ticket proposed `LEKA_ENCRYPTION_KEY`. `LEKA_ENCRYPTION_KEYS` already
exists, takes several keys so that rotation needs no downtime, has a
rotation script and a test that every encrypted column is rotated, and is
covered by LEKA-335's secret-ownership rules. A second variable would be a
second way to get it wrong.

## Consequences

- Adding a connector touches its package, one `SourceKind` member and one
  import line — no migration: the CHECK on `sources.kind` is gone.
- Activation depends on a fingerprint of the config and of the credentials'
  revision. A key rotation does not force a retest; a new token does.
- Nothing is published on the event bus until something consumes it
  (LEKA-352): the outbox would record unconsumed events as failed.
