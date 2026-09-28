"""
§26 — Scheduling / Proactive Scanning: the pure "is this schedule due right
now?" rule, factored out of app/services/scheduler.py the same way
guard_rules.py / tool_partition.py / stuck_detector.py each keep their own
decision logic dependency-free and directly unit-testable (see
backend/tests/test_scheduler_rules.py) — no app.db / app.config / httpx
import here, nothing to mock to test it.

Design decision the spec excerpt doesn't spell out: whether a brand-new
schedule (never run yet) fires on the very next poll tick, or waits for its
first real interval/cron tick to elapse first. This picks the former — due
immediately once `last_run_at is None` — for every frequency, including
'custom'. Reasoning: the person just opted into this from this project's own
Settings; an immediate first run is the fastest confirmation that it's wired
up correctly (the GitHub connector they meant to grant it actually is, the
project's LLM credential resolves, and so on) rather than leaving them to
wonder, possibly for up to 24 hours, whether anything is even happening.
Every run after the first follows the schedule's own configured cadence
exactly, measured from `last_run_at`, not from `created_at` — a schedule
disabled and re-enabled later resumes on the same cadence rather than
treating re-enabling as a second "brand new" schedule.
"""
import datetime

from croniter import croniter

Frequency = str  # 'hourly' | 'daily' | 'custom' — see 0009_scheduling.sql's own check constraint


def is_due(
    frequency: Frequency,
    cron_expression: str | None,
    last_run_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    """`last_run_at`/`now` must both be timezone-aware (UTC, same as every
    other timestamp this codebase stores — see every `timestamptz` column
    from 0001_extensions.sql onward). Callers (scheduler.py) are expected to
    have already filtered to `enabled = true` rows — this function has no
    opinion on `enabled` itself, since "is this schedule configured to ever
    fire" and "is it due right now" are two independent questions."""
    if last_run_at is None:
        return True  # see module docstring — a schedule's first run is immediate, on every frequency

    if frequency == "hourly":
        return now - last_run_at >= datetime.timedelta(hours=1)
    if frequency == "daily":
        return now - last_run_at >= datetime.timedelta(days=1)
    if frequency == "custom":
        if not cron_expression:
            return False  # can't happen past 0009_scheduling.sql's own check constraint — defensive only
        next_fire = croniter(cron_expression, last_run_at).get_next(datetime.datetime)
        if next_fire.tzinfo is None:  # defensive — croniter normally preserves an aware base's tzinfo
            next_fire = next_fire.replace(tzinfo=datetime.timezone.utc)
        return now >= next_fire
    return False  # an unrecognized frequency — can't happen past the DB check constraint either


def validate_cron_expression(cron_expression: str) -> str | None:
    """Returns an error message if `cron_expression` isn't a syntactically
    valid 5-field crontab expression croniter can parse, else None. Used by
    the schedules router so a typo is rejected at creation time with a clear
    message, rather than silently never firing (`is_due` above would raise
    from inside croniter on a genuinely malformed expression — this is the
    one place that's caught and turned into a 400, not swallowed)."""
    try:
        croniter(cron_expression)
    except (ValueError, KeyError) as exc:
        return str(exc)
    return None
