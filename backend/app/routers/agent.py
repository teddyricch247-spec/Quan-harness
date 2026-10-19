"""
§16's agent-facing HTTP surface — the thing Phase 1's routers/sessions.py
docstring named as deferred ("there is no /sessions/{id}/stream, /messages,
or /interrupt yet... that's Phase 3"). Session CRUD itself stays in
routers/sessions.py; this is everything that drives or observes a running
turn loop, delegating all of the actual orchestration to
app/services/agent_loop.py.

Phase 6.1 (step 19) adds picture attachments on user messages:
  POST /sessions/{id}/attachments           upload one picture (JSON, base64) -> its id + metadata
  GET  /sessions/{id}/attachments/{att_id}  the picture's bytes (owner only) — for thumbnails in the transcript
  POST /sessions/{id}/messages | /interrupt  accept `attachment_ids` naming pictures uploaded first
See app/services/image_input.py for the rules and the whole flow.
"""
import asyncio
import base64
import binascii
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    ApprovalDecision,
    ApprovalOut,
    AttachmentOut,
    AttachmentUpload,
    InterruptCreate,
    MessageCreate,
    SessionEventOut,
    TurnStartResult,
)
from app.repositories import approval_requests as approval_requests_repo
from app.repositories import session_attachments as session_attachments_repo
from app.repositories import session_events as session_events_repo
from app.repositories import sessions as sessions_repo
from app.services import agent_loop, image_input, live_text, turn_control

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


async def _check_attachments_usable(user_id: str, session_id: str, attachment_ids: list[str]) -> None:
    """Phase 6.1: before a message that names pictures is accepted — the session must be the caller's (404 otherwise,
    the same answer as for any other session that isn't theirs) and the project's model must be one that can read
    images (422 with the reason and the fix: the model may have been switched since the upload). A no-op for a
    message with no attachments, so nothing changes for text-only messages."""
    if not attachment_ids:
        return
    session = await sessions_repo.get_owned(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    problem = await agent_loop.image_input_problem(user_id, session)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


@router.post("/sessions/{session_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(session_id: str, body: AttachmentUpload, user: AuthedUser = Depends(verified_user)):
    session = await sessions_repo.get_owned(user.user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session["read_only"]:
        raise HTTPException(status_code=409, detail=f"This session is read-only ({session.get('read_only_reason')}).")

    encoded = body.data_base64
    if encoded.startswith("data:"):  # tolerate a pasted data URI; the contract is bare base64
        encoded = encoded.split(",", 1)[-1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="The image data isn't valid base64.")
    try:
        info = image_input.sniff_image(data, body.media_type)  # type, size and dimensions come from the BYTES
    except image_input.ImageRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)

    problem = await agent_loop.image_input_problem(user.user_id, session)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    await session_attachments_repo.purge_stale(session_id)
    if await session_attachments_repo.count_pending(session_id) >= image_input.MAX_PENDING_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many pictures are waiting to be sent in this session. Send a message first.")

    attachment_id = str(uuid.uuid4())
    filename = image_input.safe_filename(body.filename)
    await session_attachments_repo.create(
        session_id,
        attachment_id=attachment_id,
        filename=filename,
        media_type=info.media_type,
        width=info.width,
        height=info.height,
        byte_size=info.byte_size,
        data_b64=base64.b64encode(data).decode("ascii"),  # re-encoded from the validated bytes, not the client's string
    )
    return AttachmentOut(
        id=attachment_id, filename=filename, media_type=info.media_type, width=info.width, height=info.height, byte_size=info.byte_size
    )


@router.get("/sessions/{session_id}/attachments/{attachment_id}")
async def get_attachment(session_id: str, attachment_id: str, user: AuthedUser = Depends(verified_user)):
    session = await sessions_repo.get_owned(user.user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    row = await session_attachments_repo.get_data(session_id, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return Response(
        content=base64.b64decode(row["data_b64"]),
        media_type=row["media_type"],  # always one of the four image types (a CHECK in the table)
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@router.post("/sessions/{session_id}/messages", response_model=TurnStartResult, status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: MessageCreate, user: AuthedUser = Depends(verified_user)):
    if not body.text.strip() and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="Message text cannot be empty.")
    await _check_attachments_usable(user.user_id, session_id, body.attachment_ids)
    try:
        with live_text.streaming_for(session_id):  # the turn started here streams its reply to anyone watching
            started = await agent_loop.start_turn(session_id, user.user_id, body.text, body.attachment_ids or None)
    except agent_loop.AttachmentsUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    if not body.text.strip() and not body.attachment_ids:
        raise HTTPException(status_code=422, detail="Interrupt text cannot be empty.")
    await _check_attachments_usable(user.user_id, session_id, body.attachment_ids)
    try:
        with live_text.streaming_for(session_id):  # only matters if this starts a turn; a running one keeps its own binding
            ok = await agent_loop.send_interrupt(session_id, user.user_id, body.text, body.attachment_ids or None)
    except agent_loop.AttachmentsUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        session = await sessions_repo.get_owned(user.user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        raise HTTPException(status_code=409, detail=f"This session is read-only ({session.get('read_only_reason')}).")
    return TurnStartResult(session_id=session_id, status="running" if agent_loop.is_running(session_id) else "queued")


@router.post("/sessions/{session_id}/stop", response_model=TurnStartResult)
async def stop_session(session_id: str, user: AuthedUser = Depends(verified_user)):
    """The Stop button: cancel the turn running in this session (services/turn_control.py says exactly what that does and
    does not undo). 409 when nothing is running — usually the turn ended a moment before the click."""
    outcome = await turn_control.stop_turn(session_id, user.user_id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Session not found.")
    if outcome == "not_running":
        raise HTTPException(status_code=409, detail="Nothing is running in this session.")
    if outcome == "not_stopped":
        raise HTTPException(status_code=500, detail="The turn did not stop when asked. Try again in a moment.")
    return TurnStartResult(session_id=session_id, status="stopped")


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
    span multiple backend instances — see /docs/PHASE3_NOTES.md.

    Besides `event` and `status` frames it sends EPHEMERAL ones while the model is working (see services/live_text.py):
    `delta` (more text of the reply so far) and `thinking` (more of its thinking so far) — `replace: true` on the first
    one after a reconnect carries everything so far — and `reset` (discard both: the reply is being retried, or the call
    failed). They are never stored; the finished reply and the saved thinking arrive as ordinary `event`s and replace them."""
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
    # A viewer who connects (or reconnects) while the model is mid-reply is first given the text so far. Deltas already
    # inside that snapshot are recognised by their sequence number and skipped, so nothing is applied twice.
    viewer = live_text.LiveViewer(live_text.snapshot(session_id), live_text.snapshot(session_id, live_text.THINKING))

    async def event_stream():
        try:
            for row in history:
                yield _sse_format("event", _event_out(row).model_dump(mode="json"))
            for first_frame in viewer.first_frames:
                yield _sse_format(*first_frame)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                kind = payload.get("event_type")
                if kind == "__session_status__":
                    yield _sse_format("status", {"status": payload["status"]})
                    if payload["status"] in ("completed", "failed", "stuck", "waiting_approval"):
                        break
                elif live_text.is_live_payload(payload):
                    frame = viewer.frame_for(payload)  # None for a delta the snapshot above already contained
                    if frame:
                        yield _sse_format(*frame)
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
        with live_text.streaming_for(row["session_id"]):
            await agent_loop.resume_after_approval(row["session_id"], user.user_id)
    return _approval_out(row)
