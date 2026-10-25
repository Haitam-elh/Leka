"""python -m leka_architect — the same as the `leka-architect` command."""

from __future__ import annotations

import sys

from .cli import main

sys.exit(main())
