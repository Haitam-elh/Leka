"""Where a language model may be called from (LEKA-394, LEKA-429), checked
on the code itself.

What these protect:
- No business logic speaks to a vendor: a vendor's address, or its SDK,
  appears in the gateway's providers (leka/capabilities/gateway/) and
  nowhere else — a new provider is a provider there, never a call in a
  feature.
- A feature has a model work through the LLM runtime, not the gateway: the
  gateway is imported by leka.capabilities — the runtime, the catalogue's
  routing, the agent runs — and by the API of its own settings, and by no
  feature module (intentions, intelligence, knowledge, context…).
- The check can fail: it finds what it looks for in the gateway itself.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

LEKA = Path(__file__).resolve().parents[1] / "leka"
GATEWAY = LEKA / "capabilities" / "gateway"

VENDOR_HOSTS = re.compile(
    r"generativelanguage\.googleapis\.com|aiplatform\.googleapis\.com|api\.mistral\.ai"
    r"|api\.openai\.com|openai\.azure\.com|api\.anthropic\.com"
)
VENDOR_SDKS = frozenset(
    {"openai", "anthropic", "mistralai", "google.genai", "google.generativeai", "vertexai"}
)
# Who may import the gateway itself: the module that owns model access,
# and the API of the workspace's model settings.
MAY_IMPORT_GATEWAY = ("leka/capabilities/", "leka/api/model_gateway.py")


def _python() -> list[Path]:
    return sorted(p for p in LEKA.rglob("*.py") if "__pycache__" not in p.parts)


def _where(path: Path) -> str:
    return "leka/" + path.relative_to(LEKA).as_posix()


def _imports(path: Path) -> list[tuple[str, list[str]]]:
    """(module, names) of every import in a file."""
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, [alias.name for alias in node.names]))
    return found


def test_no_business_logic_speaks_to_a_vendor() -> None:
    hosts = [
        _where(path)
        for path in _python()
        if GATEWAY not in path.parents and VENDOR_HOSTS.search(path.read_text(encoding="utf-8"))
    ]
    assert not hosts, f"a vendor's address outside the gateway: {hosts}"
    sdks = [
        (_where(path), module)
        for path in _python()
        for module, _ in _imports(path)
        if any(module == sdk or module.startswith(f"{sdk}.") for sdk in VENDOR_SDKS)
    ]
    assert not sdks, f"a vendor SDK imported: {sdks}"


def test_features_have_a_model_work_through_the_runtime() -> None:
    reaching = sorted(
        {
            _where(path)
            for path in _python()
            for module, names in _imports(path)
            if (
                module.startswith("leka.capabilities.gateway")
                or (module == "leka.capabilities" and "Gateway" in names)
            )
            and not _where(path).startswith(MAY_IMPORT_GATEWAY)
        }
    )
    assert not reaching, (
        f"these reach the gateway directly: {reaching} — have the LLM runtime do the work "
        "(leka.capabilities.LLMRuntime, a Task)"
    )


def test_the_check_finds_what_it_looks_for() -> None:
    """In the gateway itself, where they belong: else the checks above pass
    over nothing."""
    providers = [p for p in GATEWAY.glob("*.py") if VENDOR_HOSTS.search(p.read_text("utf-8"))]
    assert len(providers) >= 3, [p.name for p in providers]
    features = [
        path
        for path in _python()
        for module, names in _imports(path)
        if module == "leka.capabilities" and {"LLMRuntime", "Task"} & set(names)
    ]
    assert {"reading.py", "writing.py", "enrichment.py", "job.py"} <= {p.name for p in features}
