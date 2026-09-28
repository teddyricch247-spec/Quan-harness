import datetime

from app.services.scheduler_rules import is_due, validate_cron_expression

UTC = datetime.timezone.utc


def _at(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=UTC)


def test_never_run_is_always_due_regardless_of_frequency():
    now = _at(2026, 9, 25, 12, 0)
    assert is_due("hourly", None, None, now) is True
    assert is_due("daily", None, None, now) is True
    assert is_due("custom", "0 * * * *", None, now) is True


def test_hourly_not_due_before_an_hour_elapses():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 12, 59)
    assert is_due("hourly", None, last_run, now) is False


def test_hourly_due_once_an_hour_elapses():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 13, 0)
    assert is_due("hourly", None, last_run, now) is True


def test_daily_not_due_before_a_day_elapses():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 26, 11, 59)
    assert is_due("daily", None, last_run, now) is False


def test_daily_due_once_a_day_elapses():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 26, 12, 0)
    assert is_due("daily", None, last_run, now) is True


def test_custom_cron_not_due_before_next_fire_time():
    # "0 * * * *" — top of every hour.
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 12, 59)
    assert is_due("custom", "0 * * * *", last_run, now) is False


def test_custom_cron_due_at_next_fire_time():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 13, 0)
    assert is_due("custom", "0 * * * *", last_run, now) is True


def test_custom_cron_due_past_next_fire_time():
    """A missed tick (the process was asleep, e.g. a Render free-tier cold
    instance — see docs/PHASE4_5_NOTES.md) is still due, not skipped."""
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 15, 30)
    assert is_due("custom", "0 * * * *", last_run, now) is True


def test_custom_cron_with_no_expression_is_never_due():
    # Can't happen past 0009_scheduling.sql's own check constraint — defensive only.
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 13, 0)
    assert is_due("custom", None, last_run, now) is False


def test_unrecognized_frequency_is_never_due():
    last_run = _at(2026, 9, 25, 12, 0)
    now = _at(2026, 9, 25, 13, 0)
    assert is_due("weekly", None, last_run, now) is False


def test_validate_cron_expression_accepts_valid_expression():
    assert validate_cron_expression("0 * * * *") is None
    assert validate_cron_expression("*/15 9-17 * * 1-5") is None


def test_validate_cron_expression_rejects_malformed_expression():
    assert validate_cron_expression("not a cron expression") is not None
    assert validate_cron_expression("* * * *") is not None  # only 4 fields
