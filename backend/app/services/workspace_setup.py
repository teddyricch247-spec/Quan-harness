"""
Phase Convert (C8.5) — kicking workspace provisioning off at project creation, and remembering how
it went, so the "Setting up your project" card reads a status instead of guessing from timers.

Provisioning itself is unchanged: `workspace_service.ensure_workspace` creates the Sprite behind a
project and writes its real handle over the `pending-…` stub. Before this phase that happened
lazily, on the first tool call. Convert's flow wants it to *start* the moment a project is created
(Flow B step 3) so it is usually done by the time the agent needs it — nothing blocks on it, and if
it loses a race with the agent's own first call, both converge on the same Sprite: the name is
derived from the project id, `ensure_workspace` treats a conflict-shaped create error as success, and
its `git init` step is idempotent. One caveat: that conflict detection is substring matching on the
provider's error text ("exist", "taken", "conflict", "409"), so if the Sprites API ever words it
differently the *loser* of the race raises. That is harmless here — whichever caller won has already
written the real handle, and `status_for` reports "ready" from the database regardless of what this
module remembers — but an agent tool call that loses would surface it as a tool error and retry.

The record of an attempt is in-process only. That is deliberate: a persisted status would be a
migration, and Convert adds none. The consequences are small and stated: after a backend restart a
project that never finished provisioning reports "idle" rather than "failed", and the card falls
back to the Retry action it offers anyway (POST /projects/{id}/workspace/wake, which is
`ensure_workspace` plus a no-op command). A project whose Sprite handle is real is "ready"
regardless of what this module remembers — the database, not this dict, is the source of truth for
"is it provisioned".
"""
import asyncio
import logging

from app.services import workspace_service

logger = logging.getLogger(__name__)

# project_id -> {"status": "provisioning" | "failed", "error": str | None}. Entries are removed on
# success (the handle in the database then speaks for itself).
_attempts: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()  # strong refs so a fire-and-forget task isn't garbage-collected


def status_for(workspace_row: dict | None, project_id: str) -> tuple[str, str | None]:
    """(workspace_status, workspace_error) for ProjectOut. `workspace_row` is the
    project_workspaces row (or None)."""
    if workspace_row is not None and not str(workspace_row.get("sprite_handle", "")).startswith("pending-"):
        return "ready", None
    attempt = _attempts.get(project_id)
    if attempt is not None:
        return attempt["status"], attempt.get("error")
    return "idle", None


def kick_off(project_id: str) -> None:
    """Start provisioning in the background. Safe to call twice — a second call while one is in
    flight does nothing. Must be called from inside a running event loop (a request handler)."""
    existing = _attempts.get(project_id)
    if existing is not None and existing["status"] == "provisioning":
        return
    _attempts[project_id] = {"status": "provisioning", "error": None}
    task = asyncio.create_task(_run(project_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(project_id: str) -> None:
    try:
        await workspace_service.ensure_workspace(project_id)
    except Exception as exc:  # noqa: BLE001 — a provisioning failure is a status, never a crash
        logger.warning("workspace provisioning failed for project %s: %s", project_id, exc)
        _attempts[project_id] = {"status": "failed", "error": str(exc)[:500]}
    else:
        _attempts.pop(project_id, None)


def forget(project_id: str) -> None:
    """Drop whatever is remembered about a project (it was deleted, or its setup was rolled back)."""
    _attempts.pop(project_id, None)
