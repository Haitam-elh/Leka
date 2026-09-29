"""What the production deployment files promise, checked without a server.

One environment online, `production`, on one EC2 box: the web app on
app.<domain>, the API on api.<domain>, both behind Caddy. These files are
only ever run for real on the box, so a mistake in them is found by the
first person who types the address. These tests find it first.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from leka.core.config import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
COMPOSE = DEPLOY / "docker-compose.production.yml"


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return loaded


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_runs_every_process() -> None:
    """Staging once shipped a worker and no scheduler, and nothing failed:
    the worker simply waited for work that nothing would ever dispatch."""
    services = _compose()["services"]

    assert set(services) >= {"migrate", "api", "worker", "scheduler", "web", "redis", "caddy"}
    assert services["worker"]["command"] == ["python", "-m", "leka.platform.worker"]
    assert services["scheduler"]["command"] == ["python", "-m", "leka.platform.scheduler"]


def test_every_backend_process_runs_as_production() -> None:
    """The startup guards — Secure cookies, S3, a real email sender, an https
    LEKA_WEB_URL — only bite when the environment says production."""
    services = _compose()["services"]

    for name in ("migrate", "api", "worker", "scheduler"):
        assert services[name]["environment"]["LEKA_ENVIRONMENT"] == "production", name


def test_the_web_app_is_its_own_image_of_the_same_release() -> None:
    services = _compose()["services"]

    assert "/web:" in services["web"]["image"]
    assert "/api:" in services["api"]["image"]
    assert "LEKA_RELEASE" in services["web"]["image"]


def test_caddy_serves_the_app_and_the_api_on_their_own_names() -> None:
    """leka-core.com and api. share the parent domain: that is what keeps the
    session cookie SameSite=Lax (ADR 009). The names that served the
    application before redirect to it, to the same path."""
    caddyfile = _text(DEPLOY / "Caddyfile")

    app = re.search(
        r"\{\$LEKA_APP_DOMAIN\} \{\$LEKA_APP_ALIASES\}\s*\{(?P<body>.*?)\n\}", caddyfile, re.S
    )
    assert app is not None
    assert "reverse_proxy web:3000" in app["body"]
    assert "@alias not host {$LEKA_APP_DOMAIN}" in app["body"]
    assert "redir @alias https://{$LEKA_APP_DOMAIN}{uri} permanent" in app["body"]
    assert re.search(r"\{\$LEKA_API_DOMAIN\}\s*\{[^}]*reverse_proxy api:8000", caddyfile, re.S)
    caddy_env = _compose()["services"]["caddy"]["environment"]
    assert set(caddy_env) == {"LEKA_APP_DOMAIN", "LEKA_API_DOMAIN", "LEKA_APP_ALIASES"}
    # Optional: empty, nothing redirects — and the compose file must not
    # refuse to start without it, as it does for the other two.
    assert caddy_env["LEKA_APP_ALIASES"] == "${LEKA_APP_ALIASES:-}"


def test_hsts_does_not_bind_every_name_under_the_domain() -> None:
    """Sent from leka-core.com itself, includeSubDomains would force HTTPS on
    every name under it for a year — including ones this box does not serve."""
    caddyfile = _text(DEPLOY / "Caddyfile")

    assert 'Strict-Transport-Security "max-age=31536000"' in caddyfile
    assert 'includeSubDomains"' not in caddyfile


def test_next_builds_a_standalone_server() -> None:
    """Without it the image would need the whole of node_modules to start."""
    assert re.search(r'output:\s*"standalone"', _text(REPO_ROOT / "web" / "next.config.ts"))


def test_the_api_address_is_baked_into_the_web_build() -> None:
    """NEXT_PUBLIC_* is read at BUILD time, not when the container starts:
    set on the box, it would change nothing, and the app would call
    localhost."""
    dockerfile = _text(REPO_ROOT / "web" / "Dockerfile")
    cd = _text(REPO_ROOT / ".github" / "workflows" / "cd.yml")

    assert "ARG NEXT_PUBLIC_API_URL" in dockerfile
    assert "NEXT_PUBLIC_API_URL=${{ vars.PROD_API_URL }}" in cd


def test_the_filled_in_environment_never_reaches_git() -> None:
    ignored = _text(DEPLOY / ".gitignore").split()
    assert "production.env" in ignored
    assert (DEPLOY / "production.env.example").is_file()
    assert not (DEPLOY / "production.env").exists() or "production.env" in ignored


def test_no_image_carries_a_local_env_file() -> None:
    for context in ("api", "web"):
        dockerignore = _text(REPO_ROOT / context / ".dockerignore").split()
        assert ".env" in dockerignore, context
        assert ".env.*" in dockerignore, context


def test_the_example_names_only_placeholders() -> None:
    """The example is documentation. A value that looks real is one somebody
    will leave in place."""
    for line in _text(DEPLOY / "production.env.example").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if any(word in name for word in ("PASSWORD", "SECRET", "KEY", "DSN")):
            assert value in ("", '["..."]'), f"{name} has a value in the example"


def test_the_web_image_leaves_out_the_browser_suite_whole() -> None:
    """playwright.config.ts imports e2e/, and `next build` type-checks every
    .ts file in the build context: leaving one out and not the other broke
    the image build, and only a real `docker build` showed it."""
    ignored = _text(REPO_ROOT / "web" / ".dockerignore").split()

    assert ("e2e" in ignored) == ("playwright.config.ts" in ignored)


# ── deploy.sh and the disk (CD #77) ──────────────────────────────────────────
#
# Run for real, against a `docker` and a `df` that take notes: what matters is
# the ORDER — room is made before anything is pulled — and that a disk too
# full to take a release stops the deployment before it starts.

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$1" in
  info) echo "$DOCKER_ROOT" ;;
  pull) exit 1 ;;
esac
"""

FAKE_DF = """#!/usr/bin/env bash
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/root 20971520 0 $FREE_KB 50% /"
"""


def _deploy(tmp_path: Path, *, free_mb: int) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, script in (("docker", FAKE_DOCKER), ("df", FAKE_DF)):
        (tools / name).write_text(script, encoding="utf-8")
        (tools / name).chmod(0o755)
    box = tmp_path / "opt-leka"
    box.mkdir()
    shutil.copy(DEPLOY / "deploy.sh", box / "deploy.sh")
    (box / "production.env").write_text(
        "LEKA_REGISTRY=ghcr.io/acme/leka\nLEKA_RELEASE=old\n", encoding="utf-8"
    )
    calls = tmp_path / "calls"
    calls.touch()
    result = subprocess.run(  # noqa: S603 — our own script, our own arguments
        ["bash", str(box / "deploy.sh"), "ghcr.io/acme/leka", "new"],  # noqa: S607
        env={
            "PATH": f"{tools}:{os.environ['PATH']}",
            "CALLS": str(calls),
            "DOCKER_ROOT": str(tmp_path),
            "FREE_KB": str(free_mb * 1024),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "LEKA_RELEASE=old" in (box / "production.env").read_text(encoding="utf-8")
    return result, calls.read_text(encoding="utf-8").splitlines()


def test_room_is_made_before_a_release_is_pulled(tmp_path: Path) -> None:
    """Until CD #77, old images went only AFTER a successful deployment, and
    only once a week old: a week of merges filled the disk and the pull died
    half-way. What no container uses now goes first."""
    result, calls = _deploy(tmp_path, free_mb=10_000)

    pulls = [n for n, call in enumerate(calls) if call.startswith("pull ")]
    assert pulls, calls
    assert calls.index("image prune -af") < pulls[0]
    # Every image no container uses: not a week's grace any more.
    assert not any("until=" in call for call in calls)
    # The pull failed here, and the box was left as it was — and said why.
    assert result.returncode == 1
    assert "Nothing was changed" in result.stdout
    assert "system df" in calls


def test_a_disk_too_full_for_a_release_stops_it_before_the_pull(tmp_path: Path) -> None:
    result, calls = _deploy(tmp_path, free_mb=500)

    assert result.returncode == 1
    assert not any(call.startswith("pull ") for call in calls)
    assert "500 MB free on the disk, 2048 MB needed" in result.stdout
    assert "Nothing was changed" in result.stdout
