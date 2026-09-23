# Runbook — backup, restore, and rotating a secret

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

## The AWS account closes itself around March 2027

Not a risk, a schedule. The account (`544733633234`, `eu-central-1`) is on
the plan that grants up to $200 of credit and runs for **six months or until
the credit is gone**. At the end AWS **closes the account**; ninety days
later it deletes what was in it.

So this is the one date in this file that is not about a failure:

| | |
|---|---|
| **Estimated expiry** | around March 2027 |
| **What ends** | the whole account — S3 bucket, IAM user, anything running |
| **Grace before deletion** | 90 days after closure |
| **What is NOT on it** | the database. Neon is separate and unaffected |

**Before that date**, either convert the account to a paid plan or move what
is on it. Converting is the cheap option and takes minutes; discovering the
closure afterwards costs the bucket.

**Until then, no customer data touches this account.** The bucket
`leka-payloads-…` is for validation. Staging runs on seeded data. That is
not a precaution about AWS — it is that an account which deletes itself on a
schedule is not somewhere a customer's files can live.

## Honest gaps

Stated here rather than left to be discovered.

1. **No scheduled logical dump exists.** The drill was run by hand. Until
   there is a cron job pushing a dump somewhere outside Neon, the only real
   protection is Neon's own 6-hour history, and the logical-dump RPO above is
   unbounded.
2. **6 hours of history is the free plan.** Raise it before the first paying
   customer. It is a project setting.
3. **A dump has never been stored off-provider.** Neon's history protects
   against our mistakes. It does not protect against losing the Neon account.
4. **The drill has been run once.** Quarterly is the intent; see below.

---

## Procedure — point-in-time restore (the primary path)

Use this for anything caused by us: a bad migration, a bad deploy, a `DELETE`
without a `WHERE`. It is seconds, and it does not touch the live branch.

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

These keys encrypt customers' credentials at rest. Rotating them means
re-encrypting rows, and getting the order wrong makes data unreadable.

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
