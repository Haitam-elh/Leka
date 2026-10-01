# Databases — what LEKA asks for, and what it reads

PostgreSQL, Supabase, MySQL, MariaDB, SQL Server, Oracle and MongoDB,
through [the connector framework](framework.md). LEKA-349.
**LEKA reads the catalogue, never the rows**: what the database says about
itself — its schemas, tables, views, columns, keys, indexes, and what each
view reads from — and not one value of the data. What it contributes then
goes through extraction ([extraction.md](../extraction.md)) like any other
source, and becomes the company model's databases, schemas and data objects
([company-model.md § 11](../company-model.md), LEKA-364).

**Where it was read.** Every schema and table a connector hands over says
its `server` — the engine, the host, the port, the database — so that what
two sources read on one database is one thing in the model, and a database
meets the cloud instance serving it at its endpoint. A MySQL, MariaDB or
MongoDB source reads a server: its databases are its schemas. A Supabase
source names the project's own database, `db.<project-ref>.supabase.co`,
not the pooler it connects through — one pooler serves many projects.

All hand over their tables — a MongoDB collection is one — in the same
shape (`leka/connectors/databases.py`), within the same bounds — over TLS,
to a public address, read-only; 20 000 tables a pass; estimates rounded —
and one extraction reads them all (`extraction/data.py`).

| | Engine | What LEKA's account needs | A row, a document |
|---|---|---|---|
| [PostgreSQL](#postgresql) | PostgreSQL | `CONNECT`, `USAGE` on the schemas | refused |
| [Supabase](#supabase) | PostgreSQL, through the session pooler | the same | refused |
| [MySQL](#mysql) | MySQL 8.0+ | `REFERENCES` on the databases | refused |
| [MariaDB](#mariadb) | MariaDB 10.6+ | the same | refused |
| [SQL Server](#sql-server) | SQL Server 2016+ | `VIEW DEFINITION` on the schemas | refused |
| [Oracle](#oracle) | Oracle 19c+, over TCPS | `REFERENCES` on each table and view | refused |
| [MongoDB](#mongodb) | MongoDB | a role with `listCollections`, `listIndexes`, `collStats`, `dbStats` | refused |

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
  `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, a
  `statement_timeout` of 15 seconds, a 10-second connection timeout, and
  `application_name = LEKA` — set once connected, not at the handshake, so
  a pooler in front of the server (Supabase's, PgBouncer's) lets them
  through,
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
- A table's classification is read from its columns' names and comments,
  never from a value (LEKA-364).

---

## Supabase

A Supabase project's database is PostgreSQL: the **PostgreSQL connector**,
under Supabase's name and defaults (`leka/connectors/supabase/`). Everything
said of PostgreSQL above holds — the catalogue read and never the rows, the
role, TLS, the public address, the read-only session.

| | |
|---|---|
| Server | the project's **session pooler**: `aws-0-<region>.pooler.supabase.com`, port 5432 |
| Credentials | `username` — `leka_reader.<project-ref>`, through the pooler — and `password` |
| Config | `host`, `port` (5432), `database` (`postgres`), `schemas` |
| Category, capabilities | `data`; `schemas`, `tables` |

**Why the pooler.** The project's direct host, `db.<project-ref>.supabase.co`,
has an IPv6 address only; a server without IPv6 cannot reach it. The
session pooler (Supabase → the project → **Connect** → Session pooler) has
IPv4, TLS, and keeps a session whole, which the read-only settings need.
Not the transaction pooler (port 6543): it hands each statement to another
session.

### What to create in Supabase

In the project's **SQL editor**:

```sql
create role leka_reader login password '…';
grant usage on schema public to leka_reader;
```

`CONNECT` on `postgres` is every role's already. Through the pooler, the
role signs in as `leka_reader.<project-ref>` — the pooler reads the project
from the name. Supabase's own schemas (`auth`, `storage`, `realtime`…) are
described only if the role is given `USAGE` on them, or left out by the
scope.

Not yet tried against a live Supabase project: the pooler's behaviour is
Supabase's documentation's, and the connector's tests run against a plain
PostgreSQL.

---

## MySQL

| | |
|---|---|
| Server | MySQL 8.0 or later — self-hosted, or managed (Amazon RDS, Aurora MySQL 3, Google Cloud SQL, Azure Database for MySQL…) — reachable from the internet |
| Credentials | `username` (first, so the stored hint is the account's name), `password` — write-only |
| Config | `host`, `port` (3306), `schemas` — the databases to describe |
| Category | `data` |
| Capabilities | `schemas` (in MySQL, a schema is a database), `tables` (tables and views) |
| Code | `leka/connectors/mysql/`, with the `asyncmy` driver |

MariaDB speaks another dialect of `information_schema`: it has
[its own connector](#mariadb), this one with MariaDB's queries.

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

Twelve queries, all of `information_schema` (a test checks that none
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
| No TLS; an address that is not public; too many tables; a MariaDB server | `CONFIG_INVALID` |
| The host unreachable or unknown (2002, 2003, 2006, 2013) | `NETWORK_UNREACHABLE` |
| Anything else MySQL says | `PROVIDER_ERROR` |

### Limits

- As PostgreSQL's: no private network, the certificate not verified,
  estimates rounded.
- A view's definition and dependencies need `SELECT` on it (above).
- Routines, triggers, events, users and grants are not read.
- PlanetScale is not supported: its roles cannot be kept to `REFERENCES`,
  and its `information_schema` is Vitess's, untested.

---

## MariaDB

The **MySQL connector with MariaDB's dialect** (`leka/connectors/mariadb/`):
the same account, the same boundary, the same payload, the same security
— and the queries and settings where MariaDB differs. Everything said of
MySQL above holds, checked against MariaDB 10.6, 10.11 and 11.8.

| | |
|---|---|
| Server | MariaDB 10.6 or later — self-hosted, or managed (Amazon RDS for MariaDB…) — reachable from the internet, with TLS |
| Credentials | `username`, `password` — write-only |
| Config | `host`, `port` (3306), `schemas` — the databases to describe |
| Category | `data` |
| Capabilities | `schemas` (the databases), `tables` (tables, system-versioned tables, views) |
| Code | `leka/connectors/mariadb/`, on `leka/connectors/mysql/` and its `asyncmy` driver |

### What to create in MariaDB

As in MySQL — an account with `REFERENCES` alone on the databases to
describe:

```sql
CREATE USER 'leka_reader'@'%' IDENTIFIED BY '…';
GRANT REFERENCES ON billing.* TO 'leka_reader'@'%';
```

MariaDB, too, shows in `information_schema` only what the account holds a
privilege on; with `REFERENCES`, the tables, columns, keys, checks and
indexes, and a `SELECT` is refused (`tests/test_mariadb_connector.py`). A
view's definition needs `SELECT` on the view, granted by the admin or not
read, as in MySQL.

**TLS.** MariaDB sets it up by itself since 11.4; before, the server needs
its certificate configured (`ssl_cert`, `ssl_key`). Amazon RDS for MariaDB
has TLS. A server without it is refused (`CONFIG_INVALID`).

### What MariaDB says otherwise

| | MySQL | MariaDB, and so the connector |
|---|---|---|
| A query's bound | `MAX_EXECUTION_TIME`, in ms | `max_statement_time`, in seconds — 15; too slow is error 1969 |
| Tables | `BASE TABLE`, `VIEW` | also `SYSTEM VERSIONED` — a table that keeps its history, kind `system_versioned_table`; a `SEQUENCE` is not read, as PostgreSQL's are not |
| An index's parts | columns or expressions | columns: `STATISTICS` has no `EXPRESSION` |
| A check's name | once in its database | once in its table — a check on a column takes the column's name, so two tables may each have `amount`: `CHECK_CONSTRAINTS` says which table |
| A column's default | the value | SQL: `'free'` quoted, `current_timestamp()`; `NULL` for none, read as no default |
| What a view reads | `VIEW_TABLE_USAGE` | no such table: read from the view's definition, which MariaDB writes back normalised — every table after a `from` or a `join`, as `` `schema`.`table` ``, a literal's content left aside |

Eleven queries, all of `information_schema` (a test checks). A column's type
is written as MariaDB writes it, display width included: `bigint(20)`.

**The wrong connector.** A MariaDB server added as MySQL, or a MySQL server
as MariaDB, fails the connection test with what it is, and which connector
to use (`CONFIG_INVALID`): every MariaDB writes its name in its version
(`11.8.2-MariaDB-log`), which is checked before any setting is sent.

### Synchronisation, retention, errors

As MySQL's: whole each pass, only what changed written; at most 20 000
tables a pass; kept 90 days. The errors are MySQL's, but a query too slow
is **1969** (`TIMEOUT`).

### Limits

- As MySQL's: no private network, the certificate not verified, a view's
  definition and dependencies need `SELECT` on it.
- What a view reads is found in its definition, as MariaDB writes it back:
  a table named only inside a stored function the view calls is not seen.
- Sequences, routines, triggers, events, users and grants are not read.

---

## SQL Server

| | |
|---|---|
| Server | SQL Server 2016 or later — self-hosted, or managed (Amazon RDS for SQL Server, Azure SQL Managed Instance, Azure SQL Database…) — reachable from the internet |
| Credentials | `username` — a SQL login, first so the stored hint is its name — and `password`, write-only |
| Config | `host`, `port` (1433), `database`, `schemas` |
| Category | `data` |
| Capabilities | `schemas`, `tables` (tables, system-versioned tables and their history tables, external tables, views) |
| Code | `leka/connectors/sqlserver/`, with `pymssql` (FreeTDS inside its wheels) |

A source is **one database**, as PostgreSQL's: a login is the server's,
but a user — and its permissions — is each database's. A named instance
(`host\instance`) is reached by its port.

### What to create in SQL Server

A login, a user for it in the database, and one permission:

```sql
-- on the server
CREATE LOGIN leka_reader WITH PASSWORD = '…';
-- in the database to describe
CREATE USER leka_reader FOR LOGIN leka_reader;
GRANT VIEW DEFINITION ON SCHEMA::billing TO leka_reader;
```

On Azure SQL Database, where logins may be the database's own, the user
alone: `CREATE USER leka_reader WITH PASSWORD = '…'`.

Like MySQL, and unlike PostgreSQL, **SQL Server shows in its catalogue only
what the account holds a permission on**: the boundary is the server's.
`VIEW DEFINITION` is the permission that shows the structure and not the
data — checked against SQL Server 2022:

| Granted | What the catalogue shows | A row |
|---|---|---|
| nothing | the schemas' names, no table | refused |
| **`VIEW DEFINITION` on a schema** | its tables and views, columns, keys, checks, indexes, comments, row counts and sizes, a view's definition and what it reads | **refused** |
| `VIEW DEFINITION` on the database | the same, for every schema | refused |
| `SELECT` | the rows | read |

Only the schemas the login holds `VIEW DEFINITION` on are read
(`HAS_PERMS_BY_NAME`), and among them those chosen in the scope. A foreign
key pointing into a schema the login may not see is not read: the table it
points to is not named. The connection test warns of a login that can read
rows (`SELECT` on the database, or on a schema in scope) or do more
(`db_owner`, `ALTER`, `CONTROL`…). The connector's tests run with a login
holding `VIEW DEFINITION` on one schema, and describe everything
(`tests/test_sqlserver_connector.py`).

### The connection — security

- **A public address**, resolved when connecting and connected to, as the
  others.
- **TLS required, for the whole session.** `pymssql` does not pass its
  `encryption` argument on to FreeTDS: with it alone, only the login was
  encrypted — the server's `sys.dm_exec_connections` said
  `encrypt_option FALSE` for the session. The connector gives FreeTDS its
  own configuration instead (`leka/connectors/sqlserver/freetds.conf`,
  named by `FREETDSCONF`): `encryption = require`. A test asks the server,
  as an admin, whether the connector's session is encrypted; another
  shows that a server answering the prelogin without TLS is refused
  before the login — and so the password — is sent. The certificate is
  not verified, as the others'.
- **Nothing written stays.** SQL Server has no read-only session: every
  session is **one transaction, rolled back** when it closes — a row or a
  table written in it is gone after it, which a test checks as `sa`. The
  login's permissions remain the first boundary.
- **Bounded**: 15 seconds a query, 15 seconds a lock wait
  (`LOCK_TIMEOUT`), and LEKA's session the one to give way in a deadlock
  (`DEADLOCK_PRIORITY LOW`); a 10-second login. `ApplicationIntent=ReadOnly`
  sends it to a readable replica where there is one. The session is named
  `LEKA` (`program_name`).
- FreeTDS keeps its timeouts, its configuration file and its last error's
  number **for the whole process**, not the connection: the timeouts are
  always the same, and a failure to connect is read from FreeTDS's
  messages, not its number, which may be an earlier failure's.

### What is read

Ten queries, all of `sys.*` and `INFORMATION_SCHEMA` (a test checks):

| Capability | What | Id | Container |
|---|---|---|---|
| `schemas` | name, owner, comment, and the database | the schema's name | itself |
| `tables` | schema, name, kind (`table`, `system_versioned_table`, `history_table`, `external_table`, `view`), owner, comment, rows and size (`sys.partitions`, `sys.allocation_units`); each **column** — name, type as SQL Server writes it (`nvarchar(200)`, `decimal(12,2)`, `datetime2(3)`), nullable, default (`'free'`, `sysutcdatetime()` — the parentheses SQL Server adds taken off), a computed column's `AS …`, an identity's `IDENTITY(1,1)`, a period's `GENERATED ALWAYS AS ROW START`, comment; each **constraint** — primary key, unique, foreign key with what it references and `ON DELETE`, check; each **index** as `CREATE … INDEX` would write it, with its `INCLUDE` and `WHERE`; a view's **definition** and the tables it **reads from** | `schema.table` | the schema |

A comment is the `MS_Description` extended property, as SQL Server's own
tools write it.

### Synchronisation, retention, errors

As the others: whole each pass, only what changed written; at most 20 000
tables a pass; kept 90 days.

| What | Diagnostic |
|---|---|
| The login refused — its password, or a database it has no user in (FreeTDS 20018 then 20002) | `AUTH_INVALID` |
| A schema in scope the login cannot see | `NOT_FOUND`, naming it |
| A permission missing (229, 230, 262, 297, 300) | `PERMISSION_DENIED` |
| Too slow (FreeTDS 20003), a lock waited for too long (1222) | `TIMEOUT` |
| No TLS, or not a SQL Server (20002 alone); an address that is not public; too many tables | `CONFIG_INVALID` |
| No server on the port (20009) | `NETWORK_UNREACHABLE` |
| Anything else SQL Server says | `PROVIDER_ERROR` |

### Limits

- As the others: no private network, the certificate not verified.
- A SQL login only: Microsoft Entra ID and Windows sign-in are not
  supported.
- Azure SQL Database and Managed Instance are SQL Server, but not tried
  yet; the tests run against SQL Server 2022.
- Sequences, procedures, functions, triggers, synonyms, users and grants
  are not read.

---

## Oracle

| | |
|---|---|
| Server | Oracle Database 19c or later — self-hosted, or managed (Amazon RDS for Oracle, Oracle Base Database, Autonomous Database with TLS…) — reachable from the internet, over TLS (TCPS) |
| Credentials | `username`, `password` — write-only |
| Config | `host`, `port` (2484, TCPS's), `service_name`, `schemas` — users, as Oracle writes them: `BILLING` |
| Category | `data` |
| Capabilities | `schemas` (in Oracle, a schema is a user), `tables` (tables, partitioned, temporary and external tables, views, materialized views) |
| Code | `leka/connectors/oracle/`, with `oracledb`, Oracle's driver, in its thin mode — no Oracle client to install |

### What to create in Oracle

A user of its own, that can connect, with one object privilege on each
table and view to describe:

```sql
CREATE USER leka_reader IDENTIFIED BY "…";
GRANT CREATE SESSION TO leka_reader;
BEGIN
  FOR o IN (SELECT object_name FROM dba_objects
            WHERE owner = 'BILLING' AND object_type IN ('TABLE', 'VIEW')) LOOP
    EXECUTE IMMEDIATE 'GRANT REFERENCES ON BILLING."' || o.object_name || '" TO leka_reader';
  END LOOP;
END;
/
```

Like MySQL, **Oracle shows in its `ALL_*` views only what the account holds
a privilege on**, and `REFERENCES` is the one that shows the structure and
not the data — checked against Oracle 26ai:

| Granted | What `ALL_*` shows | A row |
|---|---|---|
| `CREATE SESSION` alone | nothing | refused |
| **`REFERENCES` on a table or a view** | the table, its columns, keys, checks, indexes, comments, row count; a view **with its definition** | **refused** (`ORA-41900`) |
| `SELECT_CATALOG_ROLE` | nothing in `ALL_*` — every schema in `DBA_*`, and more (sessions, SQL texts) | refused |
| `SELECT` or `READ` | the rows | read |

`REFERENCES` is granted **object by object**: a table created later is not
seen until it is granted too — rerun the block above, or grant it with the
table. The connection test warns of an account that can read rows
(`SELECT`, `READ`, `SELECT ANY TABLE`…) or do more (`CREATE TABLE`, `DBA`…).
The connector's tests run with an account holding `REFERENCES` alone, and
describe everything (`tests/test_oracle_connector.py`).

### The connection — security

- **A public address**, resolved when connecting and connected to, as the
  others.
- **TLS required**: the connection is TCPS, and the session's own
  `NETWORK_PROTOCOL` is checked once connected (`tcps`). A port that
  speaks plain TCP is refused (`CONFIG_INVALID`), checked against a real
  one. Oracle's **native network encryption** (`SQLNET.ENCRYPTION_SERVER`)
  is not TLS, and the thin driver does not speak it: a server that offers
  only that must add a TCPS listener — a wallet with a certificate, a
  `(PROTOCOL = TCPS)` address in `listener.ora`. The certificate is not
  verified, as the others'.
- **Read-only**: every session is one transaction, `SET TRANSACTION READ
  ONLY` — a write in it is refused (`ORA-01456`), even as `SYSTEM` — rolled
  back when it closes. Each call is bounded (15 seconds), the session named
  `LEKA` (`v$session.program`).

### What is read

Eleven queries, all of the catalogue's `ALL_*`, `USER_*` and `SESSION_*`
views (a test checks):

| Capability | What | Id | Container |
|---|---|---|---|
| `schemas` | each user that owns a table or view the account may see — Oracle's own left out — and the database | the user's name | itself |
| `tables` | schema, name, kind (`table`, `partitioned_table`, `temporary_table`, `external_table`, `view`, `materialized_view`), comment, rows as of the last statistics (`NUM_ROWS`); each **column** — name, type as Oracle writes it (`VARCHAR2(200)`, `VARCHAR2(20 CHAR)`, `NUMBER(12,2)`, `TIMESTAMP(3)`), nullable, default, a virtual column's `AS (…)`, an identity's `GENERATED ALWAYS AS IDENTITY`, comment; each **constraint** — primary key, unique, foreign key with what it references and `ON DELETE`, check (a `NOT NULL`, which Oracle keeps as a check, is the column's); each **index** as `CREATE INDEX` would write it, an expression or a descending column as Oracle keeps it; a view's or a materialized view's **definition** | `SCHEMA.TABLE` | the schema |

No size: a segment's is in `DBA_SEGMENTS`, not the account's to read. No
`reads_from`: what a view reads Oracle shows only to its owner
(`ALL_DEPENDENCIES`), and LEKA does not guess it from the text.

### Synchronisation, retention, errors

As the others: whole each pass, only what changed written; at most 20 000
tables and views a pass; kept 90 days.

| What | Diagnostic |
|---|---|
| Wrong user or password, locked, expired (`ORA-01017`, `28000`, `28001`) | `AUTH_INVALID` |
| An unknown service (`DPY-6001`, `ORA-12514`); a schema in scope the account cannot see | `NOT_FOUND`, naming it |
| A privilege missing (`ORA-41900`, `01031`, `00942`, `01045`) | `PERMISSION_DENIED` |
| A call too slow (`DPY-4024`, or the connection closed on a timeout) | `TIMEOUT` |
| No TLS on the port, a session that is not `tcps`; an address that is not public; too many tables | `CONFIG_INVALID` |
| No server on the port | `NETWORK_UNREACHABLE` |
| Anything else Oracle says | `PROVIDER_ERROR` |

### Limits

- As the others: no private network, the certificate not verified.
- `REFERENCES` object by object: a new table is not seen until granted.
- Tested against Oracle 26ai; 19c has the same `ALL_*` views, not tried.
- A view's dependencies and a table's size are not read (above).
- Autonomous Database with mutual TLS (a client wallet) is not supported;
  with TLS alone and an access list letting LEKA in, it is, untried.
- Sequences, procedures, packages, triggers, synonyms, users and grants
  are not read.

---

## MongoDB

| | |
|---|---|
| Server | MongoDB — Atlas, or self-hosted — reachable from the internet |
| Credentials | `username`, `password` — write-only |
| Config | `address` (`mongodb+srv://…` or `mongodb://host:port,…`), `auth_database` (`admin`), `databases` |
| Category | `data` |
| Capabilities | `schemas` (the databases), `tables` (collections, views, time series) |
| Code | `leka/connectors/mongodb/`, with `pymongo`, MongoDB's own driver |

The address is kept to its scheme and hosts: a user and password pasted
with it — as Atlas's "Connect" gives it — are dropped, never stored in the
settings; they go in the credentials. So are the options after `?`.

### What to create in MongoDB

A role with four actions on the databases to describe, and an account
with only that role. In `mongosh`, as an admin:

```js
use admin
db.createRole({
  role: "leka_catalogue", roles: [],
  privileges: [{ resource: { db: "billing", collection: "" },
                 actions: ["listCollections", "listIndexes", "collStats", "dbStats"] }],
})
db.createUser({ user: "leka_reader", pwd: "…", roles: ["leka_catalogue"] })
```

On Atlas: **Database Access → Custom Roles**, the same four actions on the
databases, then a database user with that role alone.

What that role sees, checked against a real server: the databases it has a
privilege on and no other; each collection with its validator; **each view
with its definition**; the indexes; the counts and sizes. A `find`, a
`count`, an `insert` are refused. The connection test warns of an account
that can read documents (`find`) or write.

### The connection — security

- **Every address the driver connects to is checked.** A MongoDB
  deployment names its own hosts — an SRV record, the members a replica
  set announces — so checking the address typed is not enough. The
  connector wraps the driver's own address resolution: every host is
  resolved there, each of its addresses must be public, and the
  connection goes to what was checked; a Unix socket is refused. This
  leans on a `pymongo` internal: an upgrade that moves it fails the
  import and a test, never connects unguarded.
- **TLS required**, the certificate not verified, as the others.
- **Read-only by the role**: MongoDB has no read-only session; the
  account's role is the boundary, and the connector sends only commands
  that read — a test watches every command it sends. Each operation is
  bounded (15 seconds), the client named `LEKA` (`appname`), reads sent
  to a secondary where there is one.

### What is read

| Capability | What | Id | Container |
|---|---|---|---|
| `schemas` | each database: its collections and views counted, its size | its name | itself |
| `tables` | each collection or view: kind (`collection`, `view`, `timeseries`), estimated documents and size (`$collStats`), its **validator's fields** as columns — name, BSON type, required, description; `_id` as its key, each unique index as a unique constraint, a validator beyond `$jsonSchema` as a check; each index (fields, direction, unique, sparse, TTL, partial); a view's pipeline, and the collections it reads — the one it is on, and those its `$lookup`, `$graphLookup`, `$unionWith` name | `database.collection` | the database |

**A collection without a validator** is its name, indexes and size: its
fields are nowhere but in its documents, and LEKA reads none.

### Synchronisation, retention, errors

As the others: whole each pass, only what changed written; at most 20 000
collections a pass; kept 90 days.

| What | Diagnostic |
|---|---|
| Wrong account or password (18) | `AUTH_INVALID` |
| A database in scope the account cannot see | `NOT_FOUND`, naming it |
| An action missing (13) | `PERMISSION_DENIED` |
| Too slow (50) | `TIMEOUT` |
| No TLS; a host, or one it announced, not public; an address that leads nowhere | `CONFIG_INVALID` |
| No server answers | `NETWORK_UNREACHABLE` |
| Anything else MongoDB says | `PROVIDER_ERROR` |

### Limits

- No private network, the certificate not verified — as the others.
- Fields are the validator's, not inferred from documents.
- Not read: users, roles, the oplog, sharding.
