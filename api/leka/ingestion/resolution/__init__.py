"""Entity resolution (LEKA-357): which candidates of a workspace's sources
are one real thing — merged, linked, or said ambiguous — with how sure and
why. Rules: docs/resolution.md."""

from leka.ingestion.resolution.engine import (
    RESOLVER_VERSION,
    Decision,
    Identity,
    KeySeen,
    Mention,
    Resolution,
    resolve,
)

__all__ = [
    "RESOLVER_VERSION",
    "Decision",
    "Identity",
    "KeySeen",
    "Mention",
    "Resolution",
    "resolve",
]
