"""
§27/§10.3: every direct, human-triggered platform action (connect/disconnect a
credential, rotate one, push/pull, delete a project) gets an audit_log row with
initiated_by='user', the same trail an agent's own approved actions will write to
in later phases. Phase 1 only ever writes initiated_by='user' or 'system' rows —
'agent' rows start appearing once the agent core (Phase 3) exists.
"""
from starlette.concurrency import run_in_threadpool

from app.db import get_service_client

TABLE = "audit_log"


async def record(
    user_id: str,
    tool: str,
    action: str,
    success: bool,
    project_id: str | None = None,
    session_id: str | None = None,
    input_payload: dict | None = None,
    output_summary: str | None = None,
    initiated_by: str = "user",
) -> None:
    client = get_service_client()

    def _call():
        client.table(TABLE).insert(
            {
                "user_id": user_id,
                "project_id": project_id,
                "session_id": session_id,
                "tool": tool,
                "action": action,
                "input": input_payload or {},
                "output_summary": output_summary,
                "success": success,
                "initiated_by": initiated_by,
            }
        ).execute()

    await run_in_threadpool(_call)


async def list_for_user(user_id: str, limit: int = 100) -> list[dict]:
    client = get_service_client()

    def _call():
        return (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    return await run_in_threadpool(_call)
