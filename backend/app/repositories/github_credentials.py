from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "github_credentials"


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
    client = get_service_client()

    def _call():
        client.table(TABLE).update({"is_default": False}).eq("user_id", user_id).eq(
            "is_default", True
        ).execute()

    await run_in_threadpool(_call)


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


async def projects_using_credential(user_id: str, credential_id: str) -> list[dict]:
    """Used by the disconnect flow (§24): 'Disconnecting a credential currently
    selected by one or more projects leaves those projects with a broken selection,
    surfaced clearly on each affected project's page.'"""
    client = get_service_client()

    def _call():
        return (
            client.table("projects")
            .select("id,name")
            .eq("user_id", user_id)
            .eq("github_credential_id", credential_id)
            .execute()
            .data
        )

    return await run_in_threadpool(_call)
