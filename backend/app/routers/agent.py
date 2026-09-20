"""
§16's agent-facing HTTP surface — the thing Phase 1's routers/sessions.py
docstring named as deferred ("there is no /sessions/{id}/stream, /messages,
or /interrupt yet... that's Phase 3"). Session CRUD itself stays in
routers/sessions.py; this is everything that drives or observes a running
turn loop, delegating all of the actual orchestration to
app/services/agent_loop.py.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    ApprovalDecision,
    ApprovalOut,
    InterruptCreate,
    MessageCreate,
    SessionEventOut,
    TurnStartResult,
)
from app.repositories import approval_requests as approval_requests_repo
from app.repositories import session_events as session_events_repo
from app.repositories import sessions as sessions_repo
from app.services import agent_loop

router = APIRouter(tags=["agent"])

SSE_HEARTBEAT_SECONDS = 15


def _event_out(row: dict) -> SessionEventOut:
    return SessionEventOut(
        id=row["id"],
        session_id=row["session_id"],
        parent_event_id=row.get("parent_event_id"),
        role=row["role"],
        event_type=row["event_type"],
        content=row["content"],
        created_at=row["created_at"],
    )


def _approval_out(row: dict) -> ApprovalOut:
    return ApprovalOut(
        id=row["id"],
        session_id=row["session_id"],
        action_type=row["action_type"],
        payload=row["payload"],
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
    )


@router.post("/sessions/{session_id}/messages", response_model=TurnStartResult, status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: MessageCreate, user: AuthedUser = Depends(verified_user)):
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Message text cannot be empty.")
    started = await agent_loop.start_turn(session_id, user.user_id, body.text)
    if not started:
        session = await sessions_repo.get_owned(user.user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session["read_only"]:
            raise HTTPException(status_code=409, detail=f"This session is read-only ({session.get('read_only_reason')}).")
        raise HTTPException(status_code=409, detail="This session already has a turn in progress.")
    return TurnStartResult(session_id=session_id, status="running")


@router.post("/sessions/{session_id}/interrupt", response_model=TurnStartResult, status_code=status.HTTP_202_ACCEPTED)
async def interrupt_session(session_id: str, body: InterruptCreate, user: AuthedUser = Depends(verified_user)):
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Interrupt text cannot be empty.")
    ok = await agent_loop.send_interrupt(session_id, user.user_id, body.text)
    if not ok:
        session = await sessions_repo.get_owned(user.user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        raise HTTPException(status_code=409, detail=f"This session is read-only ({session.get('read_only_reason')}).")
    return TurnStartResult(session_id=session_id, status="running" if agent_loop.is_running(session_id) else "queued")


@router.get("/sessions/{session_id}/events", response_model=list[SessionEventOut])
async def list_events(session_id: str, after_id: int | None = None, user: AuthedUser = Depends(verified_user)):
    rows = await session_events_repo.list_for_session_owned(user.user_id, session_id, after_id=after_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return [_event_out(r) for r in rows]


@router.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request, after_id: int | None = None, user: AuthedUser = Depends(verified_user)):
    """Server-Sent Events. Sends every event since `after_id` (or the whole
    transcript if omitted) as a catch-up burst, then stays open streaming new
    events as agent_loop.py produces them, with a heartbeat comment every
    SSE_HEARTBEAT_SECONDS to keep the connection alive through proxies that
    time out an idle one. Ends the stream on a `__session_status__` payload
    whose status is terminal (completed/failed/stuck/waiting_approval) — the
    client reconnects with `after_id` set to resume watching a later turn,
    the same reconnection path a mid-stream network drop uses.

    Single-process only: this fans out from the same in-memory registry
    agent_loop.py's `_subscribers` uses, which doesn't survive a restart or
    span multiple backend instances — see /docs/PHASE3_NOTES.md."""
    # Subscribe BEFORE fetching history, not after — subscribing after the
    # fetch would leave a real gap where an event appended between the fetch
    # and the subscribe call lands in neither the catch-up burst nor the live
    # queue, and simply never reaches this client. Subscribing first means
    # anything appended during that window safely lands in the queue instead;
    # `last_history_id` below is how the live loop then avoids re-sending it
    # a second time. Unsubscribed explicitly on the not-found path since nothing
    # else would ever clean up an orphaned subscription otherwise.
    queue = agent_loop.subscribe(session_id)
    history = await session_events_repo.list_for_session_owned(user.user_id, session_id, after_id=after_id)
    if history is None:
        agent_loop.unsubscribe(session_id, queue)
        raise HTTPException(status_code=404, detail="Session not found.")

    last_history_id = history[-1]["id"] if history else (after_id or 0)

    async def event_stream():
        try:
            for row in history:
                yield _sse_format("event", _event_out(row).model_dump(mode="json"))
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if payload.get("event_type") == "__session_status__":
                    yield _sse_format("status", {"status": payload["status"]})
                    if payload["status"] in ("completed", "failed", "stuck", "waiting_approval"):
                        break
                else:
                    if payload["id"] <= last_history_id:
                        continue  # already sent as part of the catch-up burst above — avoid a duplicate
                    yield _sse_format("event", _event_out(payload).model_dump(mode="json"))
        finally:
            agent_loop.unsubscribe(session_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse_format(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


@router.get("/sessions/{session_id}/approvals/pending", response_model=ApprovalOut | None)
async def get_pending_approval(session_id: str, user: AuthedUser = Depends(verified_user)):
    session = await sessions_repo.get_owned(user.user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    row = await approval_requests_repo.get_pending_for_session(session_id)
    return _approval_out(row) if row else None


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(approval_id: str, body: ApprovalDecision, user: AuthedUser = Depends(verified_user)):
    existing = await approval_requests_repo.get_owned(user.user_id, approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    was_pending = existing["status"] == "pending"
    row = await approval_requests_repo.resolve_owned(user.user_id, approval_id, body.approved)
    if was_pending:
        await agent_loop.resume_after_approval(row["session_id"], user.user_id)
    return _approval_out(row)
