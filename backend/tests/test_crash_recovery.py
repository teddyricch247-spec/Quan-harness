from app.services.crash_recovery import find_dangling_events


def _event(id_, event_type, parent_event_id=None, content=None):
    return {"id": id_, "event_type": event_type, "parent_event_id": parent_event_id, "content": content or {}}


def test_no_events_no_dangling():
    assert find_dangling_events([]) == []


def test_a_completed_tool_call_is_not_dangling():
    events = [
        _event(1, "tool_call", content={"name": "view_file", "read_only": True}),
        _event(2, "tool_result", parent_event_id=1),
    ]
    assert find_dangling_events(events) == []


def test_a_tool_call_with_no_result_is_dangling():
    events = [_event(1, "tool_call", content={"name": "execute_bash", "read_only": False})]
    dangling = find_dangling_events(events)
    assert len(dangling) == 1
    assert dangling[0].event["id"] == 1


def test_read_only_dangling_call_classified_as_reexecute():
    events = [_event(1, "tool_call", content={"name": "view_file", "read_only": True})]
    dangling = find_dangling_events(events)
    assert dangling[0].kind == "reexecute"


def test_mutating_dangling_call_classified_as_interrupted():
    events = [_event(1, "tool_call", content={"name": "execute_bash", "read_only": False})]
    dangling = find_dangling_events(events)
    assert dangling[0].kind == "interrupted"


def test_missing_read_only_key_defaults_to_interrupted():
    events = [_event(1, "tool_call", content={"name": "mystery_tool"})]
    dangling = find_dangling_events(events)
    assert dangling[0].kind == "interrupted"


def test_a_resolved_approval_request_is_not_dangling():
    events = [
        _event(1, "approval_request", content={"action_type": "execute_bash_escalation"}),
        _event(2, "approval_response", parent_event_id=1),
    ]
    assert find_dangling_events(events) == []


def test_an_unresolved_approval_request_is_dangling_and_pending():
    events = [_event(1, "approval_request", content={"action_type": "execute_bash_escalation"})]
    dangling = find_dangling_events(events)
    assert len(dangling) == 1
    assert dangling[0].kind == "pending_approval"


def test_message_and_system_events_are_never_dangling():
    events = [_event(1, "message"), _event(2, "system"), _event(3, "stuck_notice")]
    assert find_dangling_events(events) == []


def test_multiple_dangling_events_all_reported():
    events = [
        _event(1, "tool_call", content={"name": "view_file", "read_only": True}),
        _event(2, "tool_call", content={"name": "execute_bash", "read_only": False}),
    ]
    dangling = find_dangling_events(events)
    assert {d.event["id"] for d in dangling} == {1, 2}


def test_a_later_unrelated_event_does_not_resolve_an_earlier_dangling_call():
    events = [
        _event(1, "tool_call", content={"name": "view_file", "read_only": True}),
        _event(2, "message"),  # doesn't reference event 1 as its parent
    ]
    dangling = find_dangling_events(events)
    assert len(dangling) == 1 and dangling[0].event["id"] == 1
