"""Tables owned by the intentions module.

An intention is the durable record of "someone asked for this, here is what
we decided, here is who approved it". It outlives the request that created
it, because an action taken against a customer's production system must be
answerable months later.
"""

from __future__ import annotations
