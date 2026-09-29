"""§23.9 / db/migrations/0010_deploy_pipeline.sql's deploy_runs table. Same
ownership-scoping shape as repositories/checkpoints.py's own docstring
describes: a two-step "check the project is owned by this user, then query
the child table" rather than a single joined query, kept consistent with
every other repository in this codebase for the same §5 defense-in-depth
reasoning (RLS is bypassed by the service-role client this file uses; this
explicit check is the real boundary)."""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client
from app.repositories.projects import get_for_user as get_project_for_user

TABLE = "deploy_runs"


async def create(project_id: str, fields: dict) -> dict:
    client = get_service_client()

    def _call():
        return client.table(TABLE).insert({"project_id": project_id, **fields}).execute().data[0]

    return await run_in_threadpool(_call)


async def update(run_id: str, fields: dict) -> dict:
    client = get_service_client()

    def _call():
        return client.table(TABLE).update(fields).eq("id", run_id).execute().data[0]

    return await run_in_threadpool(_call)


async def get_owned(user_id: str, run_id: str) -> dict | None:
    client = get_service_client()

    def _fetch():
        rows = client.table(TABLE).select("*").eq("id", run_id).limit(1).execute().data
        return rows[0] if rows else None

    row = await run_in_threadpool(_fetch)
    if row is None:
        return None
    project = await get_project_for_user(user_id, row["project_id"])
    if project is None:
        return None
    return row


async def list_for_project(user_id: str, project_id: str, limit: int = 20) -> list[dict] | None:
    """None (distinct from an empty list) means the project itself isn't
    owned by this user, or doesn't exist — same convention as
    checkpoints_repo.list_for_project. Callers turn None into a 404, []
    into a real, empty deploy history."""
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
            .limit(limit)
            .execute()
            .data
        )

    return await run_in_threadpool(_call)


async def get_latest_for_project(project_id: str) -> dict | None:
    """Unscoped by user — internal, service-to-service lookup only
    (agent_loop.py's per-turn DEPLOY_DIAGNOSIS context fetch, and
    deploy_pipeline.py's own concurrency check), same pattern as
    projects_repo.get_by_id. Never call this from a router in place of
    list_for_project/get_owned."""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    return await run_in_threadpool(_call)


async def has_running(project_id: str) -> bool:
    """§23.3's own "strictly user-triggered" pattern for Push/Pull carries a
    concurrency question neither of those has (a Push/Pull is a single fast
    git operation; a deploy is a multi-minute build+start) — this is what
    lets routers/deploy.py return the same 409-shaped "already in progress"
    response send_message already gives for a session with a turn running."""
    client = get_service_client()

    def _call():
        rows = (
            client.table(TABLE)
            .select("id")
            .eq("project_id", project_id)
            .eq("status", "running")
            .limit(1)
            .execute()
            .data
        )
        return bool(rows)

    return await run_in_threadpool(_call)
