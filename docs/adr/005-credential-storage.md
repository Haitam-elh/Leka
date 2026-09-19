# ADR 005 — Customers' credentials encrypted in our database with Fernet

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329
**Supersedes:** the `credentials_ref` column introduced in migration 001

## Context

LEKA connects to customers' systems on their behalf. To do that it holds
long-lived credentials: a GitHub token, a Jira API key, an AWS role, a
Datadog key. A GitHub token is the keys to a customer's source code, and we
hold one per source, per customer, indefinitely.

Migration 001 gave `sources` a `credentials_ref` column — a pointer to an
entry in a secret store. The pointer existed; the store did not, and nothing
in the repository created one. A connector had nowhere to write a token. The
decision had been made implicitly, recorded nowhere, and left the next ticket
blocked.

The constraints that matter: two part-time developers, no dedicated
infrastructure, and a product whose first customer conversation will include
a security officer asking where their token lives.

## Decision

**Credentials are encrypted by the application with Fernet
(AES-128-CBC + HMAC-SHA256) and the ciphertext is stored in
`sources.credentials_encrypted` (`bytea`). The keys live in
`LEKA_ENCRYPTION_KEYS`, in the environment.**

`leka.platform.secret_box` is the only thing that encrypts or decrypts.
Nothing else touches the column.

**Several keys, from day one.** `LEKA_ENCRYPTION_KEYS` is a list: the first
encrypts, all of them are tried when decrypting (`MultiFernet`). Key rotation
is the known weakness of this approach, so it is designed in rather than
retrofitted — retrofitting means re-encrypting rows you can no longer read:

1. put the new key first, keep the old one, deploy
2. re-encrypt existing rows with `SecretBox.rotate`
3. drop the old key in a later deploy

**A malformed key stops the process at startup.** Fernet only objects when
first used, which would be the first sync of the first connector — hours
after deploy, in a worker log nobody is watching.

**A credential that cannot be decrypted raises.** `DecryptionError`, never a
silently empty token that turns into a confusing 401 from a vendor's API.

## What this actually protects against

Being precise matters here, because the honest answer is "less than it
sounds":

**It protects** against a leaked backup, a stray `pg_dump`, a misconfigured
read replica, a decommissioned disk, or a SQL injection that reads rows. All
of those yield ciphertext. These are also, by some distance, the most common
ways credentials leak.

**It does not protect** against anyone who can read the process environment
or the application's memory. Compromise the API host and you have both the
key and the data.

The value is that the database and the key are never in the same place — and
a database is copied far more often than an environment is.

## Alternatives rejected

**An external secret store (AWS Secrets Manager, Vault) — what
`credentials_ref` implied.**
Genuinely better: the backed-up database contains no secret at all, not even
encrypted; rotation and audit are native; access is revocable per identity.
Rejected for now on cost of entry, not on merit. It means a service to
provision, pay for and keep available before a single connector can be
written, plus an invented local-development path. At two part-time
developers, that is weeks of latency for a product with no customers yet.

The way back is open and cheap: `secret_box` is the only thing that touches
the column, so swapping it for a store client is one module and one
migration. Revisit when a customer's security officer asks — that question
will come from a large account, and by then the answer is worth the work.

**Plaintext in the database, protected by access control alone.**
Rejected. A `pg_dump` in someone's downloads folder is not a hypothetical,
and "our database is well protected" is not an answer to give a security
officer.

**Asymmetric encryption, so only the worker can decrypt.**
Appealing: the API could write credentials without being able to read them
back. Rejected because the API needs to test a connection when a source is
configured, which requires the token. Worth revisiting if that stops being
true.

**A key derived per workspace.**
Would limit the blast radius of one leaked key to one customer. Rejected for
now: it needs a key hierarchy and a root key, which is most of the complexity
of a real secret store without its benefits.

## Consequences

**Good.** A connector has somewhere to write a token today, with no
infrastructure to provision. Backups and replicas carry no readable secret.
Rotation is possible without downtime. Local development needs one
environment variable.

**Bad.** The key sits in the environment of the machine that reads the data —
weaker than a real secret store, and we should say so plainly rather than
claim more. Rotation requires a re-encryption pass over existing rows. Losing
every key means losing every credential, with re-authentication by each
customer the only recovery; the keys therefore belong in the deployment
secret manager, backed up separately from the database.

**Watch for:** the first customer requiring a bring-your-own-key or an
external store; credentials being needed in a third place, which would be the
signal that `secret_box` needs to become an interface; a key rotation
happening without step 2, which leaves rows only the old key can read.
