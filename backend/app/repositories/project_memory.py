"""
§20 — project_memory (the curated, size-bounded index) and
project_memory_log (the append-only raw material behind it). Both are
project-scoped. Neither is ever touched by the agent directly — no tool
exists for either — so the *unscoped* functions below (get_memory_md,
set_memory_md, append_log) are the internal path app/services/
memory_extraction.py and agent_loop.py use, the same already-authorized-by-
the-time-we-get-here reasoning sessions_repo.update_fields documents for its
own internal writes. The *_owned functions are the scoped path for the
project's own Settings page (§20's "manual control" line) — view, edit, or
clear, directly, never through the agent.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "project_memory"
LOG_TABLE = "project_memory_log"


async def get_memory_md(project_id: str) -> str:
    """"" (never None) when no row exists yet — a brand new project before
    its first completed-or-stuck turn, or a project whose memory was
    cleared, which resets to "" rather than deleting the row (see
    clear_owned below)."""
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).select("memory_md").eq("project_id", project_id).limit(1).execute().data
        return rows[0]["memory_md"] if rows else ""

    return await run_in_threadpool(_call)


async def set_memory_md(project_id: str, memory_md: str) -> None:
    """Upsert — a project's first-ever extraction call has no row yet. Stamps
    `updated_at` itself on every call, insert or update: 0007's `project_memory`
    has no update trigger for it, and an upsert's ON CONFLICT path only
    touches columns actually present in the payload — the column's own
    `default now()` only ever fires on a genuine first insert, the same gap
    sessions_repo.update_fields's own docstring documents for `sessions`."""
    import datetime

    client = get_service_client()

    def _call():
        client.table(TABLE).upsert(
            {
                "project_id": project_id,
                "memory_md": memory_md,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).execute()

    await run_in_threadpool(_call)


async def append_log(project_id: str, session_id: str, report: str) -> None:
    client = get_service_client()

    def _call():
        client.table(LOG_TABLE).insert({"project_id": project_id, "session_id": session_id, "report": report}).execute()

    await run_in_threadpool(_call)


# --- Owned (scoped) reads/writes for the project's own Settings page ---


async def get_owned(user_id: str, project_id: str) -> str | None:
    """None means the project itself wasn't found/owned (404 material for
    the router calling this); "" is a legitimate real answer (project
    exists, nothing written to its memory yet) — the two must stay
    distinguishable, which is why this returns str | None rather than just
    falling back to get_memory_md's own "" default."""
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    return await get_memory_md(project_id)


async def update_owned(user_id: str, project_id: str, memory_md: str) -> bool:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return False
    await set_memory_md(project_id, memory_md)
    return True


async def clear_owned(user_id: str, project_id: str) -> bool:
    """§20: "view, edit, or clear" — clear resets memory_md to "", the
    curated index only. project_memory_log (the raw material a rebuild
    would read from) is deliberately untouched: §20 describes the log as
    existing so the index "can be rebuilt if a bad extraction ever corrupts
    it," and a person clearing today's (possibly bad) summary shouldn't
    also destroy the raw history that a future rebuild — manual or
    otherwise — would need."""
    return await update_owned(user_id, project_id, "")
