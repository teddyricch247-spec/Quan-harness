"""
§26 — Scheduling / Proactive Scanning: the background loop that turns a due
project_schedules row into a real, running session. Phase 4.5.

Runs as a single in-process asyncio task, started from main.py's lifespan on
app startup and cancelled on shutdown — not a separate Render Cron Job or
worker service. This matches what's actually deployed (see
docs/DEPLOYMENT.md / AGENTS.md): the backend is one Render web service, no
second service exists to run a cron job against, and adding one is real new
infrastructure a background asyncio task inside the process already running
avoids needing. See docs/PHASE4_5_NOTES.md for the real consequence this
choice has (a schedule can't fire while this single free-tier instance is
asleep) and what to do about it if that stops being acceptable.

Every "start a run" path in this module funnels through `trigger_schedule`,
which itself is nothing more than: create a session with
trigger='scheduled', then call agent_loop.start_turn on it — the exact same
function an interactive person's message goes through (§16.1's "starts a
session exactly the way a person's message would"). Nothing here duplicates
or re-implements any piece of the turn loop.
"""
import asyncio
import datetime
import logging

from app.config import get_settings
from app.repositories import audit as audit_repo
from app.repositories import project_schedules as schedules_repo
from app.repositories import projects as projects_repo
from app.repositories import sessions as sessions_repo
from app.services import agent_loop, scheduler_rules

logger = logging.getLogger(__name__)

_poll_task: asyncio.Task | None = None


def start() -> None:
    """Called once from main.py's lifespan, on app startup. A no-op if
    already running — defensive only; main.py's lifespan is only ever
    entered once per process, but a second call here should never spawn a
    second, competing polling loop against the same database."""
    global _poll_task
    if _poll_task is not None and not _poll_task.done():
        return
    settings = get_settings()
    _poll_task = asyncio.create_task(_poll_loop(settings.scheduler_poll_interval_seconds))


async def stop() -> None:
    """Called once from main.py's lifespan, on app shutdown. Cancels the
    loop and awaits it, rather than leaving a dangling task for Render's own
    process teardown to just kill mid-tick."""
    global _poll_task
    if _poll_task is None:
        return
    _poll_task.cancel()
    try:
        await _poll_task
    except asyncio.CancelledError:
        pass
    _poll_task = None


async def _poll_loop(interval_seconds: int) -> None:
    while True:
        try:
            await run_due_schedules()
        except Exception:  # noqa: BLE001 — one bad tick must never kill the loop for every project behind it
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(interval_seconds)


async def run_due_schedules(now: datetime.datetime | None = None) -> int:
    """One poll tick. Every enabled schedule across every account is fetched
    once (list_enabled — unscoped; see that repository function's own
    docstring for why a background loop can't use the *_owned functions),
    checked against the pure scheduler_rules.is_due, and triggered if due.
    Each schedule is evaluated/triggered inside its own try/except so one
    broken schedule (its project deleted out from under it, a transient DB
    error) can't stop every other project's schedule in the same tick from
    running. Returns the number actually triggered — used by tests and by
    nothing else in the running app, which only cares that this ran."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    triggered = 0
    for schedule in await schedules_repo.list_enabled():
        try:
            last_run_at = _parse_timestamp(schedule.get("last_run_at"))
            if not scheduler_rules.is_due(schedule["frequency"], schedule.get("cron_expression"), last_run_at, now):
                continue
            if await trigger_schedule(schedule, now):
                triggered += 1
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception("Failed to evaluate/trigger schedule %s", schedule.get("id"))
    return triggered


async def trigger_schedule(
    schedule: dict, ran_at: datetime.datetime | None = None, initiated_by: str = "system"
) -> bool:
    """Starts one real run for `schedule`, exactly the way §16.1 describes a
    person's own message starting one — see agent_loop.start_turn's own
    docstring. This is the *only* function in this codebase that starts a
    scheduled run; both the poll loop above and the "run now" endpoint
    (routers/projects.py's run_project_schedule_now, which passes
    initiated_by="user") call this same function, so there is exactly one
    place "what does triggering a schedule actually do" is answered, not two
    that could drift apart. `initiated_by` only affects the audit_log row
    below — everything else about the run itself (its trigger='scheduled'
    session, the forced-Ask treatment that follows from that) is identical
    either way, per §26's own "no separate, more permissive code path."

    Returns False (and does nothing further) if the project this schedule
    points at can no longer be found. project_schedules cascades on
    projects' own deletion (0009_scheduling.sql), so this is a genuine
    orphan only if that invariant is somehow violated some other way — not
    expected, but cheaper to check than to assume can't happen and raise
    into the middle of a poll tick over it.

    Marks `last_run_at`/`last_session_id` on the schedule *before* calling
    start_turn, not after. start_turn spawns the real turn loop as a
    background asyncio task and returns as soon as the session's first
    message is durably logged — well before the loop itself actually
    finishes (a real run can take minutes). Waiting to mark the row until
    "after" would really mean "after the whole run finishes," during which
    a slow schedule sitting right at its own interval boundary could be
    picked up and triggered a second time by the very next poll tick.
    Marking it as soon as the session that represents this run definitely
    exists closes that window."""
    project = await projects_repo.get_by_id(schedule["project_id"])
    if project is None:
        return False

    session = await sessions_repo.create_for_project(
        project["user_id"],
        project["id"],
        title=f"Scheduled: {schedule['description'][:80]}",
        trigger="scheduled",
        schedule_id=schedule["id"],
    )
    if session is None:
        return False  # project vanished between get_by_id and here — vanishingly unlikely, not worth raising over

    ran_at = ran_at or datetime.datetime.now(datetime.timezone.utc)
    await schedules_repo.mark_run(schedule["id"], session["id"], ran_at)
    await audit_repo.record(
        project["user_id"],
        "schedule",
        "run_triggered",
        True,
        project_id=project["id"],
        session_id=session["id"],
        output_summary=schedule["description"][:200],
        initiated_by=initiated_by,
    )

    return await agent_loop.start_turn(session["id"], project["user_id"], schedule["description"])


def _parse_timestamp(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    # PostgREST (Supabase) returns a timestamptz as an ISO 8601 string with a
    # "Z" suffix; Python's fromisoformat wants an explicit "+00:00" offset on
    # the versions this codebase can't assume it's running on (3.11+ accepts
    # "Z" natively; older 3.10 doesn't) — normalized here the same way any
    # other raw-Supabase-row timestamp this codebase parses would need to be.
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
