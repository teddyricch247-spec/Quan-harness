from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "projects"
WORKSPACES_TABLE = "project_workspaces"
ACCESS_TABLE = "project_mcp_access"


async def list_for_user(user_id: str) -> list[dict]:
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("user_id", user_id).order("created_at").execute().data

    return await run_in_threadpool(_call)


async def get_for_user(user_id: str, project_id: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", project_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def get_by_id(project_id: str) -> dict | None:
    """Unscoped lookup for internal service-to-service calls whose caller has
    already verified ownership on the way in (e.g. a router handler that called
    get_for_user first) — same pattern as get_workspace() below. Never call this
    directly from a router in place of get_for_user."""
    client = get_service_client()

    def _call():
        rows = client.table(TABLE).select("*").eq("id", project_id).limit(1).execute().data
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def create(user_id: str, row: dict) -> dict:
    client = get_service_client()

    def _call():
        payload = {**row, "user_id": user_id}
        return client.table(TABLE).insert(payload).execute().data[0]

    return await run_in_threadpool(_call)


async def update_for_user(user_id: str, project_id: str, fields: dict) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .update(fields)
            .eq("user_id", user_id)
            .eq("id", project_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def delete_for_user(user_id: str, project_id: str) -> bool:
    """§24: 'Removes Quan Harness's own record and every session/credential-
    selection/checkpoint tied to it (cascading per §10's foreign keys). Does not
    touch the actual GitHub repository or the underlying Fly.io Sprite's own
    billing account resource.'"""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("id", project_id)
            .execute()
            .data
        )
        return len(rows) > 0

    return await run_in_threadpool(_call)


async def create_workspace_stub(project_id: str, sprite_handle: str) -> dict:
    """Phase 1 only creates the row so the schema linkage is real — no actual
    Fly.io Sprite gets provisioned until the Workspace Service (Phase 2)."""
    client = get_service_client()

    def _call():
        return (
            client.table(WORKSPACES_TABLE)
            .insert({"project_id": project_id, "sprite_handle": sprite_handle, "billing_state": "cold"})
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def get_workspace(project_id: str) -> dict | None:
    client = get_service_client()

    def _call():
        rows = (
            client.table(WORKSPACES_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def update_workspace(project_id: str, fields: dict) -> dict:
    """Phase 2: workspace_service.py calls this as it provisions/wakes/sleeps the
    real Fly Machine behind a project — sprite_handle moves from Phase 1's
    `pending-*` placeholder to a real Fly Machine id here, and billing_state
    starts reflecting the Machine's actual started/stopped state."""
    client = get_service_client()

    def _call():
        return (
            client.table(WORKSPACES_TABLE)
            .update(fields)
            .eq("project_id", project_id)
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


async def set_harness_branch_ready(project_id: str) -> None:
    """§25: flips once Push creates `harness/workspace` for the first time, so
    later Pushes know to update it rather than create-then-push."""
    client = get_service_client()

    def _call():
        client.table(TABLE).update({"harness_branch_ready": True}).eq("id", project_id).execute()

    await run_in_threadpool(_call)


async def get_connector_access(project_id: str) -> list[str]:
    client = get_service_client()

    def _call():
        rows = client.table(ACCESS_TABLE).select("mcp_server_id").eq("project_id", project_id).execute().data
        return [r["mcp_server_id"] for r in rows]

    return await run_in_threadpool(_call)


async def set_connector_access(project_id: str, connector_ids: list[str]) -> None:
    """§9.3: 'a plain many-to-many toggle from the project's Settings, not a copy of
    the server's configuration.' Replaces the full grant set in one operation."""
    client = get_service_client()

    def _call():
        client.table(ACCESS_TABLE).delete().eq("project_id", project_id).execute()
        if connector_ids:
            client.table(ACCESS_TABLE).insert(
                [{"project_id": project_id, "mcp_server_id": cid} for cid in connector_ids]
            ).execute()

    await run_in_threadpool(_call)


async def grant_connector_access(project_id: str, connector_ids: list[str]) -> None:
    """Used by the New Project flow (§12 step 3) — additive, project starts with none."""
    if not connector_ids:
        return
    client = get_service_client()

    def _call():
        client.table(ACCESS_TABLE).insert(
            [{"project_id": project_id, "mcp_server_id": cid} for cid in connector_ids]
        ).execute()

    await run_in_threadpool(_call)
