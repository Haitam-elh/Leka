"""Tables owned by the context module.

Where embeddings live, alongside the entity they describe — the pgvector
column this platform runs PostgreSQL 16 for. See
docs/adr/001-postgresql.md: keeping them in the same database means an
embedding and its entity are written in one transaction, so they cannot
disagree after a crash.
"""

from __future__ import annotations
