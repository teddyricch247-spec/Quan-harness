"""
One function per table per operation, user_id a non-optional parameter in the
function signature itself (§5) — a new call site has to go out of its way to omit
the scope rather than having to remember to add it.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "llm_credentials"


async def list_for_user(user_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("user_id", user_id).order("created_at").execute().data

    return await run_in_threadpool(_call)


async def get_for_user(user_id: str, credential_id: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", credential_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def create(user_id: str, row: dict) -> dict:
    client = get_service_client()

    def _call():
        payload = {**row, "user_id": user_id}
        return client.table(TABLE).insert(payload).execute().data[0]

    return await run_in_threadpool(_call)


async def update_for_user(user_id: str, credential_id: str, fields: dict) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .update(fields)
            .eq("user_id", user_id)
            .eq("id", credential_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def delete_for_user(user_id: str, credential_id: str) -> bool:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("id", credential_id)
            .execute()
            .data
        )
        return len(rows) > 0

    return await run_in_threadpool(_call)


async def clear_default_for_user(user_id: str) -> None:
    """Called before setting a new default, since only one row may have is_default=true
    per user (unique index in 0002_connections.sql)."""
    client = get_service_client()

    def _call():
        client.table(TABLE).update({"is_default": False}).eq("user_id", user_id).eq(
            "is_default", True
        ).execute()

    await run_in_threadpool(_call)


async def get_default_for_user(user_id: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("is_default", True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)
