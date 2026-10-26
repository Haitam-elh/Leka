"""An organisation's logo (2026-10-25): text by default — its name, never a
brand's mark taken without its agreement —, an image when its admin gives
one, shown in the header to its members.

    keep_logo()   the image given, checked — a PNG, JPEG or WebP, its bytes
                  what it says, 512 KB at most — kept in object storage
                  under the workspace's prefix; the one before it removed
    drop_logo()   removed: its name again
    logo_of()     where it is kept, and what it is — None without one

Kept with the workspace (settings["logo"]): its key, its type, when it was
given — never set from WorkspacePreferences, only here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from leka.platform.models import Workspace
from leka.platform.storage import ObjectStore, from_bytes, workspace_prefix

MAX_LOGO_BYTES = 512 * 1024
# Each type and how its first bytes say it: a file that is not what its
# type says is refused, whatever it is called. No SVG: a script can hide in
# one.
SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class LogoRefusedError(ValueError):
    """Why a logo is not kept: said by its code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _checked(content_type: str, payload: bytes) -> str:
    kind = content_type.split(";")[0].strip().lower()
    if kind not in SIGNATURES:
        raise LogoRefusedError("unsupported_type")
    if not payload:
        raise LogoRefusedError("empty")
    if len(payload) > MAX_LOGO_BYTES:
        raise LogoRefusedError("too_large")
    if not any(payload.startswith(mark) for mark in SIGNATURES[kind]) or (
        kind == "image/webp" and payload[8:12] != b"WEBP"
    ):
        raise LogoRefusedError("not_what_it_says")
    return kind


def logo_of(workspace: Workspace) -> dict[str, str] | None:
    said = (workspace.settings or {}).get("logo")
    if not isinstance(said, dict) or not isinstance(said.get("key"), str):
        return None
    return {k: str(v) for k, v in said.items()}


async def keep_logo(
    workspace: Workspace,
    payload: bytes,
    *,
    content_type: str,
    store: ObjectStore,
    now: datetime | None = None,
) -> dict[str, str]:
    """The logo given, kept — LogoRefusedError otherwise, nothing kept."""
    kind = _checked(content_type, payload)
    before = logo_of(workspace)
    key = f"{workspace_prefix(workspace.id)}branding/logo-{uuid.uuid4()}.{EXTENSIONS[kind]}"
    await store.put(key, from_bytes(payload), content_type=kind)
    said = {
        "key": key,
        "type": kind,
        "updated_at": (now or datetime.now(UTC)).isoformat(),
    }
    workspace.settings = {**(workspace.settings or {}), "logo": said}
    if before is not None and before["key"] != key:
        await store.delete(before["key"])
    return said


async def drop_logo(workspace: Workspace, *, store: ObjectStore) -> bool:
    """Its logo removed — True when it had one."""
    before = logo_of(workspace)
    if before is None:
        return False
    workspace.settings = {k: v for k, v in (workspace.settings or {}).items() if k != "logo"}
    await store.delete(before["key"])
    return True
