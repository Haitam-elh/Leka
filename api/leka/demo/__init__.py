"""A demonstration of LEKA, on a company that does not exist (LEKA-449).

Someone who has not connected their tools yet can see what LEKA does with
them: a workspace of their own, marked a demonstration, whose sources are
Nova Retail's — GitHub, Jira, Datadog, Confluence — replayed by their
connectors (leka.connectors.demo), read by the pipeline as a customer's
are. Nothing of it reaches a real system, and nothing of a customer's is
in it:

- its data is fictive, and it is its own workspace: nothing in it is in
  anyone else's, nothing of anyone else's in it;
- its sources answer from leka/connectors/demo/world.py, never their
  vendor: their `http()` refuses;
- what would reach outside — a source added, an endpoint of its actions,
  its own model, a payment, an invitation — governance refuses in it
  (DEMO_REFUSED), whoever asks;
- its AI credits are its own, as any workspace's: what is asked in it
  takes nothing from its person's real workspace.

One per person. Opened again, it is the same; started afresh, the one
before is erased and a new one made: each person starts from a clean
state, and what they did in it no one else sees.
"""

from leka.demo.schemas import DemoRead
from leka.demo.service import DEMO_NAME, DemoService

__all__ = ["DEMO_NAME", "DemoRead", "DemoService"]
