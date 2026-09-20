"""
§10.3's session_events table is the append-only log every other Phase 3 piece
reads from: §16.1's SSE stream, §16.4's crash recovery
(app/services/crash_recovery.py), and §17's conversation-history context
assembly all replay this table rather than holding state anywhere else — see
those modules' own docstrings for why. `append`/`list_for_session` are
internal (agent_loop.py already knows it owns the session it's running by the
time it calls these); `list_for_session_owned` is the scoped read path for a
router endpoint the person's own client calls directly, same split as
checkpoints.py's unscoped internal helpers vs. its owned/get_owned pair.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.sessions import get_owned as get_session_owned

TABLE = "session_events"


async def append(
    session_id: str,
    role: str,
    event_type: str,
    content: dict,
    parent_event_id: int | None = None,
) -> dict:
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .insert(
                {
                    "session_id": session_id,
                    "parent_event_id": parent_event_id,
                    "role": role,
                    "event_type": event_type,
                    "content": content,
                }
            )
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def list_for_session(session_id: str, after_id: int | None = None) -> list[dict]:
    """Ordered oldest-first — every caller (context assembly, crash recovery,
    SSE catch-up) wants chronological order. `after_id` lets a reconnecting
    SSE client ask for only what it missed."""
    client = get_service_client()

    def _call():
        query = client.table(TABLE).select("*").eq("session_id", session_id)
        if after_id is not None:
            query = query.gt("id", after_id)
        return query.order("id").execute().data

    return await run_in_threadpool(_call)


async def list_for_session_owned(user_id: str, session_id: str, after_id: int | None = None) -> list[dict] | None:
    session = await get_session_owned(user_id, session_id)
    if session is None:
        return None
    return await list_for_session(session_id, after_id=after_id)


async def latest_id_for_session(session_id: str) -> int | None:
    """Used when starting a fresh turn loop, to record where 'this turn's new
    events' begin — not needed for correctness (event content carries enough
    to reconstruct anything), just avoids re-scanning the whole log."""
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).select("id").eq("session_id", session_id).order("id", desc=True).limit(1).execute().data
        return rows[0]["id"] if rows else None

    return await run_in_threadpool(_call)
