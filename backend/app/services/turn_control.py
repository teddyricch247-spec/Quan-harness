"""
Stop a running turn (the Stop button).

The agent loop runs each turn as a background asyncio task (`agent_loop._spawn` -> `_run(session_id, user_id)`) and keeps no
handle to it, so there was nothing to cancel. This module finds that task from the outside — the task whose coroutine is
`agent_loop._run` and whose `session_id` argument is the session asked about — and cancels it. Nothing in agent_loop.py had to
change for this.

What cancelling means, honestly:
  * The model call (if one is in flight) is dropped; any live text on screen is cleared.
  * A tool that was running stops being waited for. A command already started inside the workspace may keep running there
    until it ends on its own; the loop just no longer waits for or records it.
  * The log is left as it was. A tool call with no result yet is exactly what the loop's own crash-recovery scan already
    handles on the next turn ("this step was interrupted before it could be confirmed complete"), so nothing new is needed.
  * Then this module writes one notice event ("You stopped this turn…"), sets the session to `completed` (the sessions table
    has no "stopped" status and a stopped turn is, to the loop, simply over) and broadcasts that, so every watcher's UI stops.

If agent_loop's `_run` is ever renamed or its arguments change, `find_turn_task` finds nothing and Stop answers "not running"
rather than guessing; tests/test_turn_control.py pins the names. The same lookup tells live_text which session a model call
belongs to (`session_of_current_turn`), so streaming does not depend on which code path started the turn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

logger = logging.getLogger(__name__)

TURN_COROUTINE_NAME = "_run"
TURN_MODULE_FILE = "services/agent_loop.py"
CANCEL_WAIT_SECONDS = 10.0

# Shown to the person AND read by the model on its next turn (the loop renders a stuck_notice to it as "[System] …"), so it
# is worded to make sense to both: it says who stopped the turn, and what that means for the work.
STOPPED_NOTICE = (
    "The person stopped this turn. Whatever it was in the middle of may be only partly done — check the files before continuing."
)


def _session_of_turn_task(task: asyncio.Task) -> str | None:
    """The session a task is running a turn for — the `session_id` argument of its `agent_loop._run` coroutine — or None if
    the task is anything else (including a child task the turn started, such as one lane of a parallel tool batch)."""
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    if code is None or code.co_name != TURN_COROUTINE_NAME:
        return None
    if not code.co_filename.replace("\\", "/").endswith(TURN_MODULE_FILE):
        return None
    frame = getattr(coro, "cr_frame", None)
    if frame is None:
        return None
    value = frame.f_locals.get("session_id")
    return value if isinstance(value, str) else None


def find_turn_task(session_id: str, tasks: Iterable[asyncio.Task] | None = None) -> asyncio.Task | None:
    """The running `agent_loop._run` task for this session, or None. `tasks` is injectable for tests."""
    for task in tasks if tasks is not None else asyncio.all_tasks():
        if not task.done() and _session_of_turn_task(task) == session_id:
            return task
    return None


def session_of_current_turn() -> str | None:
    """The session of the turn the CALLER is running inside (None outside a turn). This is how a model call knows whose screen
    to stream to without anything having to tell it: every way of starting a turn — a message, an interrupt, an approval, the
    first message of a new project, a scheduled run — ends up as an `agent_loop._run` task, and the call is made inside it."""
    try:
        task = asyncio.current_task()
    except RuntimeError:  # no event loop is running (a plain synchronous caller): certainly not inside a turn
        return None
    return _session_of_turn_task(task) if task is not None else None


async def cancel_and_wait(task: asyncio.Task, timeout: float = CANCEL_WAIT_SECONDS) -> bool:
    """Cancel `task` and wait for it to actually finish. False if it is still running after `timeout`."""
    task.cancel()
    await asyncio.wait({task}, timeout=timeout)
    await asyncio.sleep(0)  # let the loop's own done-callbacks (which release the session's claim) run
    return task.done()


async def stop_turn(session_id: str, user_id: str) -> str:
    """'stopped' | 'not_running' | 'not_found' | 'not_stopped'."""
    from app.repositories import sessions as sessions_repo
    from app.services import agent_loop, live_text

    session = await sessions_repo.get_owned(user_id, session_id)
    if session is None:
        return "not_found"
    task = find_turn_task(session_id)
    if task is None:
        return "not_running"
    if not await cancel_and_wait(task):
        logger.error("session %s: the turn did not stop within %ss of being cancelled", session_id, CANCEL_WAIT_SECONDS)
        return "not_stopped"
    live_text.registry.reset(session_id)
    await agent_loop._append(session_id, "system", "stuck_notice", {"text": STOPPED_NOTICE, "severity": "soft"})  # noqa: SLF001
    await sessions_repo.update_fields(session_id, {"status": "completed"})
    agent_loop._broadcast_done(session_id, "completed")  # noqa: SLF001 — ends every watcher's stream, like any finished turn
    return "stopped"
