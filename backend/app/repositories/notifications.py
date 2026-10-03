"""
§23.8's notification system (project_notifications, 0011_preview.sql).

Notify-only: a row here is information shown to the person, with nothing attached
that runs. The lifecycle is deliberately small:

    open ──dismiss──▶ dismissed          (the person said "I've seen this")
      │                   │
      └──resolve──▶ resolved ◀──(never auto-reopened; a *new* row is raised
                                 if the same kind shows up again with a
                                 different detail_key)

`raise_or_update` is what makes this safe to call on every deploy: an identical
open notification is refreshed in place, an identical *dismissed* one stays
dismissed (the person isn't nagged about the same thing twice), and only a
genuinely different detail_key re-opens the matter.
"""
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "project_notifications"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def list_for_project(user_id: str, project_id: str, include_closed: bool = False) -> list[dict] | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        q = client.table(TABLE).select("*").eq("project_id", project_id)
        if not include_closed:
            q = q.eq("status", "open")
        return q.order("created_at", desc=True).limit(50).execute().data

    return await run_in_threadpool(_call)


async def raise_or_update(
    project_id: str,
    *,
    kind: str,
    source: str,
    title: str,
    body: str,
    detail_key: str | None,
    detail: dict | None = None,
    deploy_run_id: str | None = None,
) -> dict | None:
    """Returns the open row (new or refreshed), or None if the same thing was
    already dismissed and nothing about it changed."""
    client = get_service_client()
    detail = detail or {}

    def _latest():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("kind", kind)
            .neq("status", "resolved")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    existing = await run_in_threadpool(_latest)

    if existing is not None and existing["status"] == "open":
        def _refresh():
            return (
                client.table(TABLE)
                .update({"title": title, "body": body, "detail_key": detail_key, "detail": detail,
                         "deploy_run_id": deploy_run_id, "source": source, "updated_at": _now()})
                .eq("id", existing["id"])
                .execute()
                .data[0]
            )

        return await run_in_threadpool(_refresh)

    if existing is not None and existing["status"] == "dismissed" and existing.get("detail_key") == detail_key:
        return None  # same thing, already seen and dismissed — don't nag

    def _insert():
        return (
            client.table(TABLE)
            .insert({"project_id": project_id, "kind": kind, "status": "open", "source": source, "title": title,
                     "body": body, "detail_key": detail_key, "detail": detail, "deploy_run_id": deploy_run_id})
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_insert)


async def dismiss_owned(user_id: str, project_id: str, notification_id: str) -> bool:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return False
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .update({"status": "dismissed", "dismissed_at": _now(), "updated_at": _now()})
            .eq("id", notification_id)
            .eq("project_id", project_id)
            .eq("status", "open")
            .execute()
            .data
        )

    return bool(await run_in_threadpool(_call))


async def resolve_open(project_id: str, *, kinds: list[str] | None = None, source: str | None = None) -> int:
    """System-side: close open notifications whose cause has gone away (a later
    deploy succeeded; every previously-missing variable is now set)."""
    client = get_service_client()

    def _call():
        q = client.table(TABLE).update({"status": "resolved", "resolved_at": _now(), "updated_at": _now()}).eq(
            "project_id", project_id).eq("status", "open")
        if kinds:
            q = q.in_("kind", kinds)
        if source:
            q = q.eq("source", source)
        return len(q.execute().data or [])

    return await run_in_threadpool(_call)


async def get_open(project_id: str, kind: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE).select("*").eq("project_id", project_id).eq("kind", kind).eq("status", "open").limit(1).execute().data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)
