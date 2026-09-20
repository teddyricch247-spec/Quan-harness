"""
Phase 1 scope only. A session created here just sits at status='idle' — there is no
/sessions/{id}/stream, /messages, or /interrupt yet, because those require the
agent core and Workspace Service that don't exist until Phase 2/3. Trying to build
even a stub of those now would mean guessing at an SSE/turn-loop contract this
document explicitly defers — see /docs/PHASE1_NOTES.md.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import SessionCreate, SessionOut
from app.repositories import audit, sessions as repo

router = APIRouter(tags=["sessions"])


def _to_out(row: dict) -> SessionOut:
    return SessionOut(
        id=row["id"],
        project_id=row["project_id"],
        title=row.get("title"),
        status=row["status"],
        branch_name=row.get("branch_name"),
        base_branch=row.get("base_branch"),
        pr_url=row.get("pr_url"),
        plan=row.get("plan") or [],
        turn_iteration_count=row["turn_iteration_count"],
        read_only=row.get("read_only", False),
        read_only_reason=row.get("read_only_reason"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/projects/{project_id}/sessions", response_model=list[SessionOut])
async def list_sessions(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await repo.list_for_project(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return [_to_out(r) for r in rows]


@router.post("/projects/{project_id}/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(project_id: str, body: SessionCreate, user: AuthedUser = Depends(verified_user)):
    row = await repo.create_for_project(user.user_id, project_id, body.title)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    await audit.record(user.user_id, "session", "create", True, project_id=project_id, session_id=row["id"])
    return _to_out(row)


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, user: AuthedUser = Depends(verified_user)):
    row = await repo.get_owned(user.user_id, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _to_out(row)


@router.post("/sessions/{session_id}/archive", response_model=SessionOut)
async def archive_session(session_id: str, user: AuthedUser = Depends(verified_user)):
    row = await repo.update_status(user.user_id, session_id, "archived")
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await audit.record(user.user_id, "session", "archive", True, session_id=session_id)
    return _to_out(row)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user: AuthedUser = Depends(verified_user)):
    deleted = await repo.delete_owned(user.user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found.")
    await audit.record(user.user_id, "session", "delete", True, session_id=session_id)
