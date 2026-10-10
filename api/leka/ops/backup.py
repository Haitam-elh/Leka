"""Backups that are proven to restore (LEKA-408).

    python -m leka.ops.backup dump FILE [--upload]
        A logical dump of the database, and beside it FILE.manifest.json:
        every table's row count, the schema's revision, the dump's sha256 —
        all read from ONE snapshot, the very one the dump is taken from
        (pg_export_snapshot), so the counts are the dump's own, exact even
        on a live database. --upload: both to the backup bucket
        (LEKA_BACKUP_BUCKET, its own credentials, encrypted at rest), and
        the time of the last good backup told to the alerts.

    python -m leka.ops.backup verify FILE
        Restored into a throwaway database, every table counted and compared
        with the manifest; the sha256 checked first. Says how long the
        restore took — the RTO, measured — and drops the throwaway database.
        Exit 1 on any difference: a backup that does not restore is not one.

Where pg_dump and pg_restore come from: the machine's own, or a container's
(LEKA_PG_TOOLS="docker exec -i leka-postgres", or "docker run --rm -i
--network host postgres:16"); the database is named by its URL either way.
docs/operations.md § Backup and restore is the procedure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg

from leka.core.config import settings

LAST_BACKUP = "leka:ops:backup:last"


def libpq_url(url: str) -> str:
    """postgresql+asyncpg://… as the PostgreSQL tools read it."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _tools(name: str) -> list[str]:
    return [*shlex.split(os.environ.get("LEKA_PG_TOOLS", "")), name]


def _run(command: list[str], *, write: Path | None = None, read: Path | None = None) -> None:
    """One PostgreSQL tool, its output to `write` or its input from `read`."""
    with (
        write.open("wb") if write else Path(os.devnull).open("wb") as out,
        read.open("rb") if read else Path(os.devnull).open("rb") as into,
    ):
        done = subprocess.run(  # noqa: S603 — the tools named by the operator
            command, stdout=out, stdin=into, stderr=subprocess.PIPE, check=False
        )
    if done.returncode != 0:
        tool = next(part for part in command if part.startswith("pg_"))
        raise RuntimeError(f"{tool} failed: {done.stderr.decode()[-500:]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _counts(conn: asyncpg.Connection) -> dict[str, int]:
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    counts: dict[str, int] = {}
    for row in tables:
        name = row["tablename"]
        # A name from pg_tables, quoted: the catalogue's, not anyone's input.
        query = f'SELECT count(*) FROM public."{name}"'  # noqa: S608
        counts[name] = int(await conn.fetchval(query))
    return counts


@dataclass(frozen=True)
class Dumped:
    path: Path
    manifest: Path
    tables: int
    rows: int
    size: int
    seconds: float


async def dump(path: Path, *, url: str | None = None) -> Dumped:
    """The dump and its manifest, from one snapshot."""
    source = libpq_url(url or str(settings.database_url))
    began = time.monotonic()
    conn = await asyncpg.connect(source)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            snapshot = await conn.fetchval("SELECT pg_export_snapshot()")
            counts = await _counts(conn)
            revision = await conn.fetchval("SELECT version_num FROM alembic_version")
            # While this transaction holds the snapshot open.
            await asyncio.to_thread(
                _run,
                [*_tools("pg_dump"), "-Fc", f"--snapshot={snapshot}", "-d", source],
                write=path,
            )
    finally:
        await conn.close()
    manifest = path.with_name(path.name + ".manifest.json")
    size = path.stat().st_size  # noqa: ASYNC240 — a one-shot command, nothing waits on it
    manifest.write_text(
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                "revision": revision,
                "sha256": _sha256(path),
                "size": size,
                "tables": counts,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return Dumped(path, manifest, len(counts), sum(counts.values()), size, time.monotonic() - began)


@dataclass(frozen=True)
class Verified:
    ok: bool
    differences: dict[str, tuple[int, int | None]]  # table: (expected, restored)
    tables: int
    rows: int
    seconds: float


def _with_database(url: str, name: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{name}"))


async def verify(path: Path, *, url: str | None = None, keep: bool = False) -> Verified:
    """Restored into a throwaway database beside the source, counted, compared."""
    manifest = json.loads(path.with_name(path.name + ".manifest.json").read_text())
    if _sha256(path) != manifest["sha256"]:
        return Verified(False, {"<sha256>": (0, None)}, 0, 0, 0.0)
    source = libpq_url(url or str(settings.database_url))
    scratch = f"leka_restore_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_with_database(source, "postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        await admin.close()
    began = time.monotonic()
    try:
        await asyncio.to_thread(
            _run,
            [
                *_tools("pg_restore"),
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "-d",
                _with_database(source, scratch),
            ],
            read=path,
        )
        seconds = time.monotonic() - began
        conn = await asyncpg.connect(_with_database(source, scratch))
        try:
            restored = await _counts(conn)
        finally:
            await conn.close()
    finally:
        if not keep:
            admin = await asyncpg.connect(_with_database(source, "postgres"))
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
            finally:
                await admin.close()
    expected: dict[str, int] = manifest["tables"]
    differences = {
        table: (count, restored.get(table))
        for table, count in expected.items()
        if restored.get(table) != count
    }
    return Verified(not differences, differences, len(restored), sum(restored.values()), seconds)


async def upload(dumped: Dumped) -> str:
    """Both files to the backup bucket — and the alerts told it happened."""
    import boto3
    import redis.asyncio as redis

    bucket = os.environ.get("LEKA_BACKUP_BUCKET")
    if not bucket:
        raise RuntimeError("LEKA_BACKUP_BUCKET is not set.")
    client = boto3.client(
        "s3",
        region_name=os.environ.get("LEKA_BACKUP_REGION"),
        aws_access_key_id=os.environ.get("LEKA_BACKUP_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("LEKA_BACKUP_SECRET_ACCESS_KEY"),
    )
    prefix = f"{settings.environment}/{datetime.now(UTC).strftime('%Y/%m/%d/%H%M%S')}"
    for file in (dumped.path, dumped.manifest):
        client.upload_file(
            str(file),
            bucket,
            f"{prefix}/{file.name}",
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )
    told = redis.from_url(str(settings.redis_url))
    try:
        await told.set(
            LAST_BACKUP,
            json.dumps({"at": datetime.now(UTC).isoformat(), "key": prefix, "size": dumped.size}),
        )
    finally:
        await told.aclose()
    return prefix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.ops.backup")
    commands = parser.add_subparsers(dest="command", required=True)
    taking = commands.add_parser("dump", help="dump the database, with its manifest")
    taking.add_argument("file", type=Path)
    taking.add_argument("--upload", action="store_true")
    checking = commands.add_parser("verify", help="restore a dump aside and compare")
    checking.add_argument("file", type=Path)
    checking.add_argument("--keep", action="store_true", help="keep the restored database")
    args = parser.parse_args(argv)

    if args.command == "dump":
        dumped = asyncio.run(dump(args.file))
        sys.stdout.write(
            f"dumped {dumped.tables} tables, {dumped.rows} rows, {dumped.size} bytes"
            f" in {dumped.seconds:.1f}s → {dumped.path} (+ {dumped.manifest.name})\n"
        )
        if args.upload:
            sys.stdout.write(f"uploaded to {asyncio.run(upload(dumped))}\n")
        return 0
    verified = asyncio.run(verify(args.file, keep=args.keep))
    if verified.ok:
        sys.stdout.write(
            f"restored and verified: {verified.tables} tables, {verified.rows} rows,"
            f" restore took {verified.seconds:.1f}s\n"
        )
        return 0
    for table, (expected, restored) in sorted(verified.differences.items()):
        sys.stderr.write(f"MISMATCH {table}: expected {expected}, restored {restored}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
