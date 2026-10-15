"""
Phase Convert (C8.3) — what makes the red dot on a tab, as pure functions over session rows.

The shell polls GET /attention to answer one question: "does the *other* surface need me?" In
Convert only Code reports anything (Chat's counts are always zero until Phase 8), and the two things
that count are exactly the ones the spec names — a session waiting on an approval, and a turn that
failed.

A *failed* count has to stop at some point or the dot would stay red forever over a session the
person has already given up on. There is no "acknowledged" column to clear (and this phase adds no
migration), so a failure counts only while it is recent and only while it is still the session's
latest state: re-opening the session and running another turn changes its status and clears it
naturally; a failure nobody touches ages out after FAILED_WINDOW_HOURS. That window is a product
decision made here, not in the spec — change the constant to change it.

Pure: no imports from the rest of the app, so it is testable without a database.
"""
from datetime import datetime, timedelta, timezone

FAILED_WINDOW_HOURS = 24
FAILED_STATUSES = ("failed", "stuck")


def _parse(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def count_attention(sessions: list[dict], now: datetime | None = None) -> dict[str, int]:
    """`sessions` — rows with at least `status` and `updated_at`. Archived sessions never count."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FAILED_WINDOW_HOURS)
    waiting = 0
    failed = 0
    for row in sessions:
        status = row.get("status")
        if status == "archived":
            continue
        if status == "waiting_approval":
            waiting += 1
        elif status in FAILED_STATUSES:
            updated = _parse(row.get("updated_at"))
            if updated is not None and updated >= cutoff:
                failed += 1
    return {"waiting_approval": waiting, "failed": failed}


def summarize_project_sessions(sessions: list[dict]) -> dict:
    """One project's `status` and `last_activity_at` for GET /projects (C8.2).

    status: 'waiting_approval' beats 'running' beats 'idle' — if any session needs the person, that
    is what the list should say. last_activity_at is the newest `updated_at` across the project's
    sessions (agent_loop stamps it on every status change), or None for a project with no sessions.
    """
    status = "idle"
    latest: datetime | None = None
    for row in sessions:
        row_status = row.get("status")
        if row_status == "archived":
            continue
        if row_status == "waiting_approval":
            status = "waiting_approval"
        elif row_status == "running" and status != "waiting_approval":
            status = "running"
        updated = _parse(row.get("updated_at"))
        if updated is not None and (latest is None or updated > latest):
            latest = updated
    return {"status": status, "last_activity_at": latest}
