"""
§23.4. Ownership is scoped by joining through sessions -> projects, same shape as
0005_sessions.sql's RLS policy — kept consistent deliberately, same reasoning as
app/repositories/sessions.py's own docstring (§5's defense in depth).
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "checkpoints"


async def create(project_id: str, session_id: str, git_commit_sha: str, conversation_snapshot: list) -> dict:
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .insert(
                {
                    "project_id": project_id,
                    "session_id": session_id,
                    "git_commit_sha": git_commit_sha,
                    "conversation_snapshot": {"events": conversation_snapshot},
                }
            )
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def list_for_project_ids_oldest_first(project_id: str) -> list[dict]:
    """Every field needed for FIFO eviction (id, created_at) — kept separate from
    list_for_project (below) so the eviction pure-logic function in
    app/services/checkpoints.py can be handed exactly what it needs and unit
    tested against plain lists, no DB involved."""
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .select("id,created_at")
            .eq("project_id", project_id)
            .order("created_at")
            .execute()
            .data
        )

    return await run_in_threadpool(_call)


async def delete_many(checkpoint_ids: list[str]) -> None:
    if not checkpoint_ids:
        return
    client = get_service_client()

    def _call():
        client.table(TABLE).delete().in_("id", checkpoint_ids).execute()

    await run_in_threadpool(_call)


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


async def get_owned(user_id: str, checkpoint_id: str) -> dict | None:
    client = get_service_client()

    def _fetch():
        rows = client.table(TABLE).select("*").eq("id", checkpoint_id).limit(1).execute().data
        return rows[0] if rows else None

    row = await run_in_threadpool(_fetch)
    if row is None:
        return None
    project = await get_project_for_user(user_id, row["project_id"])
    if project is None:
        return None
    return row


async def get_active_session_id(project_id: str) -> str | None:
    """§23.4: 'follows whichever session most recently edited that project's
    workspace' — the session_id of this project's single most recent checkpoint
    (checkpoints_project_created_idx from 0006 is what keeps this cheap)."""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("session_id")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0]["session_id"] if rows else None

    return await run_in_threadpool(_call)


async def delete_after(session_id: str, after_created_at: str) -> None:
    """§23.4 restore: 'Permanently deletes every ... checkpoint created after it,
    within that session.'"""
    client = get_service_client()

    def _call():
        client.table(TABLE).delete().eq("session_id", session_id).gt("created_at", after_created_at).execute()

    await run_in_threadpool(_call)
