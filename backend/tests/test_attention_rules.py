"""Phase Convert (C8.2, C8.3) — what makes the red dot, and what a project's list row says."""
from datetime import datetime, timedelta, timezone

from app.services.attention_rules import FAILED_WINDOW_HOURS, count_attention, summarize_project_sessions

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _row(status, hours_ago=0.0):
    return {"status": status, "updated_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_nothing_needs_attention_by_default():
    assert count_attention([], now=NOW) == {"waiting_approval": 0, "failed": 0}
    assert count_attention([_row("idle"), _row("running"), _row("completed")], now=NOW) == {
        "waiting_approval": 0,
        "failed": 0,
    }


def test_waiting_approval_counts_regardless_of_age():
    assert count_attention([_row("waiting_approval", hours_ago=500)], now=NOW)["waiting_approval"] == 1


def test_a_recent_failure_counts_and_an_old_one_ages_out():
    rows = [_row("failed", hours_ago=1), _row("stuck", hours_ago=FAILED_WINDOW_HOURS - 1), _row("failed", hours_ago=FAILED_WINDOW_HOURS + 1)]
    assert count_attention(rows, now=NOW)["failed"] == 2


def test_archived_never_counts():
    assert count_attention([_row("archived")], now=NOW) == {"waiting_approval": 0, "failed": 0}


def test_unparseable_timestamp_on_a_failure_does_not_count_or_crash():
    assert count_attention([{"status": "failed", "updated_at": "not a date"}, {"status": "failed"}], now=NOW)["failed"] == 0


def test_naive_and_z_suffixed_timestamps_are_read_as_utc():
    rows = [{"status": "failed", "updated_at": "2026-10-10T11:00:00Z"}, {"status": "failed", "updated_at": "2026-10-10T11:00:00"}]
    assert count_attention(rows, now=NOW)["failed"] == 2


def test_project_with_no_sessions_is_idle_with_no_activity():
    assert summarize_project_sessions([]) == {"status": "idle", "last_activity_at": None}


def test_project_status_prefers_waiting_over_running_over_idle():
    assert summarize_project_sessions([_row("idle"), _row("running")])["status"] == "running"
    assert summarize_project_sessions([_row("running"), _row("waiting_approval"), _row("idle")])["status"] == "waiting_approval"
    assert summarize_project_sessions([_row("waiting_approval"), _row("running")])["status"] == "waiting_approval"
    assert summarize_project_sessions([_row("completed"), _row("failed")])["status"] == "idle"


def test_last_activity_is_the_newest_update_and_ignores_archived_sessions():
    rows = [_row("idle", hours_ago=10), _row("completed", hours_ago=2), _row("archived", hours_ago=0)]
    assert summarize_project_sessions(rows)["last_activity_at"] == NOW - timedelta(hours=2)
