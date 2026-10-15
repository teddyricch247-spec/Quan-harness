import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import verified_user, verified_user_coded
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
    ProjectScheduleCreate,
    ProjectScheduleOut,
    ProjectScheduleUpdate,
    ProjectStartOut,
    ProjectUpdate,
    TurnStartResult,
)
from app.repositories import (
    audit,
    github_credentials as github_repo,
    llm_credentials as llm_repo,
    mcp_servers as connectors_repo,
    project_knowledge as project_knowledge_repo,
    project_memory as project_memory_repo,
    preview_secrets as preview_secrets_repo,
    project_schedules as project_schedules_repo,
    projects as repo,
    sessions as sessions_repo,
)
from app.services import (
    agent_loop,
    attention_rules,
    git_sync,
    github_oauth,
    preview_runtime,
    project_naming,
    scheduler,
    scheduler_rules,
    vault,
    workspace_service,
    workspace_setup,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def _coded(status_code: int, code: str, message: str) -> HTTPException:
    """Phase Convert (C8.1): a stable machine-readable `code` next to the human `message`, so the UI
    never string-matches. Used on POST /projects only; the client accepts this shape and the old
    plain-string `detail` alike."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _to_out(
    row: dict, import_pull_error: str | None = None, summary: dict | None = None
) -> ProjectOut:
    """`summary` — attention_rules.summarize_project_sessions for this project; only GET /projects
    supplies it (Code home and the drawer need `status`/`last_activity_at`; nothing else does)."""
    workspace = await repo.get_workspace(row["id"])
    workspace_status, workspace_error = workspace_setup.status_for(workspace, row["id"])
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
        import_pull_error=import_pull_error,
        repo_origin=row.get("repo_origin", "scratch"),
        deploy_targets=row.get("deploy_targets") or [],
        deploy_targets_confirmed=row.get("deploy_targets_confirmed", False),
        workspace_status=workspace_status,
        workspace_error=workspace_error,
        last_activity_at=summary["last_activity_at"] if summary else None,
        status=summary["status"] if summary else None,
        repo_full_name=row.get("github_repo"),
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: AuthedUser = Depends(verified_user)):
    """Phase Convert (C8.2): most recently active first, each carrying `last_activity_at`, `status`
    and `repo_full_name` for Code home and the drawer. The per-project activity comes from ONE
    sessions query for the whole list (repo.summaries_for_projects), not one per project."""
    rows = await repo.list_for_user(user.user_id)
    grouped = await sessions_repo.summaries_for_projects([r["id"] for r in rows])
    out = [
        await _to_out(r, summary=attention_rules.summarize_project_sessions(grouped.get(r["id"], [])))
        for r in rows
    ]
    out.sort(key=lambda p: _as_utc(p.last_activity_at or p.created_at), reverse=True)
    return out


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, user: AuthedUser = Depends(verified_user)):
    row = await repo.get_for_user(user.user_id, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return await _to_out(row)


async def _llm_credential_resolvable(user_id: str, llm_credential_id: str | None) -> bool:
    """Cheap pre-flight for "will the first turn be able to call a model?" — an explicitly chosen
    credential that exists, or any default one. It does not read the key out of the vault (that is
    llm_client.resolve_credential's job when the turn actually runs); this only has to catch the
    common first-run case of "no key connected at all" before anything is created."""
    if llm_credential_id is not None:
        return True  # existence was verified by the caller
    return await llm_repo.get_default_for_user(user_id) is not None


async def _roll_back_project(user_id: str, project_id: str) -> None:
    """The compensating delete (C8.1). The data layer is the Supabase REST client, so there is no
    multi-table transaction to roll back; if an early setup step fails the project row is deleted
    (every dependent row cascades) so no half-built project is left behind. Best-effort by nature —
    a failure here is logged, never raised over the original error."""
    try:
        await repo.delete_for_user(user_id, project_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not roll back half-created project %s", project_id)
    workspace_setup.forget(project_id)


@router.post("", response_model=ProjectOut | ProjectStartOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: AuthedUser = Depends(verified_user_coded)):
    """§12's deterministic, sequential setup flow — no LLM involvement. The three
    setup modes:

    - 'scratch' (default, highlighted path): no repository, no GitHub credential
      required at all. Nothing is created on GitHub.
    - 'import': links an existing repository by name, looks up its *real*
      default branch from the GitHub API (Phase 4.3/4.4 — previously hardcoded
      to "main", a real, common mismatch for a repo whose default branch is
      "master", "develop", or anything else GitHub didn't invent for it — see
      github_oauth.get_repository's own docstring), and immediately pulls its
      content into the freshly-provisioned workspace so the project isn't left
      silently empty until the person happens to click Pull themselves. Phase
      1/2's original comment here said the clone was deferred until "the
      Workspace Service exists" — it does now (Phase 2), so this mode actually
      does what "Import an existing repository" says on the tin.
    - 'create_new_repo': calls the GitHub API to create a brand-new repository
      right now, using the selected github_credential_id. This *is* in scope for
      Phase 1 — it's a plain REST call, no workspace/clone involved.

    Phase Convert (C8.1) adds one more shape without changing any of the above:

    - Without `prompt`, everything behaves exactly as before and the answer is a ProjectOut.
    - With `prompt`, this is the one call behind Code home's composer: it creates the project, its
      first session and the first turn, and answers 201 ProjectStartOut. `name` and both credential
      ids become optional (the name is derived from the prompt; the LLM credential falls back to the
      account default exactly as llm_client.resolve_credential already does; the GitHub credential
      falls back to the account default or fails with `github_not_connected`). If an early setup
      step fails the project is deleted again (see _roll_back_project); once the session exists the
      project is kept no matter what happens to the turn, because from then on the person can see it
      and retry.

    Stable error codes on this endpoint (as `detail: {code, message}`): `email_not_verified`,
    `llm_key_required`, `github_not_connected`.
    """
    prompt = (body.prompt or "").strip() or None

    # "Without `prompt` the endpoint behaves exactly as before": a scratch project used to *require* a
    # name (it was a required field), and still does. Import / create-new-repo can be named from their
    # repository, so they don't need one typed.
    if prompt is None and body.mode == "scratch" and not (body.name and body.name.strip()):
        raise HTTPException(status_code=422, detail="name is required when no prompt is given.")
    if body.mode == "import" and not body.github_repo:
        raise HTTPException(status_code=400, detail="github_repo is required when mode is 'import'.")
    if body.mode == "create_new_repo" and not body.new_repo_name:
        raise HTTPException(status_code=400, detail="new_repo_name is required when mode is 'create_new_repo'.")

    cred = None
    if body.github_credential_id is not None:
        cred = await github_repo.get_for_user(user.user_id, body.github_credential_id)
        if cred is None:
            raise HTTPException(status_code=400, detail="github_credential_id not found on your account.")
    elif body.mode in ("import", "create_new_repo"):
        cred = await github_repo.get_default_for_user(user.user_id)
        if cred is None:
            raise _coded(
                400,
                "github_not_connected",
                "Connect GitHub first (Settings → GitHub), or set one of your connections as the default.",
            )
    if body.llm_credential_id is not None:
        llm_cred = await llm_repo.get_for_user(user.user_id, body.llm_credential_id)
        if llm_cred is None:
            raise HTTPException(status_code=400, detail="llm_credential_id not found on your account.")
    for connector_id in body.connector_ids:
        connector = await connectors_repo.get_for_user(user.user_id, connector_id)
        if connector is None:
            raise HTTPException(status_code=400, detail=f"Connector {connector_id} not found on your account.")

    # Checked before anything is created — in particular before a GitHub repository is, because a
    # new repository is the one side effect this endpoint cannot take back.
    if prompt is not None and not await _llm_credential_resolvable(user.user_id, body.llm_credential_id):
        raise _coded(
            400,
            "llm_key_required",
            "Connect a model key first (Settings → LLM Providers), then send your message again.",
        )

    github_repo_full_name = None
    github_default_branch = None
    github_token = None
    if cred is not None and cred.get("token_ref"):
        github_token = await vault.read_secret(cred["token_ref"])

    if body.mode == "import":
        if not github_token:
            raise HTTPException(status_code=400, detail="Selected GitHub credential has no usable token.")
        try:
            info = await github_oauth.get_repository(github_token, body.github_repo)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not look up repository {body.github_repo}: {exc}")
        github_repo_full_name = info["full_name"]
        github_default_branch = info["default_branch"]
    elif body.mode == "create_new_repo":
        if not github_token:
            raise HTTPException(status_code=400, detail="Selected GitHub credential has no usable token.")
        try:
            created = await github_oauth.create_repository(github_token, body.new_repo_name, body.new_repo_private)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"GitHub repo creation failed: {exc}")
        github_repo_full_name = created["full_name"]
        github_default_branch = created["default_branch"]

    if body.name and body.name.strip():
        name = body.name.strip()
    else:
        repo_hint = github_repo_full_name.split("/")[-1] if github_repo_full_name else None
        name = project_naming.derive_project_name(prompt, fallback=repo_hint)

    row = await repo.create(
        user.user_id,
        {
            "name": name,
            "github_repo": github_repo_full_name,
            "github_default_branch": github_default_branch,
            # The resolved credential (explicit, or the account default for import/create) — pull
            # and push read the project's own github_credential_id, so a defaulted one has to be
            # stored here, not just used for the lookups above.
            "github_credential_id": cred["id"] if cred is not None else None,
            "llm_credential_id": body.llm_credential_id,
            # Phase 5.1/5.2/5.5 (§23.6): the one distinction the deploy
            # pipeline's monorepo-detection gate cares about — 'import' is a
            # codebase the harness didn't build and doesn't already know the
            # shape of; 'scratch' and 'create_new_repo' both start from a
            # structure Quan Harness itself is the author of (or that
            # doesn't exist yet), so they collapse to the same 'scratch'
            # value here. See db/migrations/0010_deploy_pipeline.sql and
            # app/services/deploy_pipeline.py.
            "repo_origin": "imported" if body.mode == "import" else "scratch",
        },
    )
    project_id = row["id"]

    # Everything between here and the first turn is "early setup". With a prompt (the one-call
    # shape) a failure rolls the project back; without one (the legacy shape, "exactly as today")
    # it propagates untouched, as it always did.
    session_row: dict | None = None
    try:
        # Phase 1 created only a placeholder row here; Phase 2's workspace_service.py
        # does the real Fly/Sprites provisioning, lazily, the first time anything
        # actually needs the workspace (§14.6 — not something project creation
        # itself normally blocks on, so signup-to-first-project stays fast for the
        # 'scratch' and 'create_new_repo' modes). See /docs/PHASE2_NOTES.md.
        await repo.create_workspace_stub(project_id, sprite_handle=workspace_service.new_workspace_stub_handle())

        # Phase 5.3 (§23.8): the project's stable preview subdomain, assigned once here
        # and never changed (a DB trigger enforces that — 0011_preview.sql), so a client
        # can allowlist its CORS origin a single time. Done as its own step with its own
        # collision retry rather than inside the insert above, so a (vanishingly rare)
        # collision can never fail project creation; preview_runtime assigns it lazily
        # later if this ever doesn't land.
        try:
            await preview_runtime.ensure_preview_subdomain(row)
        except Exception:  # noqa: BLE001 — non-fatal by design
            pass

        await repo.grant_connector_access(project_id, body.connector_ids)

        if prompt is not None:
            session_row = await sessions_repo.create_for_project(user.user_id, project_id, None)
            if session_row is None:
                raise RuntimeError("the first session could not be created")
    except Exception as exc:  # noqa: BLE001
        if prompt is None:
            raise
        logger.exception("project setup failed for %s; rolling the project back", project_id)
        await _roll_back_project(user.user_id, project_id)
        extra = ""
        if body.mode == "create_new_repo" and github_repo_full_name:
            extra = f" The GitHub repository {github_repo_full_name} was already created and was not deleted."
        raise HTTPException(
            status_code=500,
            detail=f"Could not set up the project, so nothing was kept. Try sending your message again.{extra}",
        ) from exc

    # Phase 4.4: 'import' mode is the one case where the workspace needs real
    # content in it immediately, not lazily on first agent tool call — an
    # agent working in a blank git-init'd workspace with no relation to the
    # actual imported repository would be a silent, confusing bug, not a
    # deferred nicety. git_sync.pull() is the exact mechanism Phase 2 already
    # built for "make the workspace match GitHub" — reused as-is rather than
    # duplicated. confirm_discard=True is safe here specifically because the
    # workspace is provably brand new (create_workspace_stub/ensure_workspace
    # just ran a bare `git init`, zero commits) — there is nothing local to
    # discard.
    #
    # A failure here (most likely: Sprites/Fly credentials aren't configured
    # yet, per AGENTS.md's "the app works without them; only the sandboxed
    # workspace feature is unavailable until they're filled in") must NOT
    # fail project creation — the project row, its GitHub link (with the now-
    # correct default branch above), and its credential selection are all
    # real and useful on their own. The failure is surfaced on the response
    # instead, so the person knows to retry from the Workspace panel's own
    # Pull button once workspace credentials exist, rather than being left
    # with a silently-empty workspace and no explanation.
    import_pull_error: str | None = None
    if body.mode == "import":
        try:
            await git_sync.pull(user.user_id, project_id, confirm_discard=True)
        except git_sync.GitSyncError as exc:
            import_pull_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — workspace provisioning failing must not fail project creation
            import_pull_error = f"Could not provision the workspace to pull into: {exc}"
    elif prompt is not None:
        # Phase Convert (C8.5): start provisioning now instead of on the first tool call, so the
        # "Setting up your project" card reports a real status. Import already provisioned the
        # workspace above (its pull needs one). Only after every rollback-able step has passed —
        # a background task must never outlive a project that was just deleted.
        workspace_setup.kick_off(project_id)

    summary = f"mode={body.mode}"
    if import_pull_error:
        summary += " (initial pull failed — see import_pull_error)"

    if prompt is None:
        await audit.record(user.user_id, "project", "create", True, project_id=project_id, output_summary=summary)
        return await _to_out(row, import_pull_error=import_pull_error)

    # The turn. agent_loop.start_turn stores the prompt as the session's first message itself and
    # then spawns the loop, so there is nothing to insert here. An import whose pull failed does
    # not start one (C8.1): the agent would be working in an empty workspace, and the UI keeps the
    # prompt as the workspace draft instead.
    session_id = session_row["id"]  # type: ignore[index]
    if import_pull_error:
        turn_status = "not_started"
    else:
        try:
            started = await agent_loop.start_turn(session_id, user.user_id, prompt)
            turn_status = "running" if started else "failed"
        except Exception:  # noqa: BLE001 — the project exists; the UI offers Retry
            logger.exception("first turn could not be started for project %s", project_id)
            turn_status = "failed"
    summary += f" turn={turn_status}"
    await audit.record(
        user.user_id, "project", "create", True, project_id=project_id, session_id=session_id, output_summary=summary
    )
    return ProjectStartOut(
        project=await _to_out(row, import_pull_error=import_pull_error),
        session_id=session_id,
        turn=TurnStartResult(session_id=session_id, status=turn_status),
    )


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
    # Phase 5.3: preview secrets live in Vault; the table's ON DELETE CASCADE would
    # drop the rows and leave every value orphaned there. Remove them first.
    await preview_secrets_repo.delete_all_for_project(project_id)
    await repo.delete_for_user(user.user_id, project_id)
    workspace_setup.forget(project_id)
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


# ---------------------------------------------------------------------------
# Scheduling / Proactive Scanning (§26, Phase 4.5) — optional, opt-in, per
# project. CRUD lives behind the project's own Settings, the same pattern as
# Memory/Project Knowledge above. Actually *running* a schedule is
# app/services/scheduler.py's job — the background poll loop on its own
# cadence, or the "run now" endpoint at the bottom of this section, which is
# deliberately routed through that exact same module's trigger_schedule
# function rather than a second, parallel way of starting a run.
# ---------------------------------------------------------------------------


def _schedule_to_out(row: dict) -> ProjectScheduleOut:
    return ProjectScheduleOut(
        id=row["id"],
        project_id=row["project_id"],
        description=row["description"],
        frequency=row["frequency"],
        cron_expression=row.get("cron_expression"),
        enabled=row["enabled"],
        last_run_at=row.get("last_run_at"),
        last_session_id=row.get("last_session_id"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_schedule_fields(frequency: str, cron_expression: str | None) -> None:
    """0009_scheduling.sql's own check constraint enforces "cron_expression
    is required when frequency == 'custom'" at the DB level; this rejects
    the same problem earlier, with a clearer message, and additionally
    validates that a supplied cron_expression is a syntactically real 5-field
    crontab expression (scheduler_rules.validate_cron_expression) — the DB
    constraint has no way to check that, it would otherwise only surface the
    first time the scheduler loop tried to evaluate it against
    scheduler_rules.is_due and croniter raised."""
    if frequency == "custom":
        if not cron_expression:
            raise HTTPException(status_code=400, detail="cron_expression is required when frequency is 'custom'.")
        error = scheduler_rules.validate_cron_expression(cron_expression)
        if error:
            raise HTTPException(status_code=400, detail=f"Invalid cron_expression: {error}")


@router.get("/{project_id}/schedules", response_model=list[ProjectScheduleOut])
async def list_project_schedules(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await project_schedules_repo.list_owned(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return [_schedule_to_out(row) for row in rows]


@router.post("/{project_id}/schedules", response_model=ProjectScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_project_schedule(
    project_id: str, body: ProjectScheduleCreate, user: AuthedUser = Depends(verified_user)
):
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="description must be non-empty.")
    _validate_schedule_fields(body.frequency, body.cron_expression)
    row = await project_schedules_repo.create_owned(
        user.user_id, project_id, body.description, body.frequency, body.cron_expression, body.enabled
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    await audit.record(
        user.user_id,
        "schedule",
        "create",
        True,
        project_id=project_id,
        output_summary=body.description[:200],
        initiated_by="user",
    )
    return _schedule_to_out(row)


@router.patch("/{project_id}/schedules/{schedule_id}", response_model=ProjectScheduleOut)
async def update_project_schedule(
    project_id: str, schedule_id: str, body: ProjectScheduleUpdate, user: AuthedUser = Depends(verified_user)
):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "frequency" in fields or "cron_expression" in fields:
        existing = await project_schedules_repo.get_owned(user.user_id, project_id, schedule_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found.")
        frequency = fields.get("frequency", existing["frequency"])
        cron_expression = fields.get("cron_expression", existing.get("cron_expression"))
        _validate_schedule_fields(frequency, cron_expression)
    row = await project_schedules_repo.update_owned(user.user_id, project_id, schedule_id, fields)
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    await audit.record(
        user.user_id,
        "schedule",
        "update",
        True,
        project_id=project_id,
        output_summary=schedule_id,
        initiated_by="user",
    )
    return _schedule_to_out(row)


@router.delete("/{project_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_schedule(project_id: str, schedule_id: str, user: AuthedUser = Depends(verified_user)):
    deleted = await project_schedules_repo.delete_owned(user.user_id, project_id, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    await audit.record(
        user.user_id,
        "schedule",
        "delete",
        True,
        project_id=project_id,
        output_summary=schedule_id,
        initiated_by="user",
    )


@router.post("/{project_id}/schedules/{schedule_id}/run", response_model=ProjectScheduleOut)
async def run_project_schedule_now(project_id: str, schedule_id: str, user: AuthedUser = Depends(verified_user)):
    """Not part of §26's own text — a small, low-risk addition alongside it:
    triggers this schedule immediately, through the exact same
    scheduler.trigger_schedule the background poll loop itself calls (see
    that function's own docstring), rather than waiting for its next due
    tick. Useful mainly to confirm a freshly-created schedule is actually
    wired up correctly (the connector it needs really is granted, the
    project's LLM credential resolves) without waiting up to 24 hours to
    find out. Does not require the schedule to be `enabled` — running it
    once manually doesn't imply turning its recurring cadence back on, and
    `trigger_schedule` itself has no opinion on `enabled` either way (see
    project_schedules_repo.list_enabled's own docstring)."""
    existing = await project_schedules_repo.get_owned(user.user_id, project_id, schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    started = await scheduler.trigger_schedule(existing, initiated_by="user")
    if not started:
        raise HTTPException(status_code=502, detail="Could not start a session for this schedule — see server logs.")
    row = await project_schedules_repo.get_owned(user.user_id, project_id, schedule_id)
    return _schedule_to_out(row)
