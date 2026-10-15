"""
§14.3: "if the command text references a registered project_secrets name (e.g.
$STRIPE_TEST_KEY), it's exported as an environment variable immediately before
running and masked back to <secret-hidden> in returned output — distinct from,
and never a substitute for, the credentials in §13, which are never exposed to
execute_bash at all." Same vault-backed pattern as llm_credentials
(app/routers/llm_credentials.py) — raw values never stored in this table, only
Vault refs; the frontend only ever sees name + last-four (vault.mask_last_four).
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user
from app.services import vault

TABLE = "project_secrets"


async def list_for_project(user_id: str, project_id: str) -> list[dict] | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("*").eq("project_id", project_id).order("name").execute().data

    return await run_in_threadpool(_call)


async def create(user_id: str, project_id: str, name: str, value: str) -> dict | None:
    project = await get_project_for_user(user_id, project_id)
    if project is None:
        return None
    secret_ref = await vault.create_secret(value, name=f"project_secret:{project_id}:{name}")
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .insert({"project_id": project_id, "name": name, "secret_ref": secret_ref})
            .execute()
            .data[0]
        )

    return await run_in_threadpool(_call)


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


async def resolve_all_for_project(project_id: str) -> dict[str, str]:
    """name -> decrypted value, for shell_tools.py's env-injection and
    heuristic-guard literal-value check. Never returned over HTTP — see
    app/routers/workspace.py, which only ever calls list_for_project (masked)
    for anything client-facing."""
    client = get_service_client()

    def _call():
        return client.table(TABLE).select("name,secret_ref").eq("project_id", project_id).execute().data

    rows = await run_in_threadpool(_call)
    resolved = {}
    for row in rows:
        value = await vault.read_secret(row["secret_ref"])
        if value is not None:
            resolved[row["name"]] = value
    return resolved
