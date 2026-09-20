from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "mcp_servers"
OVERRIDES_TABLE = "mcp_tool_overrides"


async def list_for_user(user_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("user_id", user_id).order("created_at").execute().data

    return await run_in_threadpool(_call)


async def get_for_user(user_id: str, server_id: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", server_id)
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


async def update_for_user(user_id: str, server_id: str, fields: dict) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .update(fields)
            .eq("user_id", user_id)
            .eq("id", server_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def delete_for_user(user_id: str, server_id: str) -> bool:
    """Cascades to mcp_tool_overrides and every project's project_mcp_access grant
    via the on delete cascade FKs in 0002/0004 — matches §9.2's 'Disconnecting
    hard-deletes the mcp_servers row, cascading to overrides and every project's
    project_mcp_access grant.'"""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("id", server_id)
            .execute()
            .data
        )
        return len(rows) > 0

    return await run_in_threadpool(_call)


async def list_overrides(server_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return client.table(OVERRIDES_TABLE).select("*").eq("mcp_server_id", server_id).execute().data

    return await run_in_threadpool(_call)


async def upsert_override(server_id: str, tool_name: str, permission_state: str | None) -> dict:
    client = get_service_client()

    def _call():
        return (
            client.table(OVERRIDES_TABLE)
            .upsert(
                {"mcp_server_id": server_id, "tool_name": tool_name, "permission_state": permission_state},
                on_conflict="mcp_server_id,tool_name",
            )
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def delete_overrides_not_in(server_id: str, current_tool_names: list[str]) -> None:
    """§9.2: 'a permission override whose tool_name no longer appears is deleted' —
    called after a refresh handshake with the freshly discovered tool list."""
    client = get_service_client()
    existing = await list_overrides(server_id)
    stale = [o["tool_name"] for o in existing if o["tool_name"] not in current_tool_names]
    if not stale:
        return

    def _call():
        client.table(OVERRIDES_TABLE).delete().eq("mcp_server_id", server_id).in_(
            "tool_name", stale
        ).execute()

    await run_in_threadpool(_call)
