"""Tables owned by the governance module.

The audit trail. Append-only by intent: a row is written when something
happens and never updated, because an audit log that can be edited is not
an audit log.
"""

from __future__ import annotations
