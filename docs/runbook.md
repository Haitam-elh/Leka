# Runbook — backup, restore, and rotating a secret

> The nightly dump with its manifest, `python -m leka.ops.backup verify`,
> RPO/RTO and critical dependencies: [operations.md § 4](operations.md#4-backup-restore-disaster-recovery)
> (LEKA-408).

> Losing a **deployment** rather than data? See [deployment.md](deployment.md):
> shipping, rolling back, and a worker that has stopped consuming.

A backup that has never been restored is not a backup. It is an assumption.

This document records a restore that was actually performed, with the
measured numbers, and the procedure to repeat it. Where a number is a
measurement it says so. Where it is an estimate it says that too. The last
section is the other operation nobody should improvise: rotating a secret.

---

## The drill, as performed

**Performed:** 21 September 2026
**Run from:** a developer laptop, against the shared Neon project
**Target:** Neon project `Leka`, PostgreSQL 16, `aws-eu-central-1` (Frankfurt)
**Source:** PostgreSQL 16 in Docker, on a laptop in France

### Dataset

A representative small customer after a few weeks of ingestion, built with
`generate_series` rather than borrowed from anywhere real.

| | |
|---|---|
| `raw_payloads` | 150 000 rows |
| `entities` | 5 000 rows |
| `relationships` | 5 000 rows |
| `sources` | 12 rows |
| Database size | **93 MB** |
| Compressed dump (`-Fc`) | **15 MB** |

### Measurements

| Step | Measured |
|---|---|
| `pg_dump -Fc` of 93 MB | **0.9 s** |
| Create an empty Neon branch | **0.54 s** |
| `pg_restore -j 4` into Neon, over the internet | **72.2 s** |
| Point-in-time restore — API call | **1.22 s** |
| Point-in-time restore — until the first successful query | **2.73 s** |

### Verification

The restore was not assumed to have worked. Row counts were compared table by
table between source and target, and the schema version was checked:

```
✓ raw_payloads  : 150000 = 150000
✓ entities      :   5000 = 5000
✓ relationships :   5000 = 5000
✓ sources       :     12 = 12
✓ workspaces    :      1 = 1
alembic_version : 67406715fb5e
```

### RPO and RTO, as observed

**RPO — how much data a failure can cost.**

| Path | Measured / configured |
|---|---|
| Neon point-in-time restore | **up to 6 hours** — the history retention on the current free plan, read from the project's own settings |
| Logical dump | **the age of the last dump.** No dump schedule exists yet, so this is currently *unbounded* |

**RTO — how long until service is back.**

| Path | Measured |
|---|---|
| Neon point-in-time restore | **≈ 3 seconds** to a queryable database |
| Logical restore of 93 MB | **≈ 73 seconds** (dump + restore) |

### What these numbers do and do not say

They are honest and they are small, and the second fact is mostly because the
dataset is small. **The restore time scales with the data, the point-in-time
restore does not** — Neon branches are copy-on-write, so branching a 500 GB
database takes about as long as branching this one. That difference is the
whole reason the managed path is the primary one below.

Two things these numbers deliberately do **not** cover:

- **Object storage is not in them.** The payload bytes live outside the
  database (ADR 010) and have their own durability, provided by the object
  store. Restoring the database does not restore them, and does not need to.
- **A 6-hour RPO is a free-plan number.** It is a setting, not a law of
  nature, and it is the first thing to change when there is a paying
  customer.

---

## The AWS account: convert it before production

Not a risk, a schedule. The account (`544733633234`, `eu-central-1`) was
opened on the **free plan**: up to $200 of credit, for **six months or until
the credit is gone**. AWS's own words:

> "Your free account plan ends after six months or when your credits are
> fully used - whichever occurs first. […] After your free account plan
> expires, your account closes automatically, and you lose access to your
> resources and data. AWS retains your content for 90 days before
> permanently deleting your account and all associated resources."
> — *AWS Billing User Guide, "Choosing a plan"*
> (<https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html>)

Production puts the database (RDS) and customer files (S3) on this account.
**Decided 2026-09-25: production starts on the credits, and the account is
converted when they are nearly spent** — below about $50, checked monthly —
**and in any case before the first customer's data goes in.** Not after:
running out on the free plan closes the account, it does not start a bill.
See step 1 of `deployment.md`, "Turning production on".

**The procedure, as AWS documents it** (same page, "To upgrade your free
plan"):

1. Sign in to the AWS Management Console, as the account's root user or an
   administrator with billing access.
2. Open **Upgrade plan**:
   <https://console.aws.amazon.com/billing/home?#/freetier/upgrade>
3. Review the features you gain, and choose **Upgrade account**.

If the console shows the newer "AWS Settings" experience instead, AWS
documents the equivalent path — <https://settings.aws.com> → **Billing** →
**Upgrade** → **Get started** → payment method → **Upgrade account**
(<https://docs.aws.amazon.com/accounts/latest/reference/upgrade-account.html>).

What changes, again in AWS's words:

- "Any remaining credits from your free account plan are automatically
  applied to future AWS bills." Nothing is lost by converting early.
- "Account doesn't close when credits are depleted." — and in exchange, you
  "pay for charges that exceed the credit balance". The budget alarm is what
  says so before the invoice does.
- "You cannot reverse the upgrade process."

**Until it is converted, no customer data touches this account** — test
accounts and seeded data only.

## Email: the DNS records that get it delivered

The API sends as `support@leka-core.com` through OVH (`ssl0.ovh.net:465`).
Without these records, the mail leaves and lands in spam, or nowhere. All
three live in the OVH DNS zone of `leka-core.com` (Web Cloud → Domain names
→ `leka-core.com` → DNS zone).

| Record | Type | Value | Source |
|---|---|---|---|
| `leka-core.com` | TXT | `v=spf1 include:mx.ovh.com ~all` | OVHcloud, "How to improve email security with an SPF record" |
| DKIM | CNAME × 2 | created by OVH itself, see below | OVHcloud, "How to improve email security with a DKIM record" |
| `_dmarc.leka-core.com` | TXT | `v=DMARC1; p=none; rua=mailto:support@leka-core.com` | start in observation |

- **SPF.** There must be **one** `v=spf1` record. If the zone already has
  one, merge `include:mx.ovh.com` into it; two SPF records invalidate both.
- **DKIM.** Web Cloud → **MX Plan** (or the email offer in use) → the
  domain → **General information** → click the red **DKIM** badge →
  **Validate**. OVH creates the two selector CNAMEs in the zone when the
  zone is at OVH. Wait for the badge to turn green.
- **DMARC `p=none`** reports without rejecting anything. After a few weeks
  of clean reports, move to `p=quarantine`. Starting at `quarantine` risks
  losing real mail over a record that was not yet right.

Then check from the box:

```bash
docker compose -f docker-compose.production.yml --env-file production.env \
  exec api python -m leka.identity.email --test <a Gmail address you own>
```

In Gmail, *Show original* must say `SPF: PASS`, `DKIM: PASS` and
`DMARC: PASS`.

## Honest gaps

Stated here rather than left to be discovered.

1. **RDS keeps 1 day of point in time** — the most the free plan allows.
   The nightly dump (operations.md § 4) covers what is older, up to 24 hours
   lost. Both live in the same AWS account: neither survives losing it.
2. **The drill above was measured on Neon**, before the move to RDS. The
   RDS procedure is written from AWS's documentation and has not yet been
   rehearsed on our instance: the free plan refuses the third instance the
   restore needs (tried 2026-10-12). Run it at the account upgrade — a
   restore beside the live instance, `db.t4g.micro`, security group
   `rds-ec2-1`, then table counts against the live one, then delete it —
   and record the numbers here.
3. **The dump is stored in S3, not off-provider.**
4. **The drill has been run once.** Quarterly is the intent; see below.

---

## Before anything risky — a manual snapshot

A manual snapshot is kept until someone deletes it, unlike the automated
backups, which age out after 1 day (7 after the account upgrade). Take one before a migration that drops
or renames, and before any `downgrade`:

```bash
aws rds create-db-snapshot --region eu-central-1 \
  --db-instance-identifier leka \
  --db-snapshot-identifier leka-before-$(date +%Y%m%d-%H%M)
aws rds wait db-snapshot-available --region eu-central-1 \
  --db-snapshot-identifier leka-before-<the same stamp>
```

---

## Procedure — point-in-time restore on RDS (the primary path)

Use this for anything caused by us: a bad migration, a bad deploy, a
`DELETE` without a `WHERE`. RDS restores to a **new** instance beside the
live one. **Do not repair the broken one**: it stays exactly as it is, which
matters if the first theory about what happened turns out to be wrong.

1. **Decide the timestamp.** The last moment you are confident the data was
   good, in UTC, inside the 7-day window.

2. **Restore beside it**, in the same network and security group:

   ```bash
   aws rds restore-db-instance-to-point-in-time --region eu-central-1 \
     --source-db-instance-identifier leka \
     --target-db-instance-identifier leka-restore-$(date +%Y%m%d-%H%M) \
     --restore-time 2026-09-21T13:00:00Z \
     --db-subnet-group-name <the one leka uses> \
     --vpc-security-group-ids <leka-db's id> \
     --no-publicly-accessible
   aws rds wait db-instance-available --region eu-central-1 \
     --db-instance-identifier <the target above>
   ```

3. **Get its endpoint:**

   ```bash
   aws rds describe-db-instances --region eu-central-1 \
     --db-instance-identifier <the target> \
     --query 'DBInstances[0].Endpoint.Address' --output text
   ```

4. **Verify before switching anything**, from the box (the only place
   allowed to reach it):

   ```bash
   psql "$URI" -c "SELECT version_num FROM alembic_version;"
   psql "$URI" -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
   ```

5. **Point the application at it** by changing the host in
   `LEKA_DATABASE_URL`, then `bash deploy.sh` with the running release.

6. **Afterwards, re-run the deletion sweeps.** A restore reinstates rows that
   were legitimately deleted, including workspaces a customer asked to erase.
   Those deletions have to happen again:

   ```bash
   python -m leka.platform.tasks     # erasures past their grace period
   python -m leka.ingestion.tasks    # retention, then reconciliation
   ```

   Skipping this step means holding data a customer asked us to delete.

7. **Later**, once sure: delete the broken instance, keeping a final
   snapshot of it.

---

## Procedure — point-in-time restore on Neon (before RDS)

Kept while the Neon project exists, and because the drill above was run
with it.

**Before anything: do not repair the broken branch.** Branch beside it. The
original stays exactly as it is, which matters if the first theory about what
happened turns out to be wrong.

1. **Decide the timestamp.** The last moment you are confident the data was
   good, in UTC, and within the retention window (currently 6 hours).

2. **Create a branch at that moment.**

   ```bash
   export NEON_API_KEY=...          # from the Neon console, never in Git
   PROJECT=rapid-dawn-18299705
   PARENT=<the branch that broke>
   STAMP=2026-09-21T13:00:00Z

   curl -s -X POST \
     -H "Authorization: Bearer $NEON_API_KEY" \
     -H "Content-Type: application/json" \
     -d "{\"branch\":{\"name\":\"restore-$(date +%Y%m%d-%H%M)\",
           \"parent_id\":\"$PARENT\",\"parent_timestamp\":\"$STAMP\"},
          \"endpoints\":[{\"type\":\"read_write\"}]}" \
     "https://console.neon.tech/api/v2/projects/$PROJECT/branches"
   ```

3. **Get its connection string** (note the `branch_id`):

   ```bash
   curl -s -H "Authorization: Bearer $NEON_API_KEY" \
     "https://console.neon.tech/api/v2/projects/$PROJECT/connection_uri?database_name=PostgreSQL&role_name=PostgreSQL_owner&branch_id=$BRANCH"
   ```

4. **Verify before switching anything.** Row counts, the schema version, and
   at least one thing you know should be there:

   ```bash
   psql "$URI" -c "SELECT version_num FROM alembic_version;"
   psql "$URI" -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
   ```

5. **Point the application at it** by changing `LEKA_DATABASE_URL`.

6. **Afterwards, re-run the deletion sweeps.** A restore reinstates rows that
   were legitimately deleted, including workspaces a customer asked to erase.
   Those deletions have to happen again:

   ```bash
   python -m leka.platform.tasks     # erasures past their grace period
   python -m leka.ingestion.tasks    # retention, then reconciliation
   ```

   Skipping this step means holding data a customer asked us to delete.

---

## Procedure — logical restore (the portable path)

Use this when the provider is the problem, or when moving between providers.
Slower, and it depends on a dump existing.

### Taking a dump

```bash
pg_dump -Fc --no-owner --no-privileges \
  -d "$LEKA_DATABASE_URL_PLAIN" \
  -f "leka-$(date +%Y%m%d-%H%M).dump"
```

`-Fc` is the custom format: compressed, and restorable in parallel.
`--no-owner --no-privileges` because the role names differ between providers
and a restore should not fail over an owner that does not exist there.

Use the plain `postgresql://` form. `postgresql+asyncpg://` is SQLAlchemy's
spelling and `pg_dump` does not understand it.

### Restoring it

```bash
pg_restore --no-owner --no-privileges --clean --if-exists -j 4 \
  -d "$TARGET_URI" leka-20260921-1500.dump
```

Connect to the **direct** endpoint, not the pooled one: remove `-pooler` from
a Neon host. `pg_restore` opens several sessions and issues DDL, which is not
what a connection pooler is for.

`--clean --if-exists` prints "does not exist, skipping" on an empty target.
That is expected, not a problem.

### Then verify, table by table

```bash
for t in raw_payloads entities relationships sources workspaces memberships; do
  echo "$t: source=$(psql "$SOURCE" -tAc "select count(*) from $t") \
             target=$(psql "$TARGET" -tAc "select count(*) from $t")"
done
psql "$TARGET" -tAc "SELECT version_num FROM alembic_version;"
```

And re-run the deletion sweeps, for the same reason as above.

---

## What is NOT in the database

Worth knowing before a restore, so nobody spends an hour looking for it.

**Raw payload bytes.** They are in the object store (ADR 010). The database
holds keys. After restoring an old database you may hold rows whose objects
the retention sweep has since deleted — reads of those payloads will fail,
which is the expected behaviour and why `reconcile_orphaned_objects` exists
in the other direction.

**Encryption keys.** `LEKA_ENCRYPTION_KEYS` lives in the environment and
never in the database or in Git (architecture rule 12). **A restored database
without the key that wrote its `sources.credentials_encrypted` is a database
of unusable ciphertext.** Keep the keys where the backups are not.

**Sessions become useless anyway.** A restore reinstates session rows, and
everyone signs in again regardless. That is correct: a session that predates
whatever went wrong is not one to trust.

---

## Reading dates in psql — "the times are two hours off"

They are not. Every date column is `timestamptz`: the database stores an
instant, and **psql displays it in the session's time zone, which is UTC**.
`2026-09-24 08:00:00+00` is 10:00 in Paris in summer — the `+00` says so.
The API sends the same instant with its offset (`…Z`), and the browser shows
it in the viewer's local time; `tests/test_auth_emails.py` checks the offset
is there.

To read in Paris time, for this psql session only — nothing stored changes:

```sql
SET TIME ZONE 'Europe/Paris';
SELECT email, created_at, email_verified_at FROM users ORDER BY created_at DESC LIMIT 5;
```

Never change the database's own time zone to "fix" this: the values are
already right, and the change would only move the confusion elsewhere.

---

## Repeating the drill

**Quarterly**, and after any change to the schema that involves moving data
rather than adding a column.

It is quick — the numbers above are the whole cost — and it is the only thing
that turns the rest of this document from a plan into a fact.

```bash
# 1. A disposable source with a realistic volume
createdb leka_drill && LEKA_DATABASE_URL=...leka_drill alembic upgrade head
#    then seed it — see the dataset above

# 2. Dump, restore onto a fresh Neon branch, time both

# 3. Compare row counts table by table. This step is the drill.

# 4. Delete the branch and the disposable database
```

Update the measurements in this document each time, and update the
partitioning trigger in ADR 010 if the restore time is approaching **30
minutes** — that is the number at which `raw_payloads` needs partitioning,
and this drill is how it gets noticed rather than remembered.

---

## Procedure — rotating a secret

Every rotation ends the same way: **record the date** in
`LEKA_SECRETS_ROTATED_ON` for that environment. Staging and production log
`secret_rotation_overdue` at startup for any secret past its lifetime, or
whose age nobody recorded. Which module may read which secret, and how often
each should be rotated, is in `docs/configuration.md`.

### LEKA_ENCRYPTION_KEYS — five steps, and the order is the procedure

These keys encrypt customers' credentials at rest — and the signing
secrets of the systems a workspace authorized LEKA to act through
(LEKA-391). Rotating them means re-encrypting rows, and getting the order
wrong makes data unreadable. The script below does both, and reports each.

```bash
# 1. Generate the new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

2. Put the NEW key **first**, keep the old one behind it, and **deploy the
   API and the worker**:
   `LEKA_ENCRYPTION_KEYS=["<new>", "<old>"]`. Every new write now uses the
   new key; every existing row still reads with the old one.

```bash
# 3. Re-encrypt what is already stored. Count first, then do it.
api/.venv/bin/python scripts/rotate_encryption_key.py --dry-run
api/.venv/bin/python scripts/rotate_encryption_key.py

# 4. Run it again. It must report 0 rotated and 0 unreadable.
api/.venv/bin/python scripts/rotate_encryption_key.py --dry-run
```

5. In a **later** deploy, drop the old key:
   `LEKA_ENCRYPTION_KEYS=["<new>"]`, and set the date in
   `LEKA_SECRETS_ROTATED_ON`.

**Interrupted at step 3?** Nothing to repair: run it again. Both keys are
configured, so half-rotated is fully readable, each batch committed on its
own, and rows already rewritten are skipped.

**Step 3 before step 2 is deployed** — the script holds both keys while the
running API still holds only the old one — rewrites rows the API can no
longer read. The API keeps serving and fails on the first credential it
needs. Recovery: deploy step 2, which is what should have happened first.

**Step 5 before step 3 finished** leaves rows only the removed key can read.
Recovery: put the old key back and finish step 3. If the old key is gone for
good, so are those credentials: each affected customer has to reconnect the
source. This is why step 4 exists and why step 5 waits for a later deploy.

**The script exits 1** when some rows are readable by no configured key — a
key removed too early, or a database restored from another environment. Each
one is logged with its source id; everything else was rotated. Put the
missing key back if you still have it.

### LEKA_SECRET_KEY

Replace the value and deploy. No overlap period, and nothing to re-encrypt:
this key signs, it does not encrypt.

What it costs: pagination cursors handed out before the deploy stop being
accepted, and a client holding one starts again from the first page. A cursor
lives for seconds. **Sessions are not affected** — they are random tokens
stored hashed, not signed.

### Everything else — database, Redis, S3, SMTP, model keys

These are credentials somebody else issues, so the overlap is theirs to give:

1. create the new credential at the provider, leaving the old one valid;
2. deploy with the new value;
3. verify: `/api/v1/health` covers PostgreSQL and Redis; for S3, store and
   read back a payload; for SMTP, trigger one verification e-mail;
4. revoke the old credential at the provider;
5. record the date in `LEKA_SECRETS_ROTATED_ON`.

Never step 4 before step 3. A revoked credential and a deploy that has not
landed yet is an outage, and a quiet one: the API starts perfectly well and
fails on the first request that needs the service.
