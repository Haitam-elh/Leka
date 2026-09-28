# Databases — what LEKA asks for, and what it reads

PostgreSQL and MySQL, through [the connector framework](framework.md). LEKA-349.
**LEKA reads the catalogue, never the rows**: what the database says about
itself — its schemas, tables, views, columns, keys, indexes, and what each
view reads from — and not one value of the data. What it contributes then
goes through extraction ([extraction.md](../extraction.md)) like any other
source. Becoming entities of the company model — a table, its schema, its
dependencies — is LEKA-364.

Both hand over their tables in the same shape
(`leka/connectors/databases.py`), within the same bounds — a session
read-only, over TLS, to a public address; 20 000 tables a pass; estimates
rounded — and one extraction reads both (`extraction/data.py`).

---

## PostgreSQL

| | |
|---|---|
| Server | the customer's — self-hosted, or managed (Amazon RDS and Aurora, Google Cloud SQL, Azure Database, Supabase, Neon…) — reachable from the internet |
| Credentials | `username` (first, so the stored hint is the role's name, not the password), `password` — write-only |
| Config | `host`, `port` (5432), `database`, `schemas` |
| Category | `data` |
| Capabilities | `schemas`, `tables` (tables, partitioned tables, views, materialized views, foreign tables) |
| Code | `leka/connectors/postgresql/` |

### What to create in PostgreSQL

A role of its own, that can connect and see the schemas to describe — and
nothing else:

```sql
CREATE ROLE leka_reader LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE app TO leka_reader;
GRANT USAGE ON SCHEMA billing, ops TO leka_reader;
```

**No `SELECT`** on any table, no `pg_read_all_data`, no superuser: what LEKA
reads, the catalogue, every role can read. The connector's tests prove it:
they run with exactly such a role, and describe everything
(`tests/test_postgresql_connector.py`). A role that can do more — a
superuser, or one that creates roles or databases — passes the test with a
warning.

In LEKA, **Sources → Add → PostgreSQL**: the host, the database, the role
and its password. Test, choose the schemas, activate.

### The boundary, and what PostgreSQL does not enforce

Only the schemas the role has **USAGE** on are described, and among them
only those chosen in the scope, if any. That boundary is **LEKA's**, not
PostgreSQL's: PostgreSQL lets every role read its whole catalogue, the
names of every schema and table included. LEKA's queries keep what the
role may use (`has_schema_privilege(…, 'USAGE')`) and leave the rest
unread. So:

- Give USAGE on the schemas to describe, and only those.
- Since PostgreSQL 15, `public` is usable by every role by default: it is
  described unless the scope leaves it out, or
  `REVOKE USAGE ON SCHEMA public FROM PUBLIC` does.
- The source's **scope rules** ([scope-and-mapping.md](scope-and-mapping.md))
  match the schema's name: `exclude: ["*_archive"]` leaves those schemas
  and their tables out of what is stored.
- What is in a schema's comments, a table's, a column's, and a view's
  definition, is read. A secret written into one of them would be read.

### The connection — security

- **A public address only.** The host is typed by the admin and LEKA's
  server connects to it, so it could otherwise be pointed at LEKA's own
  network. A literal private address (`10.x`, `127.0.0.1`, `::1`,
  `169.254.169.254`…) is refused when saved; a name is resolved **when
  connecting**, every address it has must be public, and the connection
  goes to the address checked, not to the name — which cannot then change
  target in between (`network.public_address`, the same rule as the HTTP
  connectors'). A database only reachable inside the customer's network
  cannot be read from LEKA's server; its firewall or security group must
  let LEKA's server in, and only on the port.
- **TLS required.** A server that does not offer it is refused
  (`CONFIG_INVALID`). The server's certificate is **not verified** — the
  equivalent of libpq's `sslmode=require`: the link is encrypted, but a
  machine that intercepted the name could present its own certificate.
  Verifying against the provider's CA (`verify-full`) is to come.
- **A read-only session**, whatever the role could do:
  `default_transaction_read_only = on`, a `statement_timeout` of 15
  seconds, a 10-second connection timeout, and `application_name = LEKA`,
  so the session is recognisable in `pg_stat_activity`. One connection at a
  time, opened for one call and closed after it.
- The **password** is encrypted at rest like every credential, never
  returned by the API, and removed from every diagnostic's detail.

### The connection test

1. Who am I, on which server: `current_user`, the database, the server's
   version — the account is `role@host`. A role that can do more than read
   is a warning.
2. The schemas the role may use. A schema in the scope it cannot use fails
   the test, named (`NOT_FOUND`); none at all is a warning.
3. One read of the tables' query — if it runs, the sync will.

### What is read

Seven queries, all of the catalogue, in `leka/connectors/postgresql/connector.py`
(a test checks that none reads anything but `pg_*` relations):

| Capability | What | Id | Container |
|---|---|---|---|
| `schemas` | name, owner, comment, and the database | the schema's name | itself, as a repository is its own |
| `tables` | schema, name, kind (`table`, `partitioned_table`, `view`, `materialized_view`, `foreign_table`), owner, comment, estimated rows, size on disk; each **column** — name, type as written (`numeric(12,2)`), nullable, default, comment; each **constraint** — primary key, unique, foreign key with the table and columns it references, check, with its definition; each **index** with its definition; a view's **definition** and the tables it **reads from** | `schema.table` | the schema |

A partition is not a table of its own: its parent, the partitioned table,
is. System schemas (`pg_catalog`, `information_schema`, `pg_toast`…) are
never read.

Extraction (`extraction/data.py`): a table's name as a query writes it
(`billing.invoices`), its comment, its columns one line each —
`customer_id bigint NOT NULL → billing.customers(id)` — then its checks and
keys on several columns, a view's definition; the tables its foreign keys
reference and a view reads from as references; its kind, owner, columns,
primary key and sizes as metadata.

### Synchronisation

The catalogue has no "changed since": both capabilities are read **whole
each pass**. The sync then writes **only what changed** — a record whose
payload is the one already stored costs nothing — and marks gone, at each
pass, a table no longer there. The estimated rows and the size move with
every write to a table, so the connector keeps them to **two significant
figures** (12 345 678 → 12 000 000): a pass over an unchanged schema
writes nothing.

At most **20 000** tables and views a pass. Beyond, the pass fails and
says so (`CONFIG_INVALID`), asking for schemas to be chosen: a list read
whole and cut would mark the rest gone.

### Retention

Kept **90 days**, like the other sources that describe structure.

### Errors

| What | Diagnostic |
|---|---|
| Wrong role or password, or refused by `pg_hba.conf` | `AUTH_INVALID` |
| The database does not exist | `NOT_FOUND` |
| A schema in scope the role cannot use | `NOT_FOUND`, naming it |
| A privilege missing | `PERMISSION_DENIED` |
| A statement or the connection too slow | `TIMEOUT` |
| No TLS on the server; an address that is not public; too many tables | `CONFIG_INVALID` |
| The host unreachable or unknown | `NETWORK_UNREACHABLE` |
| Anything else PostgreSQL says | `PROVIDER_ERROR` |

### Limits

- A database inside a private network cannot be read: there is no agent
  or tunnel.
- The certificate is not verified (above).
- Row counts and sizes are PostgreSQL's estimates (`reltuples`, as of the
  last `ANALYZE`), rounded.
- Functions, triggers, sequences, types, roles and grants are not read.
- Schemas and tables are extracted, not yet entities (LEKA-364).

---

## MySQL

| | |
|---|---|
| Server | MySQL 8.0 or later — self-hosted, or managed (Amazon RDS, Aurora MySQL 3, Google Cloud SQL, Azure Database for MySQL, PlanetScale…) — reachable from the internet |
| Credentials | `username` (first, so the stored hint is the account's name), `password` — write-only |
| Config | `host`, `port` (3306), `schemas` — the databases to describe |
| Category | `data` |
| Capabilities | `schemas` (in MySQL, a schema is a database), `tables` (tables and views) |
| Code | `leka/connectors/mysql/`, with the `asyncmy` driver |

MariaDB speaks a different `information_schema` (no `VIEW_TABLE_USAGE`, no
index expressions), and is **not supported** yet.

### What to create in MySQL

An account of its own, with one privilege on the databases to describe:

```sql
CREATE USER 'leka_reader'@'%' IDENTIFIED BY '…';
GRANT REFERENCES ON billing.* TO 'leka_reader'@'%';
GRANT REFERENCES ON ops.* TO 'leka_reader'@'%';
```

Unlike PostgreSQL, **MySQL shows in `information_schema` only what the
account holds a privilege on**: the boundary is the server's own, and an
account with none sees nothing. `REFERENCES` is the one that shows the
structure and not the data — checked against a real server, privilege by
privilege:

| Granted on the database | What `information_schema` shows | A row |
|---|---|---|
| nothing | nothing | refused |
| `SHOW VIEW` | the tables' names, not their columns | refused |
| **`REFERENCES`** | tables, columns, keys, foreign keys, checks, indexes | **refused** |
| `SELECT` | all of it, and a view's definition | read |

`REFERENCES` lets an account declare a foreign key towards these tables —
which it cannot do without also being allowed to create or alter a table,
and LEKA's account is not.

**A view** is described by its name and its columns. Its definition, and
the tables it reads, MySQL shows only to an account that may `SELECT` from
it — and so read its rows. LEKA reads them when the admin chose to grant
that, view by view, knowing what it opens:

```sql
GRANT SELECT, SHOW VIEW ON billing.unpaid TO 'leka_reader'@'%';
```

The connection test warns of an account that can read rows (`SELECT`) or
do more than read (`INSERT`, `ALTER`, `SUPER`…). The connector's tests run
with an account that has `REFERENCES` alone, and describe everything
(`tests/test_mysql_connector.py`).

### The connection — security

As PostgreSQL's (above): a public address, resolved when connecting and
connected to; **TLS required** — the driver refuses a server without it
(`CONFIG_INVALID`, checked against a server started without TLS), and
the session's cipher (`Ssl_cipher`) is checked once connected, whatever
the driver did; the certificate is not verified. Every session is
**read-only** (`SET SESSION TRANSACTION READ ONLY`), each query bounded by
`MAX_EXECUTION_TIME` (15 seconds), and named `LEKA` in the connection's
attributes (`performance_schema.session_connect_attrs`).

### What is read

Eleven queries, all of `information_schema` (a test checks that none
reads anything else):

| Capability | What | Id | Container |
|---|---|---|---|
| `schemas` | each database: name, character set, collation | its name | itself |
| `tables` | database, name, kind (`table`, `view`), storage engine, comment, estimated rows, size (data and indexes); each **column** — name, type as written (`decimal(12,2)`), nullable, default, comment; each **constraint** — primary key, unique, foreign key with what it references, check with its clause; each **index**, with its columns or expressions and method; a view's definition and the tables it reads, when visible (above) | `database.table` | the database |

MySQL has no owner of a table, and no comment on a database. The row
counts and sizes are `information_schema`'s, which MySQL 8 caches for up
to a day (`information_schema_stats_expiry`) — and rounded, as
PostgreSQL's.

### Synchronisation, retention

As PostgreSQL's: whole each pass, only what changed written, a table gone
marked gone; at most 20 000 tables and views a pass. Kept **90 days**.

### Errors

| What | Diagnostic |
|---|---|
| Wrong account or password (1045) | `AUTH_INVALID` |
| A database in scope the account cannot see | `NOT_FOUND`, naming it |
| A privilege missing (1044, 1142, 1143, 1227) | `PERMISSION_DENIED` |
| A query too slow (3024), or the connection | `TIMEOUT` |
| No TLS; an address that is not public; too many tables | `CONFIG_INVALID` |
| The host unreachable or unknown (2002, 2003, 2006, 2013) | `NETWORK_UNREACHABLE` |
| Anything else MySQL says | `PROVIDER_ERROR` |

### Limits

- As PostgreSQL's: no private network, the certificate not verified,
  estimates rounded, schemas and tables not yet entities (LEKA-364).
- A view's definition and dependencies need `SELECT` on it (above).
- Routines, triggers, events, users and grants are not read.
- MariaDB is not supported.
