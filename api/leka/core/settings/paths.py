"""Where the repository root is, for settings that hold relative paths.

Its own module because several domains need it and none of them owns it.
"""

from __future__ import annotations

from pathlib import Path

# api/leka/core/settings/paths.py -> settings -> core -> leka -> api -> repo
REPO_ROOT = Path(__file__).resolve().parents[4]

__all__ = ["REPO_ROOT"]
