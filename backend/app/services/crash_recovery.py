"""
§16.4: "scan the event log for a tool_call/approval_request with no later
event referencing it as its parent_event_id... An idempotent Auto read simply
re-runs. A pending Ask approval needs no change... A non-idempotent Auto call
... surfaces plainly as an interrupted step."

Pure — takes the event list agent_loop.py already fetched via
session_events_repo.list_for_session(), same split as every other *_repo.py
I/O shell / pure-logic pairing in this codebase. Relies on each `tool_call`
event's own `content.read_only` flag, set at write time (agent_loop.py knows
whether a call was read-only when it appends the event — recomputing it here
from just the event log, after the fact, for an MCP tool in particular, would
mean re-fetching that connector's current discovered_tools, which could have
changed since the call was actually made).
"""
from dataclasses import dataclass
from typing import Literal

DanglingKind = Literal["reexecute", "pending_approval", "interrupted"]


@dataclass
class DanglingEvent:
    event: dict
    kind: DanglingKind


def find_dangling_events(events: list[dict]) -> list[DanglingEvent]:
    """`events` — every session_events row for one session, in order (as
    session_events_repo.list_for_session returns them)."""
    referenced_parent_ids = {e["parent_event_id"] for e in events if e.get("parent_event_id") is not None}
    dangling = []
    for event in events:
        if event["event_type"] not in ("tool_call", "approval_request"):
            continue
        if event["id"] in referenced_parent_ids:
            continue  # has a later tool_result/approval_response — not dangling
        dangling.append(DanglingEvent(event=event, kind=_classify(event)))
    return dangling


def _classify(event: dict) -> DanglingKind:
    if event["event_type"] == "approval_request":
        # "needs no change — its approval_requests row is still pending and
        # the card re-renders from it."
        return "pending_approval"
    if bool(event.get("content", {}).get("read_only")):
        return "reexecute"
    return "interrupted"
