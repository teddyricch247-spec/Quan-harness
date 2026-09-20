"""§19. Every case here is pure-logic, no database/LLM credential needed —
same reasoning as test_heuristic_guard.py and test_checkpoint_fifo.py."""
from app.services.stuck_detector import (
    StuckEvent,
    hash_content,
    normalize_args,
    normalize_result,
    run_stuck_detector,
)


def _view(path: str, content: str = "x") -> StuckEvent:
    return StuckEvent(
        tool="view_file",
        args_key=normalize_args("view_file", {"path": path}),
        result_key=normalize_result("view_file", ok=True, content=content),
        success=True,
    )


def _bash_fail(command: str, error: str) -> StuckEvent:
    return StuckEvent(
        tool="execute_bash",
        args_key=normalize_args("execute_bash", {"command": command}),
        result_key=normalize_result("execute_bash", ok=False, error=error),
        success=False,
    )


def _edit(path: str, content: str) -> StuckEvent:
    h = hash_content(content)
    return StuckEvent(
        tool="str_replace",
        args_key=normalize_args("str_replace", {"path": path, "old_str": "a", "new_str": content}),
        result_key=normalize_result("str_replace", ok=True, content=content),
        success=True,
        file_path=path,
        content_hash=h,
    )


# --- empty / normal operation -------------------------------------------------


def test_empty_history_is_fine():
    check = run_stuck_detector([])
    assert not check.hard_stop and not check.soft_warning


def test_a_handful_of_varied_calls_is_fine():
    events = [_view("a.py"), _view("b.py"), _edit("a.py", "one"), _view("c.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop and not check.soft_warning


# --- signal 1: repeating call-and-result --------------------------------------


def test_same_readonly_call_twice_is_not_yet_a_hard_stop():
    events = [_view("a.py"), _view("a.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_same_readonly_call_three_times_is_a_hard_stop():
    events = [_view("a.py"), _view("a.py"), _view("a.py")]
    check = run_stuck_detector(events)
    assert check.hard_stop
    assert "view_file" in check.explanation


def test_three_in_a_row_but_different_content_does_not_trip():
    events = [_view("a.py", "v1"), _view("a.py", "v2"), _view("a.py", "v3")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_different_paths_do_not_trip_even_if_same_tool():
    events = [_view("a.py"), _view("b.py"), _view("c.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


# --- signal 3: repeating error with grace nudge -------------------------------


def test_two_identical_failures_in_a_row_gives_one_time_nudge():
    events = [_bash_fail("pytest", "ModuleNotFoundError"), _bash_fail("pytest", "ModuleNotFoundError")]
    check = run_stuck_detector(events)
    assert not check.hard_stop
    assert check.soft_warning
    assert "will not work" in check.explanation


def test_three_identical_failures_in_a_row_is_a_hard_stop():
    events = [_bash_fail("pytest", "ModuleNotFoundError")] * 3
    check = run_stuck_detector(events)
    assert check.hard_stop


def test_two_failures_of_different_commands_does_not_nudge():
    events = [_bash_fail("pytest", "err"), _bash_fail("flake8", "err")]
    check = run_stuck_detector(events)
    assert not check.hard_stop and not check.soft_warning


def test_recovering_after_one_failure_does_not_nudge():
    events = [_bash_fail("pytest", "err"), _view("a.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop and not check.soft_warning


# --- signal 2: edit/revert/re-edit cycle --------------------------------------


def test_a_single_revert_is_not_yet_a_hard_stop():
    events = [_edit("a.py", "v1"), _edit("a.py", "v2"), _edit("a.py", "v1")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_two_reverts_of_the_same_file_is_a_hard_stop():
    events = [
        _edit("a.py", "v1"),
        _edit("a.py", "v2"),
        _edit("a.py", "v1"),  # 1st revert
        _edit("a.py", "v2"),
        _edit("a.py", "v1"),  # 2nd revert
    ]
    check = run_stuck_detector(events)
    assert check.hard_stop
    assert "a.py" in check.explanation


def test_reverts_across_different_files_do_not_combine():
    events = [
        _edit("a.py", "v1"),
        _edit("a.py", "v2"),
        _edit("a.py", "v1"),  # a.py's only revert
        _edit("b.py", "v1"),
        _edit("b.py", "v2"),
        _edit("b.py", "v1"),  # b.py's only revert — different file, doesn't add to a.py's count
    ]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_a_brand_new_file_content_never_seen_before_does_not_count():
    events = [_edit("a.py", "v1"), _edit("a.py", "v2"), _edit("a.py", "v3")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_failed_edits_are_not_counted_toward_revert_cycles():
    failed = StuckEvent(
        tool="str_replace",
        args_key="x",
        result_key="y",
        success=False,
        file_path="a.py",
        content_hash=hash_content("v1"),
    )
    events = [_edit("a.py", "v1"), _edit("a.py", "v2"), failed, failed]
    check = run_stuck_detector(events)
    assert not check.hard_stop


# --- signal 4: alternating pattern --------------------------------------------


def test_alternating_two_full_cycles_is_a_hard_stop():
    events = [_view("a.py"), _view("b.py"), _view("a.py"), _view("b.py")]
    check = run_stuck_detector(events)
    assert check.hard_stop
    assert "Alternating" in check.explanation


def test_alternating_one_cycle_only_is_not_yet_a_hard_stop():
    events = [_view("a.py"), _view("b.py"), _view("a.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


def test_three_distinct_actions_do_not_alternate():
    events = [_view("a.py"), _view("b.py"), _view("c.py"), _view("a.py")]
    check = run_stuck_detector(events)
    assert not check.hard_stop


# --- soft warning: 15 consecutive Auto calls with no edit --------------------


def test_fifteen_reads_with_no_edit_does_not_yet_warn():
    events = [_view(f"f{i}.py", f"v{i}") for i in range(15)]
    check = run_stuck_detector(events)
    assert not check.soft_warning


def test_sixteen_reads_with_no_edit_warns_once():
    events = [_view(f"f{i}.py", f"v{i}") for i in range(16)]
    check = run_stuck_detector(events)
    assert check.soft_warning and not check.hard_stop


def test_soft_warning_does_not_fire_twice_in_the_same_turn():
    events = [_view(f"f{i}.py", f"v{i}") for i in range(20)]
    check = run_stuck_detector(events, already_soft_nudged_this_turn=True)
    assert not check.soft_warning


def test_an_edit_within_the_window_prevents_the_soft_warning():
    events = [_view(f"f{i}.py", f"v{i}") for i in range(10)] + [_edit("a.py", "v1")] + [
        _view(f"g{i}.py", f"v{i}") for i in range(10)
    ]
    check = run_stuck_detector(events)
    assert not check.soft_warning


# --- a legitimate two-task session never trips (caller's job, not the detector's) --


def test_detector_only_ever_sees_the_current_turns_events():
    """The detector itself has no notion of 'turn' — it's the caller's job
    (agent_loop.py) to pass only this turn's events, per the module docstring.
    This test documents that contract: a pattern that would trip the detector
    is fine as long as the caller doesn't include it."""
    task_one_events = [_view("a.py"), _view("a.py"), _view("a.py")]
    assert run_stuck_detector(task_one_events).hard_stop  # confirms it WOULD trip
    task_two_events: list[StuckEvent] = []  # a fresh turn passes an empty list
    assert not run_stuck_detector(task_two_events).hard_stop
