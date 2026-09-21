"""What the API promises a client, checked rather than described.

LEKA-333's Definition of Done says "security and error-handling behaviour
verified". This file takes that at its word: one error shape whatever
failed, a request id that ties a response to a log line, cursors that cannot
be forged into someone else's data, sorting that is a whitelist, a rate
limit that announces itself, and a schema that is not published to the
internet in production.

The two tests that need production run it in a subprocess. The environment
is read once, at import, which is the right design and makes it awkward to
fake in-process — and faking it is exactly how you end up verifying a code
path that is not the one production takes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog
from httpx import AsyncClient

from leka.api.request_id import REQUEST_ID_HEADER
from leka.core.errors import INTERNAL_ERROR_MESSAGE
from leka.db.pagination import encode_cursor
from tests.conftest import FakeIdentity, error_code, error_fields, error_message

pytestmark = pytest.mark.integration

API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]


# ── One shape, whatever failed ───────────────────────────────────────────────


async def test_an_invalid_body_answers_in_our_shape_not_pydantic_s(
    client: AsyncClient,
) -> None:
    """The most common error a client meets, and the one FastAPI answers
    differently from everything else.

    Before LEKA-333 this returned {"detail": [{"loc": [...], "msg": ...}]},
    which is why web/lib/api.ts carried a parser for exactly that shape.
    """
    response = await client.post(f"{API}/auth/register", json={"email": "not-an-email"})

    assert response.status_code == 422
    assert error_code(response) == "validation_failed"

    fields = error_fields(response)
    assert "password" in fields, f"the missing field is not reported: {fields}"
    assert "email" in fields

    body = response.json()
    assert set(body) == {"error"}, f"the body has keys outside the envelope: {sorted(body)}"


async def test_a_path_that_matches_nothing_answers_in_our_shape(
    client: AsyncClient,
) -> None:
    """A 404 from the router never reaches a route, so it is the response a
    client is most likely to meet first — and the one a handler registered
    on a router would miss."""
    response = await client.get(f"{API}/no-such-thing")

    assert response.status_code == 404
    assert error_code(response) == "not_found"
    assert response.json()["error"]["request_id"]


# ── The request id ───────────────────────────────────────────────────────────


async def test_the_request_id_is_the_same_in_the_body_and_the_header(
    client: AsyncClient,
) -> None:
    """Both carry it, and they agree.

    "Give me the request id" only replaces an hour of archaeology if the
    value a person reads off their screen is the one we can search for.
    """
    response = await client.get(f"{API}/no-such-thing")

    from_header = response.headers[REQUEST_ID_HEADER]
    from_body = response.json()["error"]["request_id"]

    assert from_header == from_body, "the id in the body is not the one in the header"
    assert len(from_header) == 26, "not a ULID"


async def test_an_id_from_a_proxy_is_honoured(client: AsyncClient) -> None:
    """Something in front of us has usually stamped one already, and two
    identifiers for the same request is worse than none."""
    response = await client.get(
        f"{API}/no-such-thing", headers={REQUEST_ID_HEADER: "from-the-proxy-1"}
    )

    assert response.headers[REQUEST_ID_HEADER] == "from-the-proxy-1"
    assert response.json()["error"]["request_id"] == "from-the-proxy-1"


async def test_the_request_id_reaches_the_log_lines(capsys: pytest.CaptureFixture[str]) -> None:
    """The half that makes it worth having.

    Checked against the REAL logging configuration rather than with
    structlog.testing.capture_logs, which bypasses the processor chain — and
    merge_contextvars, the processor this whole mechanism relies on, is in
    that chain. Capturing logs the easy way would have passed whether or not
    the binding worked.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    from leka.api.request_id import request_id_middleware
    from leka.core.config import settings as live_settings
    from leka.core.logging import configure_logging

    configure_logging(live_settings)

    app = FastAPI()
    app.middleware("http")(request_id_middleware)
    logger = structlog.get_logger("contract-test")

    @app.get("/noisy")
    async def noisy() -> dict[str, bool]:
        logger.info("a_line_from_inside_a_request")
        return {"ok": True}

    async with Client(transport=ASGITransport(app=app), base_url="https://t") as inner:
        await inner.get("/noisy", headers={REQUEST_ID_HEADER: "traced-42"})

    written = capsys.readouterr().out
    assert "a_line_from_inside_a_request" in written, "the line was never logged"
    assert "traced-42" in written, f"the log line does not carry the request id:\n{written}"


async def test_an_absurd_request_id_is_not_echoed(
    client: AsyncClient,
) -> None:
    """The value lands in a log line and a response header.

    Taken on trust, it is a way to write whatever somebody likes into both.
    """
    response = await client.get(
        f"{API}/no-such-thing",
        headers={REQUEST_ID_HEADER: "a" * 200 + "\nfake-log-line"},
    )

    returned = response.headers[REQUEST_ID_HEADER]
    assert returned != "a" * 200 + "\nfake-log-line"
    assert len(returned) == 26, "a rejected id should be replaced by one of ours"


# ── Cursors ──────────────────────────────────────────────────────────────────


async def test_a_forged_cursor_is_refused_cleanly(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """Never a 500. Clients keep cursors in URLs and users share those URLs;
    a cursor that no longer means anything is an ordinary Tuesday."""
    identity.sign_in(uuid.uuid4(), None)

    for forged in ("nonsense", "a.b", "", "eyJzIjoiaWQifQ.wrong-signature"):
        response = await client.get(f"{API}/workspaces", params={"cursor": forged})
        assert response.status_code == 400, (
            f"cursor {forged!r} produced {response.status_code}, not a clean refusal"
        )
        assert error_code(response) == "invalid_cursor"


async def test_a_cursor_cannot_carry_a_workspace(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """The workspace comes from the principal, never from the request.

    Signed with the real secret rather than forged, which is the stronger
    test: this is a cursor the server accepts, carrying a field it must
    ignore. Checking that a BADLY signed cursor is rejected would prove only
    that the signature works.
    """
    import base64
    import hashlib
    import hmac

    from leka.core.config import settings

    identity.sign_in(uuid.uuid4(), None)
    stranger = uuid.uuid4()

    payload = json.dumps(
        {
            "s": "name",
            "d": "desc",
            "k": "zzz",
            "i": str(uuid.uuid4()),
            "workspace_id": str(stranger),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(
        settings.secret_key.get_secret_value().encode(), payload, hashlib.sha256
    ).digest()

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    cursor = f"{b64(payload)}.{b64(signature)}"

    response = await client.get(f"{API}/workspaces", params={"cursor": cursor})

    assert response.status_code == 200, (
        f"a validly signed cursor was refused: {response.text[:200]}"
    )
    assert str(stranger) not in response.text, (
        "a workspace named inside a cursor reached the response"
    )


async def test_a_cursor_issued_for_another_ordering_is_refused(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """Reusing a cursor while changing ?sort= would walk one ordering from a
    position taken in another, and return nonsense quietly — which is worse
    than an error, because nobody would notice."""
    identity.sign_in(uuid.uuid4(), None)

    cursor = encode_cursor(sort="name", direction="desc", key="x", row_id=uuid.uuid4())
    response = await client.get(f"{API}/workspaces", params={"cursor": cursor, "sort": "slug"})

    assert response.status_code == 400
    assert error_code(response) == "invalid_cursor"


# ── Sorting ──────────────────────────────────────────────────────────────────


async def test_a_sort_field_outside_the_whitelist_is_refused(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """A query parameter must never reach the ORM. That is how a client ends
    up sorting by a column nobody meant to expose."""
    identity.sign_in(uuid.uuid4(), None)

    response = await client.get(f"{API}/workspaces", params={"sort": "settings"})

    assert response.status_code == 400
    assert error_code(response) == "invalid_sort"
    assert "name" in error_message(response), "the refusal should say what IS allowed"


async def test_a_page_size_beyond_the_ceiling_is_refused(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """Without a ceiling, ?limit=1000000 is a way to turn one request into a
    full table read."""
    identity.sign_in(uuid.uuid4(), None)

    response = await client.get(f"{API}/workspaces", params={"limit": 100000})

    assert response.status_code == 422
    assert error_code(response) == "validation_failed"


# ── Rate limiting ────────────────────────────────────────────────────────────


async def test_the_rate_limit_announces_itself_on_every_response(
    client: AsyncClient,
) -> None:
    """A client that can see it coming slows down. One that only learns at
    429 has already been refused."""
    response = await client.get(f"{API}/no-such-thing")

    assert response.headers["RateLimit-Limit"]
    assert int(response.headers["RateLimit-Remaining"]) >= 0
    assert int(response.headers["RateLimit-Reset"]) > 0


async def test_the_rate_limit_actually_refuses(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lowered for the test rather than sending three hundred requests.

    The limit itself is a number in configuration; what is worth checking is
    that exceeding it refuses, says so in our error shape, and tells the
    client when to come back.
    """
    from leka.api import ratelimit as api_ratelimit
    from leka.core import ratelimit as core_ratelimit

    monkeypatch.setattr(
        api_ratelimit, "DEFAULT_LIMIT", core_ratelimit.Limit(attempts=3, window_seconds=60)
    )

    statuses = [(await client.get(f"{API}/no-such-thing")).status_code for _ in range(5)]
    refused = await client.get(f"{API}/no-such-thing")

    assert 429 in statuses or refused.status_code == 429, f"never refused: {statuses}"
    assert error_code(refused) == "rate_limited"
    assert int(refused.headers["Retry-After"]) > 0
    assert refused.headers["RateLimit-Remaining"] == "0"


async def test_health_is_never_rate_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy probe must not make the service look down.

    That would be this mechanism inventing the outage it exists to survive.
    """
    from leka.api import ratelimit as api_ratelimit
    from leka.core import ratelimit as core_ratelimit

    monkeypatch.setattr(
        api_ratelimit, "DEFAULT_LIMIT", core_ratelimit.Limit(attempts=1, window_seconds=60)
    )

    statuses = [(await client.get(f"{API}/health")).status_code for _ in range(5)]

    assert 429 not in statuses, f"the health probe was rate limited: {statuses}"


# ── Production ───────────────────────────────────────────────────────────────


def _in_production(snippet: str) -> str:
    """Run a snippet against the real application, with LEKA_ENVIRONMENT=production.

    A subprocess, because the environment is read once at import. Faking it
    in-process would verify a code path production does not take, which is
    the failure this is meant to catch.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "api",
        env={
            "PATH": "/usr/bin:/bin",
            "LEKA_ENVIRONMENT": "production",
            "LEKA_DATABASE_URL": "postgresql+asyncpg://leka:leka@127.0.0.1:5432/leka_test",
            "LEKA_REDIS_URL": "redis://127.0.0.1:6379/0",
            "LEKA_SECRET_KEY": "ci-only-not-a-real-secret",
            "LEKA_ENCRYPTION_KEYS": '["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="]',
            # Production refuses these otherwise — see the startup guards.
            "LEKA_SESSION_COOKIE_SECURE": "true",
            "LEKA_OBJECT_STORE": "s3",
            "LEKA_S3_BUCKET": "not-used-by-this-test",
            "LEKA_S3_ACCESS_KEY_ID": "not-used",
            "LEKA_S3_SECRET_ACCESS_KEY": "not-used",
        },
        check=False,
    )
    assert result.returncode == 0, f"subprocess failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout


def test_the_schema_is_not_published_in_production() -> None:
    """On a B2B SaaS, /docs open to anyone is a free map of the attack
    surface: every route, every field, every enumeration, kept current by
    us. The schema is still GENERATED — CI checks api-types.ts for drift —
    but it is not served."""
    output = _in_production(
        "import asyncio, json\n"
        "from httpx import AsyncClient, ASGITransport\n"
        "from leka.main import app\n"
        "async def main():\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='https://t') as c:\n"
        "        docs = await c.get('/api/v1/docs')\n"
        "        schema = await c.get('/api/v1/openapi.json')\n"
        "        print(json.dumps({'docs': docs.status_code, 'schema': schema.status_code,\n"
        "                          'generated': len(app.openapi()['paths'])}))\n"
        "asyncio.run(main())\n"
    )
    result = json.loads(output.strip().splitlines()[-1])

    assert result["docs"] == 404, "/docs is reachable in production"
    assert result["schema"] == 404, "/openapi.json is reachable in production"
    assert result["generated"] > 10, "the schema stopped being generated at all"


def test_an_unhandled_exception_in_production_leaks_nothing() -> None:
    """A 500 says something failed and gives the request id. The traceback,
    the SQL and the table names go to the log."""
    output = _in_production(
        "import asyncio, json\n"
        "from fastapi import APIRouter\n"
        "from httpx import AsyncClient, ASGITransport\n"
        "from leka.main import app\n"
        "scratch = APIRouter()\n"
        "@scratch.get('/boom')\n"
        "async def boom():\n"
        "    raise RuntimeError('SELECT password_hash FROM users WHERE id = 42')\n"
        "app.include_router(scratch, prefix='/api/v1')\n"
        "async def main():\n"
        "    transport = ASGITransport(app=app, raise_app_exceptions=False)\n"
        "    async with AsyncClient(transport=transport, base_url='https://t') as c:\n"
        "        r = await c.get('/api/v1/boom')\n"
        "        print(json.dumps({'status': r.status_code, 'body': r.text}))\n"
        "asyncio.run(main())\n"
    )
    result = json.loads(output.strip().splitlines()[-1])

    assert result["status"] == 500
    body = result["body"]

    for leak in ("password_hash", "SELECT", "RuntimeError", "Traceback", "users", "/leka/"):
        assert leak not in body, f"a 500 leaked {leak!r}:\n{body}"

    parsed = json.loads(body)
    assert parsed["error"]["code"] == "internal_error"
    assert parsed["error"]["message"] == INTERNAL_ERROR_MESSAGE
    assert parsed["error"]["request_id"], "a 500 with no request id is unreportable"


# ── The documentation must agree with the code ───────────────────────────────


def test_the_api_document_describes_the_shape_we_actually_return() -> None:
    """docs/api.md is what somebody integrating reads before writing a line.

    A document describing a body we do not send is worse than no document:
    it is wrong with authority. The same reasoning as the permissions matrix
    and the retention table.
    """
    document = (REPO_ROOT / "docs" / "api.md").read_text(encoding="utf-8")

    for element in ("request_id", "next_cursor", '"error"', "X-Request-ID", "RateLimit-"):
        assert element in document, f"docs/api.md never mentions {element}"

    assert "invalid_cursor" in document, "the cursor refusal is not documented"
    assert "/api/v1" in document, "the base path is not stated"


def test_the_adr_records_the_decisions_this_ticket_made() -> None:
    """An ADR that omits the argument is a changelog entry.

    Checked for the four decisions that cannot be changed later without
    breaking a client, and for the two deliberate departures — a reviewer
    should find them stated rather than have to notice them.
    """
    adr = (REPO_ROOT / "docs" / "adr" / "011-api-conventions.md").read_text(encoding="utf-8")

    for decision in ("cursor", "envelope", "v2", "Deprecation"):
        assert decision.lower() in adr.lower(), f"ADR 011 does not cover {decision}"

    assert "per caller" in adr.lower() or "keyed by caller" in adr.lower(), (
        "the rate-limit key is a departure from what was asked and must be stated"
    )
    assert "no index" in adr.lower(), (
        "the sortable fields without an index are an exception and must be stated"
    )


# ── The cursor's own encoding ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("datetime", datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=UTC)),
        ("uuid", uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")),
        ("string", "acme-corp"),
        ("integer", 42),
    ],
)
def test_a_sort_key_survives_the_cursor_round_trip(label: str, key: object) -> None:
    """A cursor carries the last row's sort value through JSON and back.

    Datetimes and UUIDs do not survive that on their own, so they are
    tagged and rebuilt. The uuid branch has no route sorting by one today —
    it is tested because the code offers it, and an encoder that silently
    returned a string for one type would corrupt the comparison rather than
    fail.
    """
    from leka.db.pagination import decode_cursor, encode_cursor

    row_id = uuid.uuid4()
    cursor = encode_cursor(sort="created_at", direction="desc", key=key, row_id=row_id)

    decoded_key, decoded_id = decode_cursor(cursor, sort="created_at", direction="desc")

    assert decoded_key == key, f"{label} did not survive the round trip"
    assert type(decoded_key) is type(key), f"{label} came back as {type(decoded_key).__name__}"
    assert decoded_id == row_id


def test_a_cursor_signed_by_us_but_nonsense_inside_is_refused() -> None:
    """Correctly signed, correctly shaped, and still unusable.

    Only we can produce this — which is the point. It is what an older
    encoding of ours looks like after a change, and it must refuse rather
    than raise something a caller does not expect.
    """
    import base64
    import hashlib
    import hmac

    from leka.core.config import settings
    from leka.db.pagination import CursorError, decode_cursor

    payload = json.dumps(
        {"s": "created_at", "d": "desc", "k": "x", "i": "not-a-uuid"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(
        settings.secret_key.get_secret_value().encode(), payload, hashlib.sha256
    ).digest()

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    with pytest.raises(CursorError):
        decode_cursor(f"{b64(payload)}.{b64(signature)}", sort="created_at", direction="desc")


def test_a_cursor_of_an_unknown_value_type_is_refused() -> None:
    """The encoding may change. A cursor from before that change must be
    refused, not guessed at."""
    import base64
    import hashlib
    import hmac

    from leka.core.config import settings
    from leka.db.pagination import CursorError, decode_cursor

    payload = json.dumps(
        {"s": "created_at", "d": "desc", "k": {"t": "decimal", "v": "1.5"}, "i": str(uuid.uuid4())},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(
        settings.secret_key.get_secret_value().encode(), payload, hashlib.sha256
    ).digest()

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    with pytest.raises(CursorError):
        decode_cursor(f"{b64(payload)}.{b64(signature)}", sort="created_at", direction="desc")


# ── Who a rate limit counts against ──────────────────────────────────────────


def test_an_anonymous_caller_is_counted_by_address_not_lumped_together() -> None:
    """Behind a proxy, every request arrives from the same socket.

    Without reading X-Forwarded-For, one noisy visitor would exhaust the
    bucket for everybody else on the internet — the limiter would become
    the outage.
    """
    from starlette.requests import Request

    from leka.api.ratelimit import caller_key

    def request_from(headers: list[tuple[bytes, bytes]], client: tuple[str, int] | None) -> Request:
        return Request(
            {"type": "http", "headers": headers, "client": client, "method": "GET", "path": "/"}
        )

    behind_proxy = caller_key(
        request_from([(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")], ("10.0.0.1", 1234))
    )
    direct = caller_key(request_from([], ("203.0.113.9", 1234)))

    assert behind_proxy == "i:203.0.113.7", "the first hop is the caller, not the proxy"
    assert direct == "i:203.0.113.9"
    assert behind_proxy != direct


def test_a_signed_in_caller_is_counted_by_session_and_the_token_is_hashed() -> None:
    """A Redis key is read over shoulders, dumped by KEYS, exported by
    monitoring. The session token is a credential and must not be one of
    those keys in clear."""
    from starlette.requests import Request

    from leka.api.ratelimit import caller_key
    from leka.core.config import settings

    token = "a-real-looking-session-token"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "client": ("203.0.113.9", 1234),
            "headers": [(b"cookie", f"{settings.session_cookie_name}={token}".encode())],
        }
    )

    key = caller_key(request)

    assert key.startswith("s:"), "a signed-in caller should be counted by session"
    assert token not in key, "the session token appears in a Redis key in clear"
