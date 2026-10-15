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
  message      (role=user)   {"text", "attachments"?}   -- Phase 6.1: image metadata only (see below)
  message      (role=agent)  {"text", "step"}
  tool_call    (role=agent)  {"step", "call_id", "name", "arguments", "read_only"}
  tool_result  (role=system, parent_event_id=the tool_call's id)
                              {"ok", "content", "error"}
  approval_response (role=system, parent_event_id=the approval_request's id)
                              {"approved": bool}
  user_interrupt   (role=user)   {"text", "attachments"?}
  stuck_notice     (role=system) {"text", "severity"}
  condensation_summary (role=system) {"text"}  -- the checkpoint text itself

Phase 5.7/5.8 additions (both internal contract, same writer):
  tool_result content may also carry `delegation` (a bounded trace of what a
  delegated sub-session did) and `image` (metadata about a browser screenshot).
  NEITHER is ever rendered here — `_tool_result_text` only reads ok/content/
  error, which is precisely how §14.8's "sub-agent tool calls and results never
  enter the parent's context — only the final report does" is enforced
  structurally rather than by convention. A screenshot's pixels are never
  stored in an event at all; `build_messages(..., screenshots=...)` is handed
  the few most recent ones from an in-memory store (visual_qa.ScreenshotStore)
  and places each as a user-role image message right after the tool messages of
  the step that took it.

Phase 6.1 (image input on user messages): a user `message` / `user_interrupt` may carry `attachments`, a list of
{id, filename, media_type, width, height, byte_size} — METADATA ONLY, the pixels live in `session_attachments` and
are never in an event. `build_messages(..., attachment_images=...)` is handed {attachment id: data URI} for the few
images agent_loop decided to show this call (image_input.select_attachment_ids_for_context), and renders those as
image parts on the user's own message. Every attachment NOT in that map — an older picture, or a model that can't
read images — is named in a one-line note instead, so the model knows a picture exists and doesn't pretend to have
seen it. Compaction summarises with no map at all (notes only): a summary call never needs the pixels.

A tool_call with no matching tool_result yet (still genuinely pending — should
never reach call_llm in that state; agent_loop.py's crash-recovery/resume path
always resolves or re-executes a dangling call before assembling messages
again) renders as a placeholder rather than raising, so a bug upstream shows
up as a strange-looking model turn instead of a hard crash.
"""
import json

from app.services import image_input

_PENDING_PLACEHOLDER = "(this call did not finish before the session was interrupted)"


def _tool_result_text(result_event: dict | None) -> str:
    if result_event is None:
        return _PENDING_PLACEHOLDER
    content = result_event.get("content", {})
    if content.get("ok"):
        return content.get("content", "")
    error = content.get("error") or ""
    output = content.get("content") or ""
    # Phase 5.7 fix. A command that RAN and exited non-zero (execute_bash, run_lint,
    # run_tests) is recorded as ok=False with its whole report in `content` and an
    # EMPTY `error` — and this function used to render that as the bare string
    # "Error: ", throwing away the stdout/stderr that says what failed. The model
    # was never shown a failing test's output. When there is output, it is the error.
    if error and output:
        return f"Error: {error}\n{output}"
    if output:
        return output
    return f"Error: {error or 'unknown error'}"


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


def build_messages(
    system_text: str,
    events: list[dict],
    screenshots: dict[int, str] | None = None,
    attachment_images: dict[str, str] | None = None,
) -> list[dict]:
    """`events` — every session_events row for this session, oldest first
    (session_events_repo.list_for_session's own order).

    `screenshots` — Phase 5.8: {tool_call event id: data URI} for the few most
    recent browser screenshots still held in memory. A provider's tool-result
    message can't reliably carry an image across litellm's supported providers,
    so each is delivered as a user-role message that follows the step's tool
    messages (a `role="user"` message may only come after ALL of a step's
    `role="tool"` messages, never between them). A screenshot that is no longer
    held (evicted, or the process restarted) simply isn't included; the tool
    message's own text already says what was captured.

    `attachment_images` — Phase 6.1: {attachment id: data URI} for the user-attached pictures to SHOW on this
    call. None / empty means none are shown: each is then named in a note instead (see `_user_content`)."""
    screenshots = screenshots or {}
    attachment_images = attachment_images or {}
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
            messages.append({"role": "user", "content": _user_content(event["content"]["text"], event, attachment_images)})
            i += 1
        elif etype == "user_interrupt":
            messages.append(
                {
                    "role": "user",
                    "content": _user_content(f"[Interruption from the person] {event['content']['text']}", event, attachment_images),
                }
            )
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
                messages.extend(_tool_messages(tool_call_events, results_by_parent, screenshots))
                i = j
        elif etype == "tool_call" and event["role"] == "agent":
            # A step whose assistant response had no text, only tool calls.
            step = event["content"].get("step")
            tool_call_events, j = _collect_step_tool_calls(events, i, step)
            messages.append(_assistant_message_with_tool_calls(None, tool_call_events))
            messages.extend(_tool_messages(tool_call_events, results_by_parent, screenshots))
            i = j
        else:
            # tool_result / approval_request / error / anything else — already
            # folded into the assistant/tool exchange above, or not directly
            # renderable as its own message.
            i += 1

    return messages


def _user_content(text: str, event: dict, attachment_images: dict[str, str]):
    """Plain string for a message with no attachments (byte-for-byte what it always was). With attachments:
    one text part — the person's words, then a note per group — followed by an image part for each attachment
    whose pixels were supplied, in the order the person attached them."""
    attachments = image_input.attachments_of(event)
    if not attachments:
        return text
    shown = [a for a in attachments if a["id"] in attachment_images]
    withheld = [a for a in attachments if a["id"] not in attachment_images]
    notes = []
    if shown:
        notes.append(image_input.shown_note(shown))
    if withheld:
        notes.append(image_input.withheld_note(withheld))
    body = "\n\n".join(part for part in [text, *notes] if part)
    if not shown:
        return body
    return [
        {"type": "text", "text": body},
        *({"type": "image_url", "image_url": {"url": attachment_images[a["id"]]}} for a in shown),
    ]


def _tool_messages(tool_call_events: list[dict], results_by_parent: dict[int, dict], screenshots: dict[int, str]) -> list[dict]:
    """One `role="tool"` message per call (in order), then — only if any call in
    the group produced a screenshot that's still held — ONE user message carrying
    those images. See build_messages' docstring for why images can't ride on the
    tool messages themselves."""
    out: list[dict] = []
    image_parts: list[dict] = []
    for tc_event in tool_call_events:
        out.append(
            {
                "role": "tool",
                "tool_call_id": tc_event["content"]["call_id"],
                "content": _tool_result_text(results_by_parent.get(tc_event["id"])),
            }
        )
        data_uri = screenshots.get(tc_event["id"])
        if data_uri:
            image_parts.append({"type": "image_url", "image_url": {"url": data_uri}})
    if image_parts:
        out.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": "[System] Screenshot(s) from your browser tool call(s) above:"}, *image_parts],
            }
        )
    return out


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
