"""The intention engine's benchmark (LEKA-440), run against its reference.

What this protects: each case of tests/benchmark/intentions.yaml is asked
of LEKA on the demo company (scripts/seed.py) — read before asking, asked,
analysed, with the capabilities it names made to fail — and what LEKA did
is checked against what it must and must not do (tests/benchmark/grid.py).
The run is compared with tests/benchmark/baseline.json; a change is
refused when:
- a critical failure appears that the reference does not know — a negation
  ignored, a wrong target, required evidence missing, an action despite a
  blocking ambiguity;
- any check the reference passes fails;
- a dimension of the grid falls under its floor.
A reference that no longer says what the engine does — better, measured on
another version, cases added — is written again, with the change:
`LEKA_BENCH_WRITE=1`, reviewed in its diff (docs/benchmarks/intentions.md).

The engine reads with its rules here, whatever .env holds: the same words
give the same reading on every machine. `LEKA_BENCH_MODEL=1` lets the
configured model read (LEKA_LLM_PROVIDER, LEKA_LLM_MODEL, its key) — a run
to compare, never the reference CI holds.

`LEKA_BENCH_REPORT=<dir>`: report.json and report.md written there.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import select

from leka.capabilities.gateway import service as gateway_service
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.identity import User
from leka.intentions import brief as brief_module
from leka.intentions import reading, understanding, writing
from leka.intentions.analysis import Capability, Material, Output
from leka.intentions.analyst import PLATFORM
from leka.intentions.capabilities import CAPABILITIES
from leka.intentions.dispatch import RULES
from leka.intentions.processing import analyse_intention
from leka.knowledge.registry import MODEL_VERSION
from leka.platform import Workspace
from tests.benchmark import grid
from tests.benchmark.grid import Case, Claim, DecisionSeen, Observation
from tests.conftest import FakeIdentity
from tests.test_intention_analysis_api import queued  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
API = "/api/v1/intentions"
# No model: what LEKA reads with its rules alone.
NO_MODEL = {
    "google_api_key": None,
    "mistral_api_key": None,
    "anthropic_api_key": None,
    "llm_api_url": None,
    "llm_fallbacks": "",
}


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("leka_demo_seed", ROOT / "scripts" / "seed.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _commit() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip() or None


def measured_on(dataset: grid.Dataset, read_by: set[str]) -> dict[str, Any]:
    """What a run was measured on: two runs compare when this is the same,
    and say what differs when it is not."""
    return {
        "dataset_version": dataset.version,
        "dataset_sha256": dataset.sha256,
        "fixture": dataset.fixture,
        "company_model_version": MODEL_VERSION,
        "understanding_version": understanding.UNDERSTANDING_VERSION,
        "brief_version": brief_module.BRIEF_VERSION,
        "capabilities": {c.name: c.version for c in CAPABILITIES},
        "prompts": {
            "reading": _digest(reading.SYSTEM),
            "synthesis": _digest(writing.SYSTEM),
            "analyst": _digest(PLATFORM),
            "dispatch": _digest(RULES),
        },
        "read_by": sorted(read_by),
        "commit": _commit(),
    }


# ── asking LEKA ──────────────────────────────────────────────────────────────


def _boom(_: Material) -> Output:
    raise RuntimeError("made to fail by the benchmark")


def _failing(names: tuple[str, ...]) -> list[Capability]:
    unknown = set(names) - {c.name for c in CAPABILITIES}
    assert not unknown, f"no capability is called {sorted(unknown)}"
    return [replace(c, run=_boom) if c.name in names else c for c in CAPABILITIES]


def _names_of(understood: dict[str, Any]) -> dict[str, str]:
    scope = understood.get("scope") or {}
    things = [
        *understood.get("entities", []),
        *scope.get("entities", []),
        *scope.get("excluded", []),
    ]
    return {t["entity_id"]: t["name"] for t in things}


def _read(
    understood: dict[str, Any], brief: dict[str, Any], seen: dict[str, Any]
) -> dict[str, Any]:
    """What LEKA understood and decides before analysing."""
    names = _names_of(understood)
    scope = understood.get("scope") or {}
    slots = {s["slot"]: s for s in brief["slots"]}
    period = scope.get("period") or {}
    actions = {
        a["code"]: tuple(names.get(t, f"?{t}") for t in a["targets"]) for a in understood["actions"]
    }
    return {
        **seen,
        "mode": understood["mode"],
        "goal": understood["goal"]["code"],
        "entities": tuple(e["name"] for e in understood["entities"]),
        "excluded": tuple(e["name"] for e in scope.get("excluded", [])),
        "actions": actions,
        "system_actions": tuple(a["code"] for a in understood["actions"] if a["changes_systems"]),
        "withheld": {a["code"]: a["polarity"] for a in understood["withheld"]},
        "constraints": tuple(c["kind"] for c in scope.get("constraints", [])),
        "environments": tuple(scope.get("environments") or ()),
        "period_said": bool(period.get("explicit")),
        "expected": (slots.get("expected") or {}).get("value"),
        "decision": brief["decision"],
        "questions": tuple(
            (q["kind"], q["blocking"]) for q in brief["questions"] if q.get("answer") is None
        ),
        "read_by": (understood.get("read_by") or {}).get("method") or "rules",
    }


def _analysed(analysis: dict[str, Any] | None, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """What the analysis states, what it rests on, what it puts to a person."""
    result = (analysis or {}).get("result") or {}
    evidence = {e["id"] for e in result.get("evidence", [])}
    # What it says it does not know is stated too: a document « not known to
    # be current » is said, as an uncertainty, not as a finding.
    notes = [*result.get("uncertainties", []), *result.get("missing", [])]
    stated = [
        *(f["text"] for f in result.get("findings", [])),
        *(json.dumps(f["params"], ensure_ascii=False) for f in result.get("findings", [])),
        *(c["label"] for c in result.get("causes", [])),
        *(e["label"] for e in result.get("evidence", [])),
        *(n["text"] for n in (*result.get("summary", []), *notes)),
    ]
    ungrounded = [
        s["id"]
        for s in (*result.get("findings", []), *result.get("causes", []))
        if set(s["evidence"]) - evidence
    ]
    ungrounded += [c["id"] for c in result.get("causes", []) if not c["evidence"]]
    stands_on = {s["id"] for s in (*result.get("findings", []), *result.get("causes", []))}
    # A recommendation may follow from what is not known (document it, ask
    # differently); one that changes systems never.
    ungrounded += [
        r["id"]
        for r in result.get("recommendations", [])
        if set(r["basis"]) - stands_on
        or set(r["evidence"]) - evidence
        or (r["changes_systems"] and not r["basis"])
    ]
    explained = result.get("explanation") or {}
    return {
        "confidence": (explained.get("confidence") or {}).get("level"),
        "next_step": (explained.get("next") or {}).get("code"),
        "analysis": (analysis or {}).get("status"),
        "error": (analysis or {}).get("error"),
        "findings": tuple(s["code"] for s in (*result.get("findings", []), *notes)),
        "stated": tuple(stated),
        "causes": tuple(
            Claim(text=c["label"], evidence=tuple(c["evidence"])) for c in result.get("causes", [])
        ),
        "recommendations": tuple(
            Claim(
                text=" ".join(
                    filter(None, [r["code"], (r.get("target") or {}).get("name"), r["text"]])
                ),
                evidence=tuple(r["evidence"]),
            )
            for r in result.get("recommendations", [])
        ),
        "ungrounded": tuple(ungrounded),
        "decisions": tuple(
            DecisionSeen(
                status=d["status"],
                proposals={
                    p["action"]: tuple(t["name"] for t in p["targets"]) for p in d["proposals"]
                },
                required_approvals=d["required_approvals"],
                approvers=len(d["approvers"]),
            )
            for d in decisions
        ),
    }


async def observe(client: AsyncClient, workspace_id: uuid.UUID, case: Case) -> Observation:
    """One case asked of LEKA, as a person would, and what it did."""
    asked = {"text": case.text, "answers": list(case.answers)}
    response = await client.post(f"{API}/brief", json=asked)
    if response.status_code != 200:
        return Observation(crashed=f"brief: {response.status_code} {response.text[:200]}")
    preview = response.json()
    feasible = preview["feasibility"]
    seen: dict[str, Any] = {
        "preview_decision": preview["brief"]["decision"],
        "next": feasible["verdict"],
        "needs": tuple(n["key"] for n in feasible["needed"]),
    }
    if case.stage == "brief":
        return Observation(**_read(preview["understanding"], preview["brief"], seen))

    response = await client.post(API, json=asked)
    if response.status_code == 422:
        # Nothing kept: what LEKA refuses to start from is its answer.
        seen["final"] = "refused"
        return Observation(**_read(preview["understanding"], preview["brief"], seen))
    if response.status_code != 201:
        return Observation(crashed=f"create: {response.status_code} {response.text[:200]}")
    created = response.json()["intention"]
    seen["created"] = created["status"]
    intention_id = uuid.UUID(created["id"])
    if created["status"] == "analysing":
        try:
            await analyse_intention(
                workspace_id,
                intention_id,
                trigger="created",
                capabilities=_failing(case.faults),
            )
        except Exception as error:  # a crash is what is measured
            seen["crashed"] = f"analysis: {type(error).__name__}: {error}"
    read = await client.get(f"{API}/{intention_id}")
    if read.status_code != 200:
        return Observation(crashed=f"read: {read.status_code} {read.text[:200]}")
    detail = read.json()
    analysis = await client.get(f"{API}/{intention_id}/analysis")
    decisions = await client.get(f"{API}/{intention_id}/decisions")
    if analysis.status_code not in (200, 404) or decisions.status_code != 200:
        seen["crashed"] = f"read: {analysis.status_code} {decisions.status_code}"
    seen["final"] = detail["status"]
    seen["readiness"] = (detail.get("readiness") or {}).get("status")
    seen = _read(detail["understanding"], detail["brief"], seen)
    seen.update(
        _analysed(
            analysis.json() if analysis.status_code == 200 else None,
            decisions.json() if decisions.status_code == 200 else [],
        )
    )
    return Observation(**seen)


# ── the run ──────────────────────────────────────────────────────────────────


async def _unthrottled() -> None:
    """Forget the throttling counters: a case is one person asking once, not
    the seventieth request of the minute from the same address."""
    client = redis.from_url(str(settings.redis_url))
    try:
        keys = [key async for key in client.scan_iter("leka:ratelimit:*")]
        if keys:
            await client.delete(*keys)
    finally:
        await client.aclose()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def test_the_intention_engine_holds_its_reference(
    client: AsyncClient,
    identity: FakeIdentity,
    queued: list[tuple[uuid.UUID, str]],  # noqa: F811 — a fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not os.environ.get("LEKA_BENCH_MODEL"):
        rules_only = settings.model_copy(update=NO_MODEL)
        monkeypatch.setattr(gateway_service, "settings", rules_only)
    dataset = grid.load()
    seed = _seed_module()
    await seed.seed()
    with system_scope():
        async with session_factory() as session:
            workspace = await session.scalar(select(Workspace).where(Workspace.slug == "acme"))
            nora = await session.scalar(select(User).where(User.email == seed.DEMO_EMAIL))
    assert workspace is not None and nora is not None
    identity.sign_in(nora.id, workspace.id)

    checks: list[grid.Check] = []
    read_by: set[str] = set()
    for case in dataset.cases:
        await _unthrottled()
        seen = await observe(client, workspace.id, case)
        read_by.add(seen.read_by)
        checks += grid.check(case, seen)
    run = grid.report(dataset, checks, measured_on(dataset, read_by))

    reference = (
        json.loads(grid.BASELINE.read_text(encoding="utf-8")) if grid.BASELINE.exists() else None
    )
    comparison = grid.compare(reference, run) if reference is not None else None
    if folder := os.environ.get("LEKA_BENCH_REPORT"):
        _write(Path(folder) / "report.json", json.dumps(run, ensure_ascii=False, indent=1))
        _write(Path(folder) / "report.md", grid.markdown(run, comparison))

    if os.environ.get("LEKA_BENCH_WRITE"):
        # Never a critical regression written into the reference: a case
        # added may say a failure the engine already has, none may get worse.
        worse = [r for r in (comparison.regressions if comparison else ()) if r[2] == "critical"]
        assert not worse, f"a critical regression is never the reference: {worse}"
        under = [k for k, v in run["dimensions"].items() if v["score"] < v["floor"]]
        assert not under, f"under their floor: {under}"
        _write(
            grid.BASELINE,
            json.dumps(grid.baseline_of(run), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        )
        _write(grid.BASELINE.with_suffix(".md"), grid.markdown(run))
        return

    assert comparison is not None, "no reference: LEKA_BENCH_WRITE=1 writes it"
    assert not comparison.refused, "\n".join(
        [*comparison.refused, "", grid.markdown(run, comparison)]
    )
    assert not comparison.stale, "\n".join(
        [
            "the reference no longer says what the engine does — write it again with "
            "LEKA_BENCH_WRITE=1 and commit it with the change:",
            *comparison.stale,
        ]
    )
