"""What LEKA's agents, guides and skills never carry (2026-10-18,
2026-11-05): a credit. They are LEKA's own, written in its words; their
text names no outside source, no copyright, no « adapted from » line, and
an agent's deliverable speaks as LEKA.
"""

from __future__ import annotations

import re

CREDIT = re.compile(
    r"<sub>|©|copyright \(c\)"
    r"|adapt(?:é|e|ed)\b[^\n]{0,20}\b(?:à partir|from)\b"
    r"|inspiré (?:de|par)|\bcredits?\b",
    re.IGNORECASE,
)


def carries_a_credit(text: str) -> bool:
    """Whether a text carries a credit line, a copyright or an « adapted from »."""
    return bool(CREDIT.search(text))
