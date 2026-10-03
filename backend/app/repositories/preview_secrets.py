"""
§23.8's Secrets panel — preview-only secrets, "key/value pairs, one set... injected
into the Sprite's runtime env only. Never in the LLM's context, and the agent
cannot read or use these values."

Deliberately a different repository over a different table from
repositories/project_secrets.py (0006): that one is the agent-USABLE store — its
names are listed in the agent's system prompt and its values are exported into
execute_bash (§14.3). Reusing it would put these values one `resolve_all_for_project`
call away from the agent's shell. Nothing in the agent-facing code (shell_tools,
system_prompt, agent_loop's secret-name fetch) imports this module for anything
except *masking*, which only ever removes values from what the agent sees.

Same vault-backed pattern as every other credential (§13): raw values live in
Vault, this table holds only the ref, and the HTTP surface only ever returns
name + last four characters.
"""
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user
from app.services import vault

TABLE = "preview_secrets"

MAX_SECRETS_PER_PROJECT = 50
MAX_VALUE_BYTES = 8 * 1024


class PreviewSecretLimitError(ValueError):
    pass


async def list_for_project(user_id: str, project_id: str) -> list[dict] | None:
    """None (not []) = the project isn't this user's. Rows only — never values."""
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("project_id", project_id).order("name").execute().data

    return await run_in_threadpool(_call)


async def list_names(project_id: str) -> list[str]:
    """Internal: names only, no Vault read. Used by the `.env.example` check to
    work out what's still missing without ever touching a value."""
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("name").eq("project_id", project_id).execute().data

    return sorted(r["name"] for r in await run_in_threadpool(_call))


async def upsert(user_id: str, project_id: str, name: str, value: str) -> tuple[dict, bool] | None:
    """Create-or-replace by name ("one set": a name has exactly one value).
    Returns (row, created) or None if the project isn't this user's. Replacing
    rotates the Vault secret in place."""
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
        raise PreviewSecretLimitError(f"A value can be at most {MAX_VALUE_BYTES // 1024} KB.")
    client = get_service_client()

    def _existing():
        rows = client.table(TABLE).select("*").eq("project_id", project_id).eq("name", name).limit(1).execute().data
        return rows[0] if rows else None

    def _count():
        return len(client.table(TABLE).select("id").eq("project_id", project_id).execute().data)

    existing = await run_in_threadpool(_existing)
    if existing is not None:
        await vault.update_secret(existing["secret_ref"], value)

        def _touch():
            return (
                client.table(TABLE)
                .update({"updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", existing["id"])
                .execute()
                .data[0]
            )

        return await run_in_threadpool(_touch), False

    if await run_in_threadpool(_count) >= MAX_SECRETS_PER_PROJECT:
        raise PreviewSecretLimitError(f"A project can have at most {MAX_SECRETS_PER_PROJECT} preview secrets.")

    secret_ref = await vault.create_secret(value, name=f"preview_secret:{project_id}:{name}")

    def _insert():
        return client.table(TABLE).insert({"project_id": project_id, "name": name, "secret_ref": secret_ref}).execute().data[0]

    try:
        return await run_in_threadpool(_insert), True
    except Exception:
        # Don't leave an orphaned Vault secret behind if the row insert lost a race.
        await vault.delete_secret(secret_ref)
        raise


async def delete_owned(user_id: str, project_id: str, secret_id: str) -> bool:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return False
    client = get_service_client()

    def _fetch():
        rows = client.table(TABLE).select("*").eq("id", secret_id).eq("project_id", project_id).limit(1).execute().data
        return rows[0] if rows else None

    row = await run_in_threadpool(_fetch)
    if row is None:
        return False
    await vault.delete_secret(row["secret_ref"])

    def _delete():
        client.table(TABLE).delete().eq("id", secret_id).execute()

    await run_in_threadpool(_delete)
    return True


async def delete_all_for_project(project_id: str) -> int:
    """Called before a project is deleted: the table's own ON DELETE CASCADE would
    remove the rows but leave every value orphaned in Vault, which is exactly the
    kind of leftover a secrets store shouldn't have."""
    client = get_service_client()

    def _fetch():
        return client.table(TABLE).select("secret_ref").eq("project_id", project_id).execute().data

    rows = await run_in_threadpool(_fetch)
    for row in rows:
        await vault.delete_secret(row["secret_ref"])

    def _delete():
        client.table(TABLE).delete().eq("project_id", project_id).execute()

    await run_in_threadpool(_delete)
    return len(rows)


async def resolve_all_for_project(project_id: str) -> dict[str, str]:
    """name -> decrypted value. Callers, exhaustively: preview_runtime (injects
    into the Sprite service's env at start), and preview_secrets_service (builds
    the redaction set). Never returned over HTTP, never put in a prompt, never
    passed to any agent tool."""
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("name,secret_ref").eq("project_id", project_id).execute().data

    rows = await run_in_threadpool(_call)
    resolved: dict[str, str] = {}
    for row in rows:
        value = await vault.read_secret(row["secret_ref"])
        if value is not None:
            resolved[row["name"]] = value
    return resolved
