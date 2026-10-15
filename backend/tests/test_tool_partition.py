from app.services import tool_partition as tp
from dataclasses import dataclass

from app.services.tool_partition import is_read_only, partition


@dataclass
class _Call:
    name: str


def test_view_file_is_read_only():
    assert is_read_only("view_file") is True


def test_web_search_is_read_only():
    assert is_read_only("web_search") is True


def test_browser_tools_are_read_only():
    for name in (
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_get_console_logs",
    ):
        assert is_read_only(name) is True


def test_str_replace_create_file_execute_bash_are_always_mutating():
    for name in ("str_replace", "create_file", "execute_bash"):
        assert is_read_only(name) is False
        # unconditionally — a caller passing mcp_side_effect_free=True for a
        # native tool must not flip it (that flag only applies to mcp__ tools)
        assert is_read_only(name, mcp_side_effect_free=True) is False


def test_run_lint_run_tests_update_plan_default_to_mutating():
    for name in ("run_lint", "run_tests", "update_plan"):
        assert is_read_only(name) is False


def test_mcp_tool_follows_its_own_side_effect_free_flag():
    assert is_read_only("mcp__github__list_issues", mcp_side_effect_free=True) is True
    assert is_read_only("mcp__github__create_issue", mcp_side_effect_free=False) is False


def test_partition_splits_and_preserves_order():
    calls = [_Call("view_file"), _Call("str_replace"), _Call("view_file"), _Call("execute_bash")]
    read_only, mutating = partition(calls)
    assert [c.name for c in read_only] == ["view_file", "view_file"]
    assert [c.name for c in mutating] == ["str_replace", "execute_bash"]


def test_partition_respects_per_call_mcp_flags():
    calls = [_Call("mcp__x__read"), _Call("mcp__x__write")]
    read_only, mutating = partition(calls, side_effect_free_by_name={"mcp__x__read": True, "mcp__x__write": False})
    assert [c.name for c in read_only] == ["mcp__x__read"]
    assert [c.name for c in mutating] == ["mcp__x__write"]


def test_partition_empty_batch():
    assert partition([]) == ([], [])


# --- Phase 5.8: browser tools share a lane ---------------------------------------------------------------------------


def _calls(*names):
    from types import SimpleNamespace

    return [SimpleNamespace(name=n) for n in names]


def test_browser_tools_share_one_lane_in_issue_order_and_every_other_call_has_its_own():
    lanes = tp.group_into_lanes(_calls("view_file", "browser_navigate", "view_file", "browser_screenshot", "browser_get_console_logs", "preview_status"))
    assert lanes == [[0], [1, 3, 4], [2], [5]]


def test_no_browser_calls_means_every_call_is_concurrent_and_nothing_is_dropped():
    assert tp.group_into_lanes(_calls("view_file", "view_file")) == [[0], [1]] and tp.group_into_lanes([]) == []


def test_the_local_browser_name_set_matches_the_schemas_and_preview_status_is_read_only():
    from app.services import tool_schemas

    assert tp.BROWSER_TOOL_NAMES == tool_schemas.BROWSER_TOOL_NAMES
    assert tp.is_read_only("preview_status") and not tp.is_read_only("preview_rebuild") and not tp.is_read_only("delegate_task")
