"""
§10.3's approval_requests table. `create` is internal (agent_loop.py, already
running against an authorized session); `get_owned`/`resolve_owned` are the
scoped pair the approval-response router endpoint calls directly, same split
as session_events.py.
"""
import datetime

from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.sessions import get_owned as get_session_owned

TABLE = "approval_requests"


async def create(session_id: str, action_type: str, payload: dict) -> dict:
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .insert({"session_id": session_id, "action_type": action_type, "payload": payload})
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def get_pending_for_session(session_id: str) -> dict | None:
    """At most one pending approval per session at a time — the turn loop
    always pauses on the first Ask-gated call it hits rather than batching
    several (§16.2's pseudocode processes the mutating partition strictly
    sequentially, one call at a time)."""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("session_id", session_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def get_owned(user_id: str, approval_id: str) -> dict | None:
    client = get_service_client()

    def _fetch():
        rows = client.table(TABLE).select("*").eq("id", approval_id).limit(1).execute().data
        return rows[0] if rows else None

    row = await run_in_threadpool(_fetch)
    if row is None:
        return None
    session = await get_session_owned(user_id, row["session_id"])
    if session is None:
        return None
    return row


async def resolve_owned(user_id: str, approval_id: str, approved: bool) -> dict | None:
    row = await get_owned(user_id, approval_id)
    if row is None:
        return None
    if row["status"] != "pending":
        return row  # already resolved (a double-click, a stale reconnect) — idempotent, not an error
    client = get_service_client()
    status = "approved" if approved else "rejected"

    def _call():
        return (
            client.table(TABLE)
            .update({"status": status, "resolved_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            .eq("id", approval_id)
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)
