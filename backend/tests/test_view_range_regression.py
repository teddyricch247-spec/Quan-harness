"""
Regression for "Internal error: object of type 'int' has no len()".

A model sent `view_range` as a bare number instead of [start, end]. agent_loop._as_range called len() on it,
the exception escaped the turn loop, and — because the tool_call was left dangling in the event log — crash
recovery re-ran it (and re-crashed) at the start of every later message in that session.
"""
import asyncio
from unittest import mock

from app.services import agent_loop, file_tools


def test_as_range_accepts_a_two_item_list_or_tuple():
    assert agent_loop._as_range([3, 9]) == (3, 9)
    assert agent_loop._as_range((3, 9)) == (3, 9)
    assert agent_loop._as_range(["3", "9"]) == (3, 9)


def test_as_range_treats_anything_else_as_no_range_instead_of_raising():
    bad_values = [None, 0, 50, 1.5, True, "", "1-50", "[1, 50]", {"start": 1, "end": 9}, [], [1], [1, 2, 3], ["a", "b"], [None, 3]]
    for bad in bad_values:
        assert agent_loop._as_range(bad) is None, bad


def test_view_file_with_a_bare_number_range_returns_the_whole_file():
    view = mock.AsyncMock(return_value=file_tools.ToolResult(ok=True, content="body"))
    with mock.patch.object(file_tools, "view_file", view):
        outcome = asyncio.run(
            agent_loop._execute_native("p1", "s1", "u1", "view_file", {"path": "a.py", "view_range": 50}, set(), {"id": "s1"})
        )
    assert outcome.ok and outcome.content == "body"
    view.assert_awaited_once_with("p1", "a.py", None)


def test_a_tool_that_raises_becomes_a_failed_result_not_a_crashed_turn():
    rows = []

    async def record(**kwargs):
        rows.append(kwargs)

    boom = mock.AsyncMock(side_effect=RuntimeError("disk on fire"))
    with mock.patch.object(file_tools, "view_file", boom), mock.patch.object(agent_loop.audit_repo, "record", record), mock.patch.object(
        agent_loop.preview_secrets_service, "get_redaction_values", mock.AsyncMock(return_value={})
    ):
        outcome = asyncio.run(
            agent_loop._execute_call("p1", "s1", "u1", "view_file", {"path": "a.py"}, set(), mock.Mock(), {"id": "s1"}, [])
        )
    assert not outcome.ok
    assert "disk on fire" in outcome.error
    assert len(rows) == 1 and rows[0]["success"] is False
