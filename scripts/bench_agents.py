"""Ask the library's agents the same questions before and after a change to
their instructions, and put the answers side by side (LEKA-447).

    api/.venv/bin/python scripts/bench_agents.py --before main \
        --after feature/LEKA-447-data-method [--agents code-review,debug-assistant] \
        [--out bench-agents]

Each side runs in its own process, on the same code and the same database,
with LEKA_AGENTS_DIR pointed at the agents/ of its git ref (git archive):
only the instructions differ. A run goes through the real runtime —
AgentRuntime.start then execute_run, as the job runner does — for the demo
account of scripts/seed.py, so its rights, its sources and its model are the
ones the screens would use. What it writes, in --out:

    <side>.json      each case: status, error, version, model, tool calls,
                     seconds, the answer
    comparison.md    each question, the two answers, and a grid to fill in
                     by hand: relevance, false findings, what is missing

It calls the model configured for the API (LEKA_GOOGLE_API_KEY, … in .env or
the environment): every case costs one deep-tier run per side. Without a
key, point it at the browser tests' stand-in (web/e2e/model-env.ts) to check
the bench itself runs — the answers then say nothing.

Like seed.py, developer tooling: it never runs in production. The runs it
starts stay in the database as any other run, under the demo account.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Two questions per agent, on the demo company (scripts/seed.py). The demo
# has no database source: data-analysis is expected to be refused there.
CASES: tuple[tuple[str, str], ...] = (
    ("code-review", "Fais la revue de la dernière pull request de acme/backend"),
    ("code-review", "Revue des changements récents sur payment-api"),
    ("security-review", "Est-ce que payment-api est exposé ?"),
    ("security-review", "Revue de sécurité de auth-service"),
    ("build-fixer", "Le build de acme/backend est cassé, que faire ?"),
    ("build-fixer", "Pourquoi la CI de user-service échoue depuis ce matin ?"),
    ("architecture-analysis", "Explique-moi l'architecture de payment-api"),
    ("architecture-analysis", "Où sont les fragilités autour de postgres-prod ?"),
    ("documentation-assistant", "Qu'est-ce qui manque dans la documentation de payment-api ?"),
    ("documentation-assistant", "Rédige une première documentation de auth-service"),
    ("test-analysis", "Que faut-il tester avant de changer postgres-prod ?"),
    ("test-analysis", "Plan de test pour le déploiement deploy-2026-09-18-1432"),
    ("debug-assistant", "payment-api renvoie des erreurs 500 depuis ce matin"),
    ("debug-assistant", "auth-service est lent depuis hier"),
    ("release-analysis", "Analyse le déploiement deploy-2026-09-18-1432"),
    ("release-analysis", "Quel risque pour la prochaine release de payment-api ?"),
    ("infrastructure-analysis", "Où tourne payment-api et qu'est-ce qui est partagé ?"),
    (
        "infrastructure-analysis",
        "Quels sont les points uniques de défaillance du compte de production ?",
    ),
    ("data-analysis", "Qui lit et qui écrit dans postgres-prod ?"),
)

CITED = re.compile(r"\[[^\]\s]{3,}\]")


def export_agents(ref: str, into: Path) -> Path:
    """agents/ as it stands at a git ref."""
    git = ["git", "-C", str(REPO), "archive", "--format=tar", ref, "agents"]
    # git from PATH and the ref the developer names: their own repository.
    archive = subprocess.run(git, check=True, capture_output=True).stdout  # noqa: S603
    with tempfile.TemporaryFile() as tar:
        tar.write(archive)
        tar.seek(0)
        with tarfile.open(fileobj=tar) as t:
            t.extractall(into, filter="data")
    return into / "agents"


async def run_side(cases: list[tuple[str, str]]) -> list[dict[str, object]]:
    """Every case, once, with the agents LEKA_AGENTS_DIR names."""
    from sqlalchemy import select

    import leka.identity  # every table known, as seed.py does
    import leka.intentions.capabilities  # noqa: F401 — its capabilities, which workflows name
    from leka.capabilities.registry import find
    from leka.capabilities.repository import CapabilityRunRepository
    from leka.capabilities.runs import execute_run
    from leka.capabilities.service import AgentRuntime, RunRefusedError
    from leka.db import session_factory, system_scope, workspace_scope
    from leka.governance.policies import subject_of
    from leka.identity import User
    from leka.platform import Workspace

    sys.path.insert(0, str(REPO / "scripts"))
    from seed import DEMO_EMAIL, WORKSPACE_SLUG

    with system_scope():
        async with session_factory() as session:
            workspace_id = (
                await session.execute(select(Workspace.id).where(Workspace.slug == WORKSPACE_SLUG))
            ).scalar_one()
            user_id = (
                await session.execute(select(User.id).where(User.email == DEMO_EMAIL))
            ).scalar_one()

    found: list[dict[str, object]] = []
    for key, text in cases:
        definition = find(key)
        case: dict[str, object] = {"agent": key, "question": text}
        if definition is None:
            found.append({**case, "status": "unknown_agent"})
            continue
        name = definition.contract.inputs[0].name if definition.contract.inputs else "demande"
        started = time.monotonic()
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                subject = await subject_of(session, workspace_id, user_id)
                assert subject is not None, "the demo account is not in the demo workspace"
                try:
                    run = await AgentRuntime(session, workspace_id).start(
                        key,
                        {name: text},
                        by=user_id,
                        permissions=frozenset(p.value for p in subject.permissions),
                    )
                except RunRefusedError as refused:
                    found.append({**case, "status": "refused", "error": refused.refusal.code})
                    print(f"  {key}: refused ({refused.refusal.code})", flush=True)
                    continue
                run_id = run.id
                await session.commit()
        await execute_run(workspace_id, run_id)
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                done = await CapabilityRunRepository(session, workspace_id).run(run_id)
                assert done is not None
                found.append(
                    {
                        **case,
                        "status": done.status,
                        "error": done.error,
                        "version": done.version,
                        "model": done.model,
                        "tool_calls": done.tool_calls,
                        "seconds": round(time.monotonic() - started, 1),
                        "answer": done.output or "",
                    }
                )
        print(f"  {key}: {found[-1]['status']}", flush=True)
    return found


def compared(before: str, after: str, a: list[dict], b: list[dict]) -> str:
    """The two sides, question by question, with the grid a person fills in."""

    def said(side: dict) -> str:
        if side.get("answer"):
            return str(side["answer"])
        return f"_Pas de réponse : {side.get('status')} {side.get('error') or ''}_"

    def figures(side: dict) -> str:
        answer = str(side.get("answer") or "")
        return (
            f"v{side.get('version', '?')} · {side.get('status')} · "
            f"{side.get('tool_calls', 0)} appels d'outils · {side.get('seconds', '?')} s · "
            f"{len(answer)} caractères · {len(CITED.findall(answer))} citations [id]"
        )

    out = [
        "# Banc d'essai des agents — avant / après",
        "",
        f"Avant : `{before}` · Après : `{after}` · même code, même base, mêmes questions.",
        "",
        "Pour chaque question : pertinence de 1 à 5, faux constats (affirmé sans appui, "
        "inventé), ce qui manque, et laquelle des deux réponses on garderait.",
    ]
    for x, y in zip(a, b, strict=True):
        out += [
            "",
            f"## {x['agent']} — « {x['question']} »",
            "",
            f"### Avant — {figures(x)}",
            "",
            said(x),
            "",
            f"### Après — {figures(y)}",
            "",
            said(y),
            "",
            "| | Avant | Après |",
            "| --- | --- | --- |",
            "| Pertinence (1-5) | | |",
            "| Faux constats | | |",
            "| Ce qui manque | | |",
            "| On garde | | |",
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", default="main")
    parser.add_argument("--after", required=True)
    parser.add_argument("--agents", help="keys, comma-separated; all by default")
    parser.add_argument("--out", type=Path, default=Path("bench-agents"))
    parser.add_argument("--side", help=argparse.SUPPRESS)  # the child's own run
    args = parser.parse_args()

    wanted = set(args.agents.split(",")) if args.agents else None
    cases = [c for c in CASES if wanted is None or c[0] in wanted]

    if args.side:
        import asyncio

        result = asyncio.run(run_side(cases))
        (args.out / f"{args.side}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        return

    args.out.mkdir(parents=True, exist_ok=True)
    sides: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for side, ref in (("avant", args.before), ("apres", args.after)):
            print(f"{side} ({ref})", flush=True)
            agents = export_agents(ref, Path(tmp) / side)
            subprocess.run(  # noqa: S603 — this script, our own interpreter
                [
                    sys.executable,
                    __file__,
                    "--after",
                    args.after,
                    "--out",
                    str(args.out),
                    "--side",
                    side,
                    *(["--agents", args.agents] if args.agents else []),
                ],
                check=True,
                env={**os.environ, "LEKA_AGENTS_DIR": str(agents)},
            )
            sides[side] = json.loads((args.out / f"{side}.json").read_text())
    report = args.out / "comparison.md"
    report.write_text(compared(args.before, args.after, sides["avant"], sides["apres"]))
    print(f"→ {report}")


if __name__ == "__main__":
    main()
