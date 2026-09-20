from app.services import message_builder
from app.services.message_builder import build_messages

SYS = "SYSTEM PROMPT TEXT"


def _msg(id_, role, text, step=None):
    content = {"text": text}
    if step is not None:
        content["step"] = step
    return {"id": id_, "role": role, "event_type": "message", "content": content, "parent_event_id": None}


def _tool_call(id_, step, call_id, name, arguments, parent=None):
    return {
        "id": id_,
        "role": "agent",
        "event_type": "tool_call",
        "content": {"step": step, "call_id": call_id, "name": name, "arguments": arguments, "read_only": False},
        "parent_event_id": parent,
    }


def _tool_result(id_, parent_event_id, ok, content="", error=""):
    return {
        "id": id_,
        "role": "system",
        "event_type": "tool_result",
        "content": {"ok": ok, "content": content, "error": error},
        "parent_event_id": parent_event_id,
    }


def test_system_prompt_always_first():
    messages = build_messages(SYS, [])
    assert messages == [{"role": "system", "content": SYS}]


def test_plain_user_message():
    messages = build_messages(SYS, [_msg(1, "user", "fix the bug")])
    assert messages[1] == {"role": "user", "content": "fix the bug"}


def test_plain_agent_text_with_no_tool_calls():
    events = [_msg(1, "agent", "Sure, on it.", step=1)]
    messages = build_messages(SYS, events)
    assert messages[1] == {"role": "assistant", "content": "Sure, on it."}


def test_agent_text_plus_single_tool_call_and_result():
    events = [
        _msg(1, "agent", "Let me check.", step=1),
        _tool_call(2, 1, "call_1", "view_file", {"path": "a.py"}),
        _tool_result(3, 2, ok=True, content="print(1)"),
    ]
    messages = build_messages(SYS, events)
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Let me check."
    assert messages[1]["tool_calls"][0]["id"] == "call_1"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "view_file"
    assert messages[2] == {"role": "tool", "tool_call_id": "call_1", "content": "print(1)"}


def test_tool_call_with_no_leading_text():
    events = [
        _tool_call(1, 1, "call_1", "execute_bash", {"command": "ls"}),
        _tool_result(2, 1, ok=True, content="a.py\nb.py"),
    ]
    messages = build_messages(SYS, events)
    assert messages[1]["content"] is None
    assert messages[1]["tool_calls"][0]["function"]["name"] == "execute_bash"
    assert messages[2]["content"] == "a.py\nb.py"


def test_multiple_tool_calls_in_the_same_step_all_grouped():
    events = [
        _msg(1, "agent", "", step=1),
        _tool_call(2, 1, "call_1", "view_file", {"path": "a.py"}),
        _tool_call(3, 1, "call_2", "view_file", {"path": "b.py"}),
        _tool_result(4, 2, ok=True, content="A"),
        _tool_result(5, 3, ok=True, content="B"),
    ]
    messages = build_messages(SYS, events)
    assert len(messages[1]["tool_calls"]) == 2
    assert messages[2]["content"] == "A"
    assert messages[3]["content"] == "B"


def test_interleaved_call_result_call_result_still_groups_into_one_assistant_message():
    # what agent_loop.py actually produces for a mutating batch — each result
    # appended right after its own call, for live SSE streaming, rather than
    # withholding every result until the whole batch finishes
    events = [
        _msg(1, "agent", "", step=1),
        _tool_call(2, 1, "call_1", "str_replace", {"path": "a.py"}),
        _tool_result(3, 2, ok=True, content="ok"),
        _tool_call(4, 1, "call_2", "execute_bash", {"command": "pytest"}),
        _tool_result(5, 4, ok=True, content="3 passed"),
    ]
    messages = build_messages(SYS, events)
    assert len(messages) == 4  # system, assistant(2 calls), and the two tool results
    assert len(messages[1]["tool_calls"]) == 2
    assert [m["role"] for m in messages[2:]] == ["tool", "tool"]


def test_interleaved_ordering_preserves_which_result_goes_with_which_call():
    events = [
        _tool_call(1, 1, "call_1", "view_file", {"path": "a.py"}),
        _tool_result(2, 1, ok=True, content="A"),
        _tool_call(3, 1, "call_2", "view_file", {"path": "b.py"}),
        _tool_result(4, 3, ok=True, content="B"),
    ]
    messages = build_messages(SYS, events)
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert tool_msgs[0]["tool_call_id"] == "call_1" and tool_msgs[0]["content"] == "A"
    assert tool_msgs[1]["tool_call_id"] == "call_2" and tool_msgs[1]["content"] == "B"


def test_a_gated_call_with_no_result_yet_still_ends_the_group_cleanly():
    # the call after a gated one is never even recorded (discarded per §16.2) —
    # only the gated call itself appears, with a placeholder result
    events = [
        _msg(1, "agent", "", step=1),
        _tool_call(2, 1, "call_1", "execute_bash", {"command": "rm -rf x"}),
    ]
    messages = build_messages(SYS, events)
    assert len(messages[1]["tool_calls"]) == 1
    assert "did not finish" in messages[2]["content"]


def test_an_unrelated_event_between_calls_breaks_the_group():
    events = [
        _tool_call(1, 1, "call_1", "view_file", {"path": "a.py"}),
        _tool_result(2, 1, ok=True, content="A"),
        {"id": 3, "role": "user", "event_type": "user_interrupt", "content": {"text": "wait, stop"}, "parent_event_id": None},
        _tool_call(4, 1, "call_2", "view_file", {"path": "b.py"}),
        _tool_result(5, 4, ok=True, content="B"),
    ]
    messages = build_messages(SYS, events)
    # two separate assistant/tool exchanges, split by the interrupt in between
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 2
    assert len(assistant_msgs[0]["tool_calls"]) == 1
    assert len(assistant_msgs[1]["tool_calls"]) == 1


def test_failed_tool_result_renders_as_error_text():
    events = [
        _tool_call(1, 1, "call_1", "execute_bash", {"command": "bad"}),
        _tool_result(2, 1, ok=False, error="command not found"),
    ]
    messages = build_messages(SYS, events)
    assert messages[2]["content"] == "Error: command not found"


def test_missing_tool_result_renders_as_placeholder_not_a_crash():
    events = [_tool_call(1, 1, "call_1", "execute_bash", {"command": "sleep 999"})]
    messages = build_messages(SYS, events)
    assert "did not finish" in messages[2]["content"]


def test_user_interrupt_becomes_a_user_message():
    events = [{"id": 1, "role": "user", "event_type": "user_interrupt", "content": {"text": "actually stop"}, "parent_event_id": None}]
    messages = build_messages(SYS, events)
    assert messages[1]["role"] == "user"
    assert "actually stop" in messages[1]["content"]


def test_approval_response_approved_becomes_a_user_message():
    events = [{"id": 1, "role": "user", "event_type": "approval_response", "content": {"approved": True}, "parent_event_id": None}]
    messages = build_messages(SYS, events)
    assert "Approved" in messages[1]["content"]


def test_approval_response_rejected_tells_the_model_not_to_repeat_it():
    events = [{"id": 1, "role": "user", "event_type": "approval_response", "content": {"approved": False}, "parent_event_id": None}]
    messages = build_messages(SYS, events)
    assert "Rejected" in messages[1]["content"]


def test_approval_request_itself_is_not_rendered_as_a_message():
    events = [
        _tool_call(1, 1, "call_1", "execute_bash", {"command": "rm x"}),
        {"id": 2, "role": "system", "event_type": "approval_request", "content": {"action_type": "execute_bash_escalation"}, "parent_event_id": 1},
    ]
    messages = build_messages(SYS, events)
    # the tool_call becomes an assistant message with a placeholder tool result
    # (still gated, no real result yet) — the approval_request row itself
    # contributes nothing of its own to the message list
    assert len(messages) == 3
    assert messages[1]["tool_calls"][0]["id"] == "call_1"
    assert "did not finish" in messages[2]["content"]


def test_condensation_summary_becomes_a_user_message():
    events = [{"id": 1, "role": "system", "event_type": "condensation_summary", "content": {"text": "<compacted-summary>...</compacted-summary>"}, "parent_event_id": None}]
    messages = build_messages(SYS, events)
    assert "compacted-summary" in messages[1]["content"]


def test_stuck_notice_becomes_a_user_message():
    events = [{"id": 1, "role": "system", "event_type": "stuck_notice", "content": {"text": "You're stuck.", "severity": "hard"}, "parent_event_id": None}]
    messages = build_messages(SYS, events)
    assert "stuck" in messages[1]["content"].lower()


def test_apply_condensation_no_summary_returns_events_unchanged():
    events = [_msg(1, "user", "hi")]
    assert message_builder.apply_condensation(events) is events or message_builder.apply_condensation(events) == events


def test_apply_condensation_puts_summary_first_then_kept_events_in_order():
    events = [
        _msg(1, "user", "old message, should be dropped"),
        _msg(2, "agent", "old reply, should be dropped", step=1),
        _msg(3, "user", "recent message, kept", step=None),
        _msg(4, "agent", "recent reply, kept", step=2),
        {
            "id": 5,
            "role": "system",
            "event_type": "condensation_summary",
            "content": {"text": "<compacted-summary>...</compacted-summary>", "kept_from_event_id": 3},
            "parent_event_id": None,
        },
    ]
    result = message_builder.apply_condensation(events)
    assert [e["id"] for e in result] == [5, 3, 4]


def test_apply_condensation_uses_the_most_recent_summary_if_several_exist():
    events = [
        _msg(1, "user", "very old"),
        {"id": 2, "role": "system", "event_type": "condensation_summary", "content": {"text": "first summary", "kept_from_event_id": 1}, "parent_event_id": None},
        _msg(3, "user", "kept 1"),
        _msg(4, "user", "kept 2"),
        {"id": 5, "role": "system", "event_type": "condensation_summary", "content": {"text": "second summary", "kept_from_event_id": 4}, "parent_event_id": None},
    ]
    result = message_builder.apply_condensation(events)
    assert [e["id"] for e in result] == [5, 4]
    assert result[0]["content"]["text"] == "second summary"


def test_apply_condensation_then_build_messages_end_to_end():
    events = [
        _msg(1, "user", "old — condensed away"),
        _msg(2, "user", "kept"),
        {"id": 3, "role": "system", "event_type": "condensation_summary", "content": {"text": "SUMMARY TEXT", "kept_from_event_id": 2}, "parent_event_id": None},
    ]
    condensed = message_builder.apply_condensation(events)
    messages = build_messages(SYS, condensed)
    assert messages[1]["content"] == "SUMMARY TEXT"
    assert messages[2]["content"] == "kept"
    assert "old — condensed away" not in [m.get("content") for m in messages]
    events = [
        _msg(1, "user", "add a health endpoint"),
        _msg(2, "agent", "I'll check the router first.", step=1),
        _tool_call(3, 1, "call_1", "view_file", {"path": "app/main.py"}),
        _tool_result(4, 3, ok=True, content="from fastapi import FastAPI"),
        _msg(5, "agent", "Adding it now.", step=2),
        _tool_call(6, 2, "call_2", "str_replace", {"path": "app/main.py", "old_str": "x", "new_str": "y"}),
        _tool_result(7, 6, ok=True, content="y"),
        _msg(8, "agent", "Done — added /health.", step=3),
    ]
    messages = build_messages(SYS, events)
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert messages[-1]["content"] == "Done — added /health."
