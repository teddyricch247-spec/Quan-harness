"""Phase 5.7/5.8 — per-turn budgets read from the durable event log."""
from app.services import turn_limits as tl


def _call(name, event_id=0):
    return {"id": event_id, "event_type": "tool_call", "role": "agent", "content": {"name": name}}


USER = {"id": 1, "event_type": "message", "role": "user", "content": {"text": "go"}}


def test_the_nth_delegation_is_allowed_and_the_next_one_is_refused():
    events = [USER] + [_call("delegate_task", i) for i in range(tl.MAX_DELEGATIONS_PER_TURN)]
    assert not tl.exceeded(events, "delegate_task")                      # the 5th (its own event already appended)
    assert tl.exceeded(events + [_call("delegate_task", 99)], "delegate_task")   # the 6th


def test_two_calls_in_one_response_count_against_each_other():
    events = [USER] + [_call("preview_rebuild", i) for i in range(tl.MAX_REBUILDS_PER_TURN + 1)]
    assert tl.exceeded(events, "preview_rebuild")


def test_a_new_user_message_starts_a_new_turn_but_an_interrupt_does_not():
    spent = [_call("delegate_task", i) for i in range(tl.MAX_DELEGATIONS_PER_TURN + 1)]
    assert tl.exceeded([USER, *spent], "delegate_task")
    interrupt = {"id": 50, "event_type": "user_interrupt", "role": "user", "content": {"text": "also"}}
    assert tl.exceeded([USER, *spent, interrupt, _call("delegate_task", 51)], "delegate_task")
    assert not tl.exceeded([USER, *spent, {**USER, "id": 60}, _call("delegate_task", 61)], "delegate_task")


def test_other_tools_and_other_budgets_are_independent():
    events = [USER] + [_call("view_file", i) for i in range(100)] + [_call("delegate_task", 200)]
    assert not tl.exceeded(events, "view_file") and not tl.exceeded(events, "delegate_task")
    assert tl.count_in_turn(events, "view_file") == 100
    assert tl.limit_message("delegate_task") and tl.limit_message("preview_rebuild") and tl.limit_message("x")
