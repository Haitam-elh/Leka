"""Tables owned by the ingestion module.

Ingestion writes entities and relationships, but it does not own them —
leka.knowledge does. What ingestion owns is the record of its own work: what
ran, over which source, what it produced, what it could not parse.

A failed parse is data, not an exception to swallow. It is how we find out a
vendor changed a payload shape.
"""

from __future__ import annotations
