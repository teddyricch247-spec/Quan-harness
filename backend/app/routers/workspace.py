"""
Phase 2's only new HTTP surface. Deliberately does NOT expose view_file/
str_replace/create_file/execute_bash/run_lint/run_tests over HTTP — those are
native agent tools (§14) called internally by Phase 3's turn loop
(app/services/agent_loop.py), not by any HTTP client directly (see
app/services/file_tools.py and shell_tools.py's own docstrings), and adding
a REST endpoint for them now would just be inventing an ad-hoc debug API the
spec never asked for. Push, Pull, workspace status, checkpoints, and project
secrets are the pieces of Phase 2 that are genuinely user-facing (§23.3: "Push
and Pull ... both strictly user-triggered").
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    CheckpointOut,
    ProjectSecretCreate,
    ProjectSecretOut,
    PullRequest,
    PullResult,
    PushRequest,
    PushResult,
    WorkspaceOut,
)
from app.repositories import checkpoints as checkpoints_repo
from app.repositories import project_secrets as project_secrets_repo
from app.repositories import projects as projects_repo
from app.services import checkpoints as checkpoints_service
from app.services import git_sync, vault, workspace_service

router = APIRouter(tags=["workspace"])


@router.get("/projects/{project_id}/workspace", response_model=WorkspaceOut)
async def get_workspace(project_id: str, user: AuthedUser = Depends(verified_user)):
    project = await projects_repo.get_for_user(user.user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    ws = await projects_repo.get_workspace(project_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace record missing for this project.")
    return WorkspaceOut(
        project_id=project_id,
        billing_state=ws["billing_state"],
        provisioned=not ws["sprite_handle"].startswith("pending-"),
        last_active_at=ws.get("last_active_at"),
    )


@router.post("/projects/{project_id}/workspace/wake", response_model=WorkspaceOut)
async def wake_workspace(project_id: str, user: AuthedUser = Depends(verified_user)):
    """A manual 'resume' action for the UI — e.g. before opening a session on a
    cold workspace so file browsing feels immediate rather than waiting out the
    implicit wake on the first tool call. Not itself a tool (§14.6)."""
    project = await projects_repo.get_for_user(user.user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    ws = await workspace_service.wake(project_id)
    return WorkspaceOut(
        project_id=project_id,
        billing_state=ws["billing_state"],
        provisioned=not ws["sprite_handle"].startswith("pending-"),
        last_active_at=ws.get("last_active_at"),
    )


@router.post("/projects/{project_id}/push", response_model=PushResult)
async def push(project_id: str, body: PushRequest, user: AuthedUser = Depends(verified_user)):
    try:
        result = await git_sync.push(user.user_id, project_id, body.repo_name, body.private)
    except git_sync.GitSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PushResult(**result)


@router.post("/projects/{project_id}/pull", response_model=PullResult)
async def pull(project_id: str, body: PullRequest, user: AuthedUser = Depends(verified_user)):
    try:
        result = await git_sync.pull(user.user_id, project_id, body.confirm_discard)
    except git_sync.GitSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PullResult(**result)


@router.get("/projects/{project_id}/checkpoints", response_model=list[CheckpointOut])
async def list_checkpoints(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await checkpoints_repo.list_for_project(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    active_session_id = await checkpoints_repo.get_active_session_id(project_id)
    return [
        CheckpointOut(
            id=r["id"],
            project_id=r["project_id"],
            session_id=r["session_id"],
            git_commit_sha=r["git_commit_sha"],
            restorable=r["session_id"] == active_session_id,
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/checkpoints/{checkpoint_id}/restore", response_model=CheckpointOut)
async def restore_checkpoint(checkpoint_id: str, user: AuthedUser = Depends(verified_user)):
    try:
        checkpoint = await checkpoints_service.restore_checkpoint(user.user_id, checkpoint_id)
    except checkpoints_service.CheckpointRestoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CheckpointOut(
        id=checkpoint["id"],
        project_id=checkpoint["project_id"],
        session_id=checkpoint["session_id"],
        git_commit_sha=checkpoint["git_commit_sha"],
        restorable=True,
        created_at=checkpoint["created_at"],
    )


@router.get("/projects/{project_id}/secrets", response_model=list[ProjectSecretOut])
async def list_secrets(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await project_secrets_repo.list_for_project(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    out = []
    for row in rows:
        value = await vault.read_secret(row["secret_ref"])
        out.append(
            ProjectSecretOut(
                id=row["id"],
                name=row["name"],
                value_last_four=value[-4:] if value and len(value) >= 4 else "----",
                created_at=row["created_at"],
            )
        )
    return out


@router.post("/projects/{project_id}/secrets", response_model=ProjectSecretOut, status_code=status.HTTP_201_CREATED)
async def create_secret(project_id: str, body: ProjectSecretCreate, user: AuthedUser = Depends(verified_user)):
    if not body.name.isidentifier() or not body.name.isupper():
        raise HTTPException(
            status_code=400,
            detail="Secret names must be UPPER_SNAKE_CASE valid shell identifiers (e.g. STRIPE_TEST_KEY), "
            "since they're referenced in execute_bash commands as $NAME.",
        )
    row = await project_secrets_repo.create(user.user_id, project_id, body.name, body.value)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return ProjectSecretOut(
        id=row["id"],
        name=row["name"],
        value_last_four=body.value[-4:] if len(body.value) >= 4 else "****",
        created_at=row["created_at"],
    )


@router.delete("/projects/{project_id}/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(project_id: str, secret_id: str, user: AuthedUser = Depends(verified_user)):
    deleted = await project_secrets_repo.delete_owned(user.user_id, project_id, secret_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found.")
    return None
