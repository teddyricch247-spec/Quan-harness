"""
§26 — Scheduling / Proactive Scanning. CRUD lives entirely behind the
project's own Settings page (the *_owned functions below, ownership checked
by joining through projects — same pattern project_knowledge.py's repository
uses for the identical reason). `list_enabled`/`mark_run` are the unscoped
internal reads/writes app/services/scheduler.py's background poll loop uses
— there is no "current user" on a request nobody sent, so these can't be
scoped by user_id the way the *_owned functions are; the loop instead reads
every enabled schedule across every account, the same
already-authorized-by-the-time-we-get-here reasoning app/repositories/
sessions.py's own update_fields docstring gives for its unscoped write.
"""
import datetime

from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "project_schedules"


async def list_owned(user_id: str, project_id: str) -> list[dict] | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("project_id", project_id).order("created_at").execute().data

    return await run_in_threadpool(_call)


async def get_owned(user_id: str, project_id: str, schedule_id: str) -> dict | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("id", schedule_id)
            .eq("project_id", project_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def create_owned(
    user_id: str,
    project_id: str,
    description: str,
    frequency: str,
    cron_expression: str | None,
    enabled: bool,
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
                    "description": description,
                    "frequency": frequency,
                    "cron_expression": cron_expression,
                    "enabled": enabled,
                }
            )
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def update_owned(user_id: str, project_id: str, schedule_id: str, fields: dict) -> dict | None:
    """Always stamps `updated_at` itself — 0009_scheduling.sql has no update
    trigger for it, same gap project_knowledge_repo.update_owned's own
    docstring documents (and works around the same way) for that table."""
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()
    payload = {**fields, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def _call():
        rows = (
            client.table(TABLE)
            .update(payload)
            .eq("id", schedule_id)
            .eq("project_id", project_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def delete_owned(user_id: str, project_id: str, schedule_id: str) -> bool:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return False
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).delete().eq("id", schedule_id).eq("project_id", project_id).execute().data
        return len(rows) > 0

    return await run_in_threadpool(_call)


async def list_enabled() -> list[dict]:
    """Unscoped — every enabled schedule across every account, for
    scheduler.py's own poll tick to run scheduler_rules.is_due against.
    Deliberately does not filter on anything else (a project that's since
    had its workspace deleted, say) — scheduler.py's own per-schedule
    handling is what decides what to do when the project a schedule points
    at can no longer actually be found, not this query."""
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("enabled", True).execute().data

    return await run_in_threadpool(_call)


async def mark_run(schedule_id: str, session_id: str, ran_at: datetime.datetime) -> None:
    """The one write scheduler.py's poll loop makes to the schedule row
    itself, immediately after successfully starting the session for a run —
    see scheduler.py's own docstring for why this has to happen before
    agent_loop.start_turn is called, not after."""
    client = get_service_client()

    def _call():
        client.table(TABLE).update({"last_run_at": ran_at.isoformat(), "last_session_id": session_id}).eq(
            "id", schedule_id
        ).execute()

    await run_in_threadpool(_call)
