"""
Create/list/get/archive/delete a session row (Phase 1), plus `update_fields`
(Phase 3) — agent_loop.py's own internal status/plan/turn_iteration_count
writes once a turn loop is actually running against a session. Everything
else here stays Phase 1's original scope: ownership scoped by joining
through projects, same shape as the RLS policies in 0005_sessions.sql, kept
consistent deliberately (§5's "defense in depth" — the repository's own
scoping shouldn't rely on RLS being correct, and vice versa).
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "sessions"


async def list_for_project(user_id: str, project_id: str) -> list[dict] | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
            .data
        )

    return await run_in_threadpool(_call)


async def create_for_project(user_id: str, project_id: str, title: str | None) -> dict | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return client.table(TABLE).insert({"project_id": project_id, "title": title}).execute().data[0]

    row = await run_in_threadpool(_call)
    await _enforce_concurrency_cap(project_id, just_created_session_id=row["id"])
    return row


async def _enforce_concurrency_cap(project_id: str, just_created_session_id: str) -> None:
    """§23.4/§25: 'max 2 writable sessions per project. Opening a 3rd forces one
    of the existing two (the least-recently-used) to become permanently
    read-only.' §25 confirms this happens at the application layer on open,
    not by rejecting the new session outright — so session creation always
    succeeds; this just demotes whichever *other* writable session was used
    least recently, if doing so is now necessary.

    'Least recently used' — updated_at ascending, the only recency signal this
    phase's schema has (no turn loop yet to generate richer activity data;
    Phase 3's turn loop will naturally keep updated_at fresh on real activity)."""
    writable = await list_writable_for_project(project_id)
    others = [s for s in writable if s["id"] != just_created_session_id]
    if len(others) < 2:
        return
    lru = min(others, key=lambda s: s["updated_at"])
    await set_read_only(lru["id"], reason="concurrency_cap")


async def list_writable_for_project(project_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .select("id,updated_at")
            .eq("project_id", project_id)
            .eq("read_only", False)
            .neq("status", "archived")
            .execute()
            .data
        )

    return await run_in_threadpool(_call)


async def set_read_only(session_id: str, reason: str) -> None:
    client = get_service_client()

    def _call():
        client.table(TABLE).update({"read_only": True, "read_only_reason": reason}).eq("id", session_id).execute()

    await run_in_threadpool(_call)


async def close_others_to_read_only(project_id: str, except_session_id: str, reason: str) -> None:
    """§23.4 checkpoint restore: 'Closes every other currently-open session on
    that project to permanently read-only.'"""
    client = get_service_client()

    def _call():
        (
            client.table(TABLE)
            .update({"read_only": True, "read_only_reason": reason})
            .eq("project_id", project_id)
            .neq("id", except_session_id)
            .neq("status", "archived")
            .execute()
        )

    await run_in_threadpool(_call)


async def get_owned(user_id: str, session_id: str) -> dict | None:
    """Reads the session then verifies its project belongs to user_id — no direct
    user_id column on sessions itself (it's project-scoped, per §10.3)."""
    client = get_service_client()

    def _fetch():
        rows = client.table(TABLE).select("*").eq("id", session_id).limit(1).execute().data
        return rows[0] if rows else None

    session = await run_in_threadpool(_fetch)
    if session is None:
        return None
    project = await get_project_for_user(user_id, session["project_id"])
    if project is None:
        return None
    return session


async def update_status(user_id: str, session_id: str, status: str) -> dict | None:
    session = await get_owned(user_id, session_id)
    if session is None:
        return None
    client = get_service_client()

    def _call():
        return client.table(TABLE).update({"status": status}).eq("id", session_id).execute().data[0]

    return await run_in_threadpool(_call)


async def update_fields(session_id: str, fields: dict) -> dict:
    """Internal/unscoped — for agent_loop.py's own status/plan/
    turn_iteration_count writes once it's already running against a session
    whose ownership the router validated on the way in (same
    already-authorized-by-the-time-we-get-here reasoning as checkpoints.py's
    unscoped `create`). Always stamps `updated_at` itself: 0005_sessions.sql
    has no update trigger for it, and `_enforce_concurrency_cap`'s LRU
    eviction depends on this column reflecting genuine recent activity, per
    that function's own docstring."""
    import datetime

    client = get_service_client()
    payload = {**fields, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def _call():
        return client.table(TABLE).update(payload).eq("id", session_id).execute().data[0]

    return await run_in_threadpool(_call)


async def delete_events_after(session_id: str, after_created_at: str) -> None:
    """§23.4 restore: '...every message ... created after it, within that
    session.' session_events has no writer yet (Phase 3's turn loop is the
    first) so this is correct-but-currently-a-no-op, the same standing Phase 1
    left checkpoints/session_events/approval_requests in generally — see
    /docs/PHASE1_NOTES.md."""
    client = get_service_client()

    def _call():
        client.table("session_events").delete().eq("session_id", session_id).gt(
            "created_at", after_created_at
        ).execute()

    await run_in_threadpool(_call)


async def delete_owned(user_id: str, session_id: str) -> bool:
    session = await get_owned(user_id, session_id)
    if session is None:
        return False
    client = get_service_client()

    def _call():
        client.table(TABLE).delete().eq("id", session_id).execute()

    await run_in_threadpool(_call)
    return True
