from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    ProjectConnectorsAccessUpdate,
    ProjectCreate,
    ProjectDeleteRequest,
    ProjectKnowledgeCreate,
    ProjectKnowledgeOut,
    ProjectKnowledgeUpdate,
    ProjectMemoryOut,
    ProjectMemoryUpdate,
    ProjectOut,
    ProjectUpdate,
)
from app.repositories import (
    audit,
    github_credentials as github_repo,
    llm_credentials as llm_repo,
    mcp_servers as connectors_repo,
    project_knowledge as project_knowledge_repo,
    project_memory as project_memory_repo,
    projects as repo,
)
from app.services import github_oauth, vault, workspace_service

router = APIRouter(prefix="/projects", tags=["projects"])


async def _to_out(row: dict) -> ProjectOut:
    workspace = await repo.get_workspace(row["id"])
    return ProjectOut(
        id=row["id"],
        name=row["name"],
        github_repo=row.get("github_repo"),
        github_default_branch=row.get("github_default_branch"),
        github_credential_id=row.get("github_credential_id"),
        llm_credential_id=row.get("llm_credential_id"),
        test_command=row.get("test_command"),
        max_turn_iterations=row["max_turn_iterations"],
        workspace_billing_state=workspace["billing_state"] if workspace else None,
        harness_branch_ready=row.get("harness_branch_ready", False),
        created_at=row["created_at"],
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: AuthedUser = Depends(verified_user)):
    rows = await repo.list_for_user(user.user_id)
    return [await _to_out(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, user: AuthedUser = Depends(verified_user)):
    row = await repo.get_for_user(user.user_id, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return await _to_out(row)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: AuthedUser = Depends(verified_user)):
    """§12's deterministic, sequential setup flow — no LLM involvement. The three
    setup modes:

    - 'scratch' (default, highlighted path): no repository, no GitHub credential
      required at all. Nothing is created on GitHub.
    - 'import': links an existing repository by name. The actual one-time clone
      into the persistent workspace is Workspace Service work (Phase 2) — this
      records the link so it's ready for that step.
    - 'create_new_repo': calls the GitHub API to create a brand-new repository
      right now, using the selected github_credential_id. This *is* in scope for
      Phase 1 — it's a plain REST call, no workspace/clone involved.
    """
    if body.mode == "import" and not (body.github_repo and body.github_credential_id):
        raise HTTPException(
            status_code=400,
            detail="github_repo and github_credential_id are both required when mode is 'import'.",
        )
    if body.mode == "create_new_repo" and not (body.github_credential_id and body.new_repo_name):
        raise HTTPException(
            status_code=400,
            detail="github_credential_id and new_repo_name are required when mode is 'create_new_repo'.",
        )

    if body.github_credential_id is not None:
        cred = await github_repo.get_for_user(user.user_id, body.github_credential_id)
        if cred is None:
            raise HTTPException(status_code=400, detail="github_credential_id not found on your account.")
    if body.llm_credential_id is not None:
        llm_cred = await llm_repo.get_for_user(user.user_id, body.llm_credential_id)
        if llm_cred is None:
            raise HTTPException(status_code=400, detail="llm_credential_id not found on your account.")
    for connector_id in body.connector_ids:
        connector = await connectors_repo.get_for_user(user.user_id, connector_id)
        if connector is None:
            raise HTTPException(status_code=400, detail=f"Connector {connector_id} not found on your account.")

    github_repo_full_name = None
    github_default_branch = None

    if body.mode == "import":
        github_repo_full_name = body.github_repo
        github_default_branch = "main"  # confirmed/corrected once the Workspace Service (Phase 2) clones it
    elif body.mode == "create_new_repo":
        token = await vault.read_secret(cred["token_ref"]) if cred.get("token_ref") else None
        if not token:
            raise HTTPException(status_code=400, detail="Selected GitHub credential has no usable token.")
        try:
            created = await github_oauth.create_repository(token, body.new_repo_name, body.new_repo_private)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"GitHub repo creation failed: {exc}")
        github_repo_full_name = created["full_name"]
        github_default_branch = created["default_branch"]

    row = await repo.create(
        user.user_id,
        {
            "name": body.name,
            "github_repo": github_repo_full_name,
            "github_default_branch": github_default_branch,
            "github_credential_id": body.github_credential_id,
            "llm_credential_id": body.llm_credential_id,
        },
    )

    # Phase 1 created only a placeholder row here; Phase 2's workspace_service.py
    # does the real Fly provisioning, lazily, the first time anything actually
    # needs the workspace (§14.6 — not something project creation itself blocks
    # on, so signup-to-first-project stays fast). See /docs/PHASE2_NOTES.md.
    await repo.create_workspace_stub(row["id"], sprite_handle=workspace_service.new_workspace_stub_handle())

    await repo.grant_connector_access(row["id"], body.connector_ids)

    await audit.record(
        user.user_id, "project", "create", True, project_id=row["id"], output_summary=f"mode={body.mode}"
    )
    return await _to_out(row)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate, user: AuthedUser = Depends(verified_user)):
    existing = await repo.get_for_user(user.user_id, project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.github_credential_id is not None:
        cred = await github_repo.get_for_user(user.user_id, body.github_credential_id)
        if cred is None:
            raise HTTPException(status_code=400, detail="github_credential_id not found on your account.")
        fields["github_credential_id"] = body.github_credential_id
    if body.llm_credential_id is not None:
        llm_cred = await llm_repo.get_for_user(user.user_id, body.llm_credential_id)
        if llm_cred is None:
            raise HTTPException(status_code=400, detail="llm_credential_id not found on your account.")
        fields["llm_credential_id"] = body.llm_credential_id
    if body.test_command is not None:
        fields["test_command"] = body.test_command
    if body.max_turn_iterations is not None:
        fields["max_turn_iterations"] = body.max_turn_iterations

    row = await repo.update_for_user(user.user_id, project_id, fields) if fields else existing
    await audit.record(user.user_id, "project", "update", True, project_id=project_id)
    return await _to_out(row)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, body: ProjectDeleteRequest, user: AuthedUser = Depends(verified_user)):
    """§24: 'Requires typing the project's name to confirm.' §24 also: does not
    touch the real GitHub repository or the Fly.io Sprite's own billing resource —
    Quan Harness only ever held a reference to them, never a copy."""
    existing = await repo.get_for_user(user.user_id, project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if body.confirmation != existing["name"]:
        raise HTTPException(status_code=400, detail="Confirmation text must exactly match the project name.")
    await repo.delete_for_user(user.user_id, project_id)
    await audit.record(user.user_id, "project", "delete", True, project_id=project_id, output_summary=existing["name"])


@router.get("/{project_id}/connectors-access", response_model=list[str])
async def get_connectors_access(project_id: str, user: AuthedUser = Depends(verified_user)):
    existing = await repo.get_for_user(user.user_id, project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return await repo.get_connector_access(project_id)


@router.put("/{project_id}/connectors-access", response_model=list[str])
async def put_connectors_access(
    project_id: str, body: ProjectConnectorsAccessUpdate, user: AuthedUser = Depends(verified_user)
):
    """§9.3: a plain many-to-many toggle from the project's Settings. Takes effect
    on the project's next session (there's no running session to affect in Phase 1
    anyway, since the turn loop doesn't exist yet)."""
    existing = await repo.get_for_user(user.user_id, project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    for connector_id in body.connector_ids:
        connector = await connectors_repo.get_for_user(user.user_id, connector_id)
        if connector is None:
            raise HTTPException(status_code=400, detail=f"Connector {connector_id} not found on your account.")
    await repo.set_connector_access(project_id, body.connector_ids)
    await audit.record(
        user.user_id,
        "project",
        "set_connectors_access",
        True,
        project_id=project_id,
        output_summary=f"count={len(body.connector_ids)}",
    )
    return body.connector_ids


# ---------------------------------------------------------------------------
# Memory (§20, Phase 4.1) — "a person can view, edit, or clear both memory
# stores directly at any time (project Settings; Connections)". This is the
# project-scoped store; app/routers/account.py has the account-level one.
# project_memory_log (the raw append-only material behind memory_md) is
# deliberately not exposed here at all — §20 is explicit that it's never
# injected into any prompt and exists only so memory_md can be rebuilt after
# a bad extraction, not as something a person views or edits directly.
# ---------------------------------------------------------------------------


@router.get("/{project_id}/memory", response_model=ProjectMemoryOut)
async def get_project_memory(project_id: str, user: AuthedUser = Depends(verified_user)):
    memory_md = await project_memory_repo.get_owned(user.user_id, project_id)
    if memory_md is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return ProjectMemoryOut(project_id=project_id, memory_md=memory_md)


@router.put("/{project_id}/memory", response_model=ProjectMemoryOut)
async def put_project_memory(project_id: str, body: ProjectMemoryUpdate, user: AuthedUser = Depends(verified_user)):
    """A direct, deterministic edit — never something that goes through the
    agent (§20: the agent has no memory-writing tool at all)."""
    ok = await project_memory_repo.update_owned(user.user_id, project_id, body.memory_md)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found.")
    await audit.record(
        user.user_id, "memory", "update_project_memory", True, project_id=project_id, initiated_by="user"
    )
    return ProjectMemoryOut(project_id=project_id, memory_md=body.memory_md)


@router.delete("/{project_id}/memory", response_model=ProjectMemoryOut)
async def clear_project_memory(project_id: str, user: AuthedUser = Depends(verified_user)):
    """Resets memory_md to "" (the curated index only — see
    project_memory_repo.clear_owned's own docstring for why
    project_memory_log is deliberately untouched by this). Returns the
    now-empty state rather than 204: this is a reset, not a removal of the
    project_memory row itself, so there's real content worth showing back —
    a deliberate, small deviation from this router's own delete_secret/
    delete_project convention of a bare 204."""
    ok = await project_memory_repo.clear_owned(user.user_id, project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found.")
    await audit.record(
        user.user_id, "memory", "clear_project_memory", True, project_id=project_id, initiated_by="user"
    )
    return ProjectMemoryOut(project_id=project_id, memory_md="")


# ---------------------------------------------------------------------------
# Project Knowledge (§21, Phase 4.2) — CRUD from the project's own Settings.
# Every note here is human-authored and never written by the agent (no tool
# exists for it, symmetric with memory above); agent_loop.py only ever reads
# these to check trigger conditions each turn-loop iteration.
# ---------------------------------------------------------------------------


@router.get("/{project_id}/knowledge", response_model=list[ProjectKnowledgeOut])
async def list_project_knowledge(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await project_knowledge_repo.list_owned(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return [ProjectKnowledgeOut(**row) for row in rows]


@router.post("/{project_id}/knowledge", response_model=ProjectKnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_project_knowledge(
    project_id: str, body: ProjectKnowledgeCreate, user: AuthedUser = Depends(verified_user)
):
    if not body.name.strip() or not body.trigger_value.strip():
        raise HTTPException(status_code=400, detail="name and trigger_value must both be non-empty.")
    row = await project_knowledge_repo.create_owned(
        user.user_id, project_id, body.name, body.body, body.trigger_type, body.trigger_value
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    await audit.record(
        user.user_id,
        "memory",
        "create_project_knowledge",
        True,
        project_id=project_id,
        output_summary=body.name,
        initiated_by="user",
    )
    return ProjectKnowledgeOut(**row)


@router.patch("/{project_id}/knowledge/{note_id}", response_model=ProjectKnowledgeOut)
async def update_project_knowledge(
    project_id: str, note_id: str, body: ProjectKnowledgeUpdate, user: AuthedUser = Depends(verified_user)
):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    row = await project_knowledge_repo.update_owned(user.user_id, project_id, note_id, fields)
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    await audit.record(
        user.user_id,
        "memory",
        "update_project_knowledge",
        True,
        project_id=project_id,
        output_summary=note_id,
        initiated_by="user",
    )
    return ProjectKnowledgeOut(**row)


@router.delete("/{project_id}/knowledge/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_knowledge(project_id: str, note_id: str, user: AuthedUser = Depends(verified_user)):
    deleted = await project_knowledge_repo.delete_owned(user.user_id, project_id, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found.")
    await audit.record(
        user.user_id,
        "memory",
        "delete_project_knowledge",
        True,
        project_id=project_id,
        output_summary=note_id,
        initiated_by="user",
    )
