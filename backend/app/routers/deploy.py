"""
§23.5/§23.6/§23.9's user-facing HTTP surface, delegating all real
orchestration to app/services/deploy_pipeline.py — same split as
routers/agent.py -> agent_loop.py.

Every endpoint here is strictly user-triggered, same as routers/workspace.py's
Push/Pull (§23.3): there is no deploy-triggering tool on the agent's own tool
list, and never will be — see deploy_pipeline.py's own module docstring for
why a deploy command is something this pipeline constructs itself from a
detected/confirmed plan, never something a model is handed a shell for.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    DeployNeedsConfirmationResult,
    DeployRunOut,
    DeployTarget,
    DeployTargetsConfirmRequest,
    DeployTriggerRequest,
    DeployTriggerResult,
)
from app.repositories import deploy_runs as deploy_runs_repo
from app.repositories import projects as projects_repo
from app.services import deploy_detection, deploy_pipeline, llm_client
from app.services.workspace_paths import resolve_repo_path

router = APIRouter(prefix="/projects", tags=["deploy"])

SSE_HEARTBEAT_SECONDS = 15


def _run_out(row: dict) -> DeployRunOut:
    return DeployRunOut(
        id=row["id"],
        project_id=row["project_id"],
        status=row["status"],
        target_name=row.get("target_name"),
        phase=row["phase"],
        stack=row.get("stack"),
        build_cmd=row.get("build_cmd"),
        run_cmd=row.get("run_cmd"),
        port=row.get("port"),
        exit_code=row.get("exit_code"),
        stdout=row.get("stdout") or "",
        stderr=row.get("stderr") or "",
        failure_class=row.get("failure_class"),
        diagnosis_text=row.get("diagnosis_text"),
        suggested_fix_prompt=row.get("suggested_fix_prompt"),
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )


async def _require_project(user: AuthedUser, project_id: str) -> dict:
    project = await projects_repo.get_for_user(user.user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.post("/{project_id}/deploy", response_model=DeployTriggerResult | DeployNeedsConfirmationResult)
async def trigger_deploy(project_id: str, body: DeployTriggerRequest = DeployTriggerRequest(), user: AuthedUser = Depends(verified_user)):
    """Same "one 200 response, a flag field distinguishes outcomes" shape as
    routers/workspace.py's pull() and its PullResult.needs_confirmation —
    §23.6's monorepo confirmation step is a normal, expected branch of this
    call for an 'imported' project's first deploy, not an error condition,
    so it's a 200 carrying DeployNeedsConfirmationResult rather than an HTTP
    error status. Only "a deploy is already running" is a real error (409) —
    see below."""
    await _require_project(user, project_id)
    try:
        started = await deploy_pipeline.start_deploy(project_id, user.user_id, force_redetect=body.force_redetect)
    except deploy_pipeline.DeployNeedsConfirmation as exc:
        return DeployNeedsConfirmationResult(proposed_targets=[DeployTarget(**t) for t in exc.proposed_targets])
    except llm_client.NoLlmCredentialError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't work out this repository's deployable roots: {exc}")
    except llm_client.LlmCallFailedError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't work out this repository's deployable roots: the model call failed ({exc}).")
    except deploy_detection.DetectionLlmError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't work out this repository's deployable roots: {exc} Enter them manually and confirm.")
    if not started:
        raise HTTPException(status_code=409, detail="A deploy is already in progress for this project.")
    return DeployTriggerResult(status="running")


@router.post("/{project_id}/deploy/targets/confirm", response_model=list[DeployTarget])
async def confirm_deploy_targets(project_id: str, body: DeployTargetsConfirmRequest, user: AuthedUser = Depends(verified_user)):
    await _require_project(user, project_id)
    for target in body.targets:
        if not isinstance(target, dict):
            raise HTTPException(status_code=422, detail="Every target must be an object with 'name' and 'root'.")
        if not isinstance(target.get("name"), str) or not target["name"].strip():
            raise HTTPException(status_code=422, detail="Every target needs a non-empty 'name'.")
        if not isinstance(target.get("root"), str) or not target["root"].strip():
            raise HTTPException(status_code=422, detail="Every target needs a non-empty 'root'.")
        try:
            resolve_repo_path(target["root"].strip())
        except ValueError as exc:
            # Reject here rather than letting a bad root blow up later inside the
            # background deploy task, where there's nobody to return an error to.
            raise HTTPException(status_code=422, detail=f"Invalid root '{target['root']}': {exc}")
    names = [t["name"].strip() for t in body.targets]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=422, detail="Target names must be unique.")
    blanked = await deploy_pipeline.confirm_targets(project_id, body.targets)
    return [DeployTarget(**t) for t in blanked]


@router.get("/{project_id}/deploy/runs", response_model=list[DeployRunOut])
async def list_deploy_runs(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await deploy_runs_repo.list_for_project(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return [_run_out(r) for r in rows]


@router.get("/{project_id}/deploy/runs/{run_id}", response_model=DeployRunOut)
async def get_deploy_run(project_id: str, run_id: str, user: AuthedUser = Depends(verified_user)):
    row = await deploy_runs_repo.get_owned(user.user_id, run_id)
    if row is None or row["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Deploy run not found.")
    return _run_out(row)


@router.get("/{project_id}/deploy/stream")
async def stream_deploy(project_id: str, request: Request, user: AuthedUser = Depends(verified_user)):
    """Server-Sent Events, same shape as routers/agent.py's stream_session
    (see that function's own docstring — this reuses its exact reasoning for
    subscribing before fetching, the heartbeat, and the terminal-status
    close condition, just against deploy_pipeline._subscribers keyed by
    project_id instead of agent_loop._subscribers keyed by session_id).
    Not yet consumed by any frontend page — same "the endpoint exists before
    the UI that will use it" situation as stream_session's own frontend gap;
    see /docs/PHASE5_1_5_2_5_5_NOTES.md."""
    await _require_project(user, project_id)
    queue = deploy_pipeline.subscribe(project_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if payload.get("type") == "__deploy_status__":
                    yield _sse_format("status", {"status": payload["status"]})
                    break
                yield _sse_format("phase", payload)
        finally:
            deploy_pipeline.unsubscribe(project_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse_format(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
