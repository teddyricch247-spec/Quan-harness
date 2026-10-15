"""
Phase 5.7 / 5.8 — per-turn budgets for the two tools that can spend real time or money on their own: `delegate_task`
(a sub-session is a whole extra stream of model calls) and `preview_rebuild` (a full build + restart on the workspace).
Neither is gated by an approval (§14.8 and §14.9 make them Auto), so the cap is what stops a confused model from looping
on them. Counted from the DURABLE event log, not memory, so a restart or a crash-recovery re-run can't reset it.

A "turn" is everything since the person's last message (an interrupt steers the same turn; it does not start a new one).
`exceeded` is called AFTER the current call's own tool_call event was appended, so the Nth call is the Nth event and the
(N+1)th is the first refused — including two calls in one model response, which see each other.

Pure and dependency-free, like stuck_detector and tool_partition.
"""

MAX_DELEGATIONS_PER_TURN = 5
MAX_REBUILDS_PER_TURN = 3

_LIMITS = {
    "delegate_task": MAX_DELEGATIONS_PER_TURN,
    "preview_rebuild": MAX_REBUILDS_PER_TURN,
}


def count_in_turn(events: list[dict], tool_name: str) -> int:
    count = 0
    for event in reversed(events):
        if event.get("event_type") == "message" and event.get("role") == "user":
            break  # the person's message that started this turn
        if event.get("event_type") == "tool_call" and (event.get("content") or {}).get("name") == tool_name:
            count += 1
    return count


def exceeded(events: list[dict], tool_name: str) -> bool:
    limit = _LIMITS.get(tool_name)
    return limit is not None and count_in_turn(events, tool_name) > limit


def limit_message(tool_name: str) -> str:
    limit = _LIMITS.get(tool_name)
    if tool_name == "delegate_task":
        return (
            f"You have already delegated {limit} sub-tasks in this turn, which is the limit. Do the remaining work "
            "yourself, or finish and tell the person what is left."
        )
    if tool_name == "preview_rebuild":
        return (
            f"You have already rebuilt the preview {limit} times in this turn, which is the limit. If it still isn't "
            "working, report what you saw and what you tried instead of rebuilding again."
        )
    return "This tool has reached its limit for this turn."
