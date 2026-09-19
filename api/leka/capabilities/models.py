"""Tables owned by the capabilities module.

Where a model call is recorded: which agent, which context, what came back,
what it cost. Not for billing — for being able to answer "why did LEKA say
that?" three weeks later.

Agents themselves are never stored here. They are files in agents/
(architecture rule 8).
"""

from __future__ import annotations
