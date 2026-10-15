"""
§21 — Project Knowledge: human-authored notes, never touched by the agent
(no tool exists for it). CRUD lives entirely behind the project's own
Settings page (the *_owned functions below); `list_for_project` is the
unscoped internal read agent_loop.py uses each turn-loop iteration to check
trigger conditions (app/services/project_knowledge.py's pure matching
logic), same already-authorized-by-the-time-we-get-here reasoning as
project_memory.py's own unscoped functions.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "project_knowledge"


async def list_for_project(project_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("project_id", project_id).order("created_at").execute().data

    return await run_in_threadpool(_call)


async def list_owned(user_id: str, project_id: str) -> list[dict] | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    return await list_for_project(project_id)


async def create_owned(
    user_id: str, project_id: str, name: str, body: str, trigger_type: str, trigger_value: str
) -> dict | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .insert(
                {
                    "project_id": project_id,
                    "name": name,
                    "body": body,
                    "trigger_type": trigger_type,
                    "trigger_value": trigger_value,
                }
            )
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def update_owned(user_id: str, project_id: str, note_id: str, fields: dict) -> dict | None:
    """Always stamps `updated_at` itself: 0007_memory_and_project_knowledge.sql
    has no update trigger for it (same gap sessions_repo.update_fields's own
    docstring documents for `sessions`), so without this an edited note would
    report a stale `updated_at` — its original creation time — forever,
    despite ProjectKnowledgeOut returning that field to the API."""
    import datetime

    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()
    payload = {**fields, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def _call():
        rows = client.table(TABLE).update(payload).eq("id", note_id).eq("project_id", project_id).execute().data
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def delete_owned(user_id: str, project_id: str, note_id: str) -> bool:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return False
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).delete().eq("id", note_id).eq("project_id", project_id).execute().data
        return len(rows) > 0

    return await run_in_threadpool(_call)
