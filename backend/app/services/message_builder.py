"""
§17 dynamic item 6: "conversation and tool-call history, translated into the
provider's native message format via the LLM wrapper." This is that
translation — pure (no I/O), given an already-fetched event list, so the
tricky part (correctly grouping tool_calls with the assistant message and
tool_results they belong to, into the shape an OpenAI-style
`tool_calls`/`role="tool"` exchange requires) is unit-tested directly
(backend/tests/test_message_builder.py) rather than only exercised end-to-end
against a real LLM credential this sandbox doesn't have — see
/docs/PHASE3_NOTES.md.

Event content shapes this module depends on (agent_loop.py is the only
writer, so these are an internal contract, not a public API):
  message      (role=user)   {"text"}
  message      (role=agent)  {"text", "step"}
  tool_call    (role=agent)  {"step", "call_id", "name", "arguments", "read_only"}
  tool_result  (role=system, parent_event_id=the tool_call's id)
                              {"ok", "content", "error"}
  approval_response (role=system, parent_event_id=the approval_request's id)
                              {"approved": bool}
  user_interrupt   (role=user)   {"text"}
  stuck_notice     (role=system) {"text", "severity"}
  condensation_summary (role=system) {"text"}  -- the checkpoint text itself

A tool_call with no matching tool_result yet (still genuinely pending — should
never reach call_llm in that state; agent_loop.py's crash-recovery/resume path
always resolves or re-executes a dangling call before assembling messages
again) renders as a placeholder rather than raising, so a bug upstream shows
up as a strange-looking model turn instead of a hard crash.
"""
import json

_PENDING_PLACEHOLDER = "(this call did not finish before the session was interrupted)"


def _tool_result_text(result_event: dict | None) -> str:
    if result_event is None:
        return _PENDING_PLACEHOLDER
    content = result_event.get("content", {})
    if content.get("ok"):
        return content.get("content", "")
    return f"Error: {content.get('error', 'unknown error')}"


def _assistant_message_with_tool_calls(text: str | None, tool_call_events: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": e["content"]["call_id"],
                "type": "function",
                "function": {"name": e["content"]["name"], "arguments": json.dumps(e["content"]["arguments"])},
            }
            for e in tool_call_events
        ],
    }


def apply_condensation(events: list[dict]) -> list[dict]:
    """§17.1 compaction support. A `condensation_summary` event is always
    appended at the *end* of the log chronologically (agent_loop.py's
    _run_compaction runs it as an auxiliary call before the next normal
    call_llm), but what it represents — "everything before this point,
    condensed" — needs to sit at the *front* of the reconstructed message
    list, immediately followed by whatever was kept verbatim (the most
    recent full step at the time compaction ran, per §17.1's own rule).

    Its content therefore carries `kept_from_event_id`: the id of the
    earliest event that should still be replayed verbatim after it. This
    function is the only place that boundary is interpreted — build_messages
    itself has no notion of compaction at all, it just renders whatever event
    list it's given. Returns `events` unchanged if there's no condensation_summary.
    """
    summaries = [e for e in events if e["event_type"] == "condensation_summary"]
    if not summaries:
        return events
    latest = max(summaries, key=lambda e: e["id"])
    kept_from_id = latest["content"]["kept_from_event_id"]
    kept = [e for e in events if e["id"] >= kept_from_id and e["id"] != latest["id"]]
    return [latest] + kept


def build_messages(system_text: str, events: list[dict]) -> list[dict]:
    """`events` — every session_events row for this session, oldest first
    (session_events_repo.list_for_session's own order)."""
    messages: list[dict] = [{"role": "system", "content": system_text}]

    results_by_parent: dict[int, dict] = {
        e["parent_event_id"]: e
        for e in events
        if e["event_type"] == "tool_result" and e.get("parent_event_id") is not None
    }

    i, n = 0, len(events)
    while i < n:
        event = events[i]
        etype = event["event_type"]

        if etype == "message" and event["role"] == "user":
            messages.append({"role": "user", "content": event["content"]["text"]})
            i += 1
        elif etype == "user_interrupt":
            messages.append({"role": "user", "content": f"[Interruption from the person] {event['content']['text']}"})
            i += 1
        elif etype == "stuck_notice":
            messages.append({"role": "user", "content": f"[System] {event['content']['text']}"})
            i += 1
        elif etype == "approval_response":
            approved = event["content"].get("approved")
            text = "Approved — proceed." if approved else "Rejected — do not repeat that exact call; try a different approach or ask what to do instead."
            messages.append({"role": "user", "content": f"[System] {text}"})
            i += 1
        elif etype == "condensation_summary":
            messages.append({"role": "user", "content": event["content"]["text"]})
            i += 1
        elif etype == "message" and event["role"] == "agent":
            step = event["content"].get("step")
            text = event["content"].get("text", "")
            tool_call_events, j = _collect_step_tool_calls(events, i + 1, step)
            if not tool_call_events:
                messages.append({"role": "assistant", "content": text})
                i += 1
            else:
                messages.append(_assistant_message_with_tool_calls(text, tool_call_events))
                for tc_event in tool_call_events:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_event["content"]["call_id"],
                            "content": _tool_result_text(results_by_parent.get(tc_event["id"])),
                        }
                    )
                i = j
        elif etype == "tool_call" and event["role"] == "agent":
            # A step whose assistant response had no text, only tool calls.
            step = event["content"].get("step")
            tool_call_events, j = _collect_step_tool_calls(events, i, step)
            messages.append(_assistant_message_with_tool_calls(None, tool_call_events))
            for tc_event in tool_call_events:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_event["content"]["call_id"],
                        "content": _tool_result_text(results_by_parent.get(tc_event["id"])),
                    }
                )
            i = j
        else:
            # tool_result / approval_request / error / anything else — already
            # folded into the assistant/tool exchange above, or not directly
            # renderable as its own message.
            i += 1

    return messages


def _collect_step_tool_calls(events: list[dict], start: int, step) -> tuple[list[dict], int]:
    """Collects every `tool_call` event belonging to `step`, tolerating its own
    `tool_result` events interleaved between them — agent_loop.py appends each
    mutating call's result immediately after executing it (call, result, call,
    result...), rather than withholding every result until the whole batch
    finishes, so a live SSE viewer sees each outcome as soon as it's ready
    instead of a long silent gap. A tool_result only ever continues the scan
    when its parent is one of the tool_calls already collected in this same
    group; anything else (a different step, a message, a user_interrupt) ends
    the group, same as before."""
    tool_calls: list[dict] = []
    collected_ids: set[int] = set()
    j = start
    while j < len(events):
        event = events[j]
        if event["event_type"] == "tool_call" and event["content"].get("step") == step:
            tool_calls.append(event)
            collected_ids.add(event["id"])
            j += 1
            continue
        if event["event_type"] == "tool_result" and event.get("parent_event_id") in collected_ids:
            j += 1  # belongs to this group — rendered afterward via results_by_parent, not here
            continue
        break
    return tool_calls, j
