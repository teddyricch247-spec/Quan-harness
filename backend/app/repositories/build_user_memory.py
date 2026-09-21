"""
§20 — build_user_memory: the account-level counterpart to project_memory,
named that way (not plain user_memory) because Ask keeps its own separate
ask_user_memory store in a later phase — the two are never read by each
other's loop, under any circumstance (§20's own line). Written only by
app/services/memory_extraction.py; read by agent_loop.py (WHAT_YOU_KNOW_
ABOUT_THIS_PERSON) and by the person's own direct view/edit/clear from
Connections.

No separate *_owned split here the way project_memory.py needs one — there's
no second table to verify ownership against first (a project's memory has to
be checked against the *project's* owner; an account's own memory is already
scoped by exactly the authenticated user_id the router handler already has
from its own auth dependency), so every function here is already correctly
scoped by the user_id its caller passes in.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "build_user_memory"


async def get_memory_md(user_id: str) -> str:
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).select("memory_md").eq("user_id", user_id).limit(1).execute().data
        return rows[0]["memory_md"] if rows else ""

    return await run_in_threadpool(_call)


async def set_memory_md(user_id: str, memory_md: str) -> None:
    """Upsert — an account's first-ever extraction call has no row yet. Stamps
    `updated_at` itself on every call, insert or update — same reasoning as
    project_memory.set_memory_md's own docstring: 0007's `build_user_memory`
    has no update trigger, and an upsert's ON CONFLICT path only touches
    columns present in the payload."""
    import datetime

    client = get_service_client()

    def _call():
        client.table(TABLE).upsert(
            {
                "user_id": user_id,
                "memory_md": memory_md,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).execute()

    await run_in_threadpool(_call)


async def clear(user_id: str) -> None:
    await set_memory_md(user_id, "")
