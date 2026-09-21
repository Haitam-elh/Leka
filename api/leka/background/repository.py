"""Every database query of the background module.

Three repositories, because these tables are read very different ways.

EventRepository is the ordinary one: it belongs to ONE workspace, and the
workspace comes from whoever is calling, never from the payload.

EventDispatchRepository is the dispatcher's, and deliberately is not scoped:
it sweeps every workspace, like the retention and reconciliation sweeps in
leka.ingestion.tasks. It must be used inside system_scope(), which says so in
one visible line — the session guard refuses the query otherwise.

JobRunRepository is for a table the session guard does not protect, on purpose
(see JobRun). It has two kinds of method and they must not be mixed up: the
transitions and passes, which act across every workspace and are the worker's,
and list_for_workspace / get_for_workspace, which are what a customer may see
and filter on for_workspace_id explicitly. Nothing else is safe to hand to a
request.

None of them commits. The caller owns the transaction.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from leka.background.models import Event
from leka.db import WorkspaceScopedRepository


class EventRepository(WorkspaceScopedRepository):
    async def insert_once(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        dedupe_key: str | None,
        request_id: str | None,
    ) -> Event | None:
        """Write an event, or say it was already there.

        ON CONFLICT DO NOTHING rather than looking first: a check has a race
        between the look and the write, and the constraint does not. Returns
        None when the dedupe key was already taken — which is a duplicate, not
        an error, so the caller is not made to catch anything.
        """
        statement = (
            pg_insert(Event)
            .values(
                workspace_id=self.workspace_id,
                type=event_type,
                payload=payload,
                dedupe_key=dedupe_key,
                request_id=request_id,
            )
            .on_conflict_do_nothing(constraint="uq_events_workspace_dedupe_key")
            .returning(Event)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()


__all__ = ["EventRepository"]
