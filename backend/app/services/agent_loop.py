"""
§16 — The Agent Orchestration Loop. Implementation order step 9/10.

This is the I/O shell that wires together every pure module this phase adds:
system_prompt (§18), repo_map/compaction (§17), tool_schemas/mcp_tools (§9.4),
message_builder (§17 item 6), stuck_detector (§19), tool_partition/
crash_recovery (§16.2/§16.4). Each of those is unit-tested on its own —
nothing here has run against a real database, workspace, or LLM credential in
the sandbox this was built in (no network — see /docs/PHASE3_NOTES.md), so
treat this module as reviewed-and-reasoned-through rather than proven.

ENTRY POINTS (called by app/routers/agent.py):
  start_turn(session_id, user_id, text)       -- a fresh user message
  send_interrupt(session_id, user_id, text)   -- mid-run steering (§16.2)
  resume_after_approval(session_id, user_id)  -- after an Ask-gate resolves
  subscribe(session_id) / unsubscribe(...)    -- SSE fan-out

All three "start something running" entry points converge on the same
private `_run(session_id, user_id)`, run as a background asyncio task — a
fresh user message, a resumed-after-crash session, and a resumed-after-
approval session are all "take a new turn on this session," and §16.4's own
crash-recovery scan is written to run "on any session resume, before taking a
new turn," not only after a literal process crash. Treating all three
identically is what makes that scan meaningful instead of a special case.

DESIGN DECISIONS NOT SPELLED OUT VERBATIM IN THE SPEC EXCERPT (see
/docs/PHASE3_NOTES.md for the fuller writeup of each):
  - Checkpoint creation is NOT triggered from here. file_tools.py/
    shell_tools.py already create one, unconditionally, inside str_replace/
    create_file/execute_bash themselves (Phase 2). §16.2's pseudocode line
    `create_checkpoint_if_dirty(workspace)` describes behavior Phase 2 already
    delivers; calling checkpoints.create_checkpoint() again here would create
    a duplicate commit per edit.
  - An approved execute_bash re-run calls shell_tools.execute_bash(...,
    bypass_guard=True) — added this phase — rather than re-running the normal
    path, which would re-trip the same guard rule on the same unchanged
    command text and make the approval a no-op.
  - Tool_call events for a whole batch are appended contiguously (all of a
    response's calls, read-only and mutating together) as soon as they're
    known, in the model's own order; their tool_result events are appended as
    each call finishes, which can interleave with later tool_call events
    (message_builder.py's grouping tolerates this — see its own docstring).
    This is so a live SSE viewer sees each result as soon as it's ready
    rather than a long silent gap while a whole batch executes.
  - A call after an Ask-gated one in the same response is never recorded at
    all (no tool_call event), not recorded-then-abandoned — §16.2 says these
    are "discarded, not queued," and never persisting them avoids a
    permanently-dangling event future crash-recovery scans would otherwise
    keep tripping over.
  - `is_read_only` on a bash/native call is a fixed per-tool-name property
    (tool_partition.py); nothing here inspects execute_bash's command text to
    guess read-only-ness, matching §16.2's own explicit reasoning.
"""
import asyncio
import datetime
from dataclasses import dataclass

from app.repositories import approval_requests as approval_requests_repo
from app.repositories import audit as audit_repo
from app.repositories import mcp_servers as mcp_servers_repo
from app.repositories import project_secrets as project_secrets_repo
from app.repositories import projects as projects_repo
from app.repositories import session_events as session_events_repo
from app.repositories import sessions as sessions_repo
from app.services import (
    compaction,
    crash_recovery,
    file_tools,
    llm_client,
    mcp_tools,
    message_builder,
    repo_map,
    shell_tools,
    stuck_detector,
    system_prompt,
    tool_partition,
    tool_schemas,
)

MAX_ITERATION_SAFETY_DEFAULT = 50  # falls back to this only if project.max_turn_iterations is somehow missing

# ---------------------------------------------------------------------------
# In-memory registry: which sessions have a loop running right now, and who's
# listening for their events over SSE. Both are per-process and intentionally
# not durable — §16.4's whole point is that the durable event log is the
# source of truth, so losing this registry (a restart) loses nothing but the
# "is a task literally running this millisecond" bookkeeping and any
# mid-stream SSE connections, which reconnect and catch up from the log.
# ---------------------------------------------------------------------------
_running_sessions: set[str] = set()
_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe(session_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(session_id, []).append(queue)
    return queue


def unsubscribe(session_id: str, queue: asyncio.Queue) -> None:
    listeners = _subscribers.get(session_id)
    if listeners and queue in listeners:
        listeners.remove(queue)
        if not listeners:
            _subscribers.pop(session_id, None)


def is_running(session_id: str) -> bool:
    return session_id in _running_sessions


def _claim_session(session_id: str) -> bool:
    """Atomically marks a session as running, returning False if it already
    was. Deliberately synchronous with no `await` inside it: Python's
    cooperative scheduler only ever switches to another task at an `await`
    point, so a check-then-set with no `await` between them can't race
    against another coroutine doing the same thing, even for the same
    session_id. This matters because the three entry points below each need
    an `await` (to fetch the session, to durably log the incoming message)
    between deciding "is anything already running" and actually starting a
    loop — checking is_running() at the top and calling _spawn() several
    awaits later, as an earlier version of this file did, leaves exactly
    that gap open: two near-simultaneous requests for the same session could
    both see 'not running' and both end up spawning a turn loop. Claiming
    the session here, before the first await, closes it; `_release_session`
    is the counterpart for every path that decides not to actually spawn
    after claiming."""
    if session_id in _running_sessions:
        return False
    _running_sessions.add(session_id)
    return True


def _release_session(session_id: str) -> None:
    _running_sessions.discard(session_id)


def _broadcast(session_id: str, event: dict) -> None:
    for queue in list(_subscribers.get(session_id, [])):
        queue.put_nowait(event)


def _broadcast_done(session_id: str, status: str) -> None:
    _broadcast(session_id, {"event_type": "__session_status__", "status": status})


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def start_turn(session_id: str, user_id: str, text: str) -> bool:
    """A fresh message into a session. Returns False (and does nothing) if the
    session is read-only or a loop is already running on it — the router
    surfaces that as a plain 409, not a silent drop."""
    if not _claim_session(session_id):
        return False
    try:
        session = await sessions_repo.get_owned(user_id, session_id)
        if session is None or session["read_only"]:
            _release_session(session_id)
            return False
        await session_events_repo.append(session_id, role="user", event_type="message", content={"text": text})
    except BaseException:
        # Anything going wrong between claiming and actually spawning (a DB
        # error included) must release the claim — otherwise this session
        # would be permanently stuck "running" with no task ever actually
        # started, unable to ever start a turn again. The explicit release
        # above, on the plain not-found/read-only return, is needed for
        # exactly the same reason — that path returns normally rather than
        # raising, so it would otherwise slip past this except entirely.
        _release_session(session_id)
        raise
    _spawn(session_id, user_id)
    return True


async def send_interrupt(session_id: str, user_id: str, text: str) -> bool:
    """§16.2 mid-run steering. Durably appended either way — if a loop is
    currently running, it picks this up the next time it re-reads the event
    log (every iteration, before the next call_llm — see module docstring on
    why no separate in-memory interrupt channel is needed for correctness).
    If nothing is running, this starts one, the same as any other message."""
    session = await sessions_repo.get_owned(user_id, session_id)
    if session is None or session["read_only"]:
        return False
    await session_events_repo.append(session_id, role="user", event_type="user_interrupt", content={"text": text})
    if _claim_session(session_id):
        _spawn(session_id, user_id)
    return True


async def resume_after_approval(session_id: str, user_id: str) -> bool:
    if not _claim_session(session_id):
        return False
    try:
        session = await sessions_repo.get_owned(user_id, session_id)
    except BaseException:
        _release_session(session_id)
        raise
    if session is None or session["read_only"]:
        _release_session(session_id)
        return False
    _spawn(session_id, user_id)
    return True


def _spawn(session_id: str, user_id: str) -> None:
    """Only ever called immediately after a successful `_claim_session` for
    the same session_id — does not claim it itself."""
    task = asyncio.create_task(_run(session_id, user_id))
    task.add_done_callback(lambda _t: _release_session(session_id))


# ---------------------------------------------------------------------------
# Event log helpers
# ---------------------------------------------------------------------------


async def _append(session_id: str, role: str, event_type: str, content: dict, parent_event_id: int | None = None) -> dict:
    event = await session_events_repo.append(session_id, role, event_type, content, parent_event_id)
    _broadcast(session_id, event)
    return event


def _reconstruct_viewed_paths(events: list[dict]) -> set[str]:
    """§14.2: 'every path seen in a tool_call/tool_result event this
    session' — file_tools.py's own docstring names this exact reconstruction.
    A create_file also counts (see module docstring's file_tools.py note) so
    a freshly created file can be edited without an extra round-trip view."""
    viewed = set()
    for event in events:
        if event["event_type"] != "tool_call":
            continue
        content = event["content"]
        if content.get("name") in ("view_file", "create_file"):
            path = content.get("arguments", {}).get("path")
            if path:
                viewed.add(path)
    return viewed


def _extract_keywords(events: list[dict]) -> list[str]:
    """Cheap keyword extraction for repo_map's ranking — the most recent
    user-authored text (a message or an interrupt), lowercased, split on
    non-alphanumerics, short/common words dropped. Not NLP; just enough to
    bias the repo map toward files whose names/signatures share vocabulary
    with what the person actually asked for."""
    import re

    stopwords = {
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
        "is", "are", "it", "this", "that", "with", "as", "be", "at", "by",
    }
    text = ""
    for event in reversed(events):
        if event["event_type"] in ("message", "user_interrupt") and event["role"] == "user":
            text = event["content"].get("text", "")
            break
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in stopwords]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


@dataclass
class ExecutionOutcome:
    ok: bool
    content: str = ""
    error: str = ""
    checkpoint_id: str | None = None
    needs_approval: bool = False
    guard_reason: str | None = None


async def _execute_native(
    project_id: str,
    session_id: str,
    user_id: str,
    name: str,
    arguments: dict,
    viewed_paths: set[str],
    session: dict,
    conversation_snapshot: list | None = None,
) -> ExecutionOutcome:
    if name == "view_file":
        result = await file_tools.view_file(project_id, arguments.get("path", ""), _as_range(arguments.get("view_range")))
        if result.ok:
            viewed_paths.add(arguments.get("path", ""))
        return ExecutionOutcome(ok=result.ok, content=result.content, error=result.error or "")

    if name == "str_replace":
        path = arguments.get("path", "")
        try:
            result = await file_tools.str_replace(
                project_id,
                path,
                arguments.get("old_str", ""),
                arguments.get("new_str", ""),
                viewed_paths,
                session_id,
                conversation_snapshot,
            )
        except file_tools.PathNotViewedError as exc:
            return ExecutionOutcome(ok=False, error=str(exc))
        text = result.content
        if result.syntax_check:
            text += f"\n\n[syntax check] {result.syntax_check}"
        return ExecutionOutcome(ok=result.ok, content=text, error=result.error or "", checkpoint_id=result.checkpoint_id)

    if name == "create_file":
        path = arguments.get("path", "")
        result = await file_tools.create_file(
            project_id, path, arguments.get("file_text", ""), session_id, conversation_snapshot
        )
        if result.ok:
            viewed_paths.add(path)
        text = result.content
        if result.syntax_check:
            text += f"\n\n[syntax check] {result.syntax_check}"
        return ExecutionOutcome(ok=result.ok, content=text, error=result.error or "", checkpoint_id=result.checkpoint_id)

    if name == "execute_bash":
        timeout = _safe_int(arguments.get("timeout_seconds"), default=120)
        bash_result = await shell_tools.execute_bash(
            project_id,
            session_id,
            user_id,
            arguments.get("command", ""),
            timeout,
            conversation_snapshot=conversation_snapshot,
        )
        if bash_result.needs_approval:
            return ExecutionOutcome(ok=False, needs_approval=True, guard_reason=bash_result.guard_reason)
        return ExecutionOutcome(
            ok=bash_result.exit_code == 0,
            content=f"exit {bash_result.exit_code}\nstdout:\n{bash_result.stdout}\nstderr:\n{bash_result.stderr}",
            checkpoint_id=bash_result.checkpoint_id,
        )

    if name == "run_lint":
        bash_result = await shell_tools.run_lint(project_id)
        return ExecutionOutcome(
            ok=bash_result.exit_code == 0, content=f"exit {bash_result.exit_code}\n{bash_result.stdout}\n{bash_result.stderr}"
        )

    if name == "run_tests":
        bash_result = await shell_tools.run_tests(project_id, arguments.get("test_path"))
        return ExecutionOutcome(
            ok=bash_result.exit_code == 0, content=f"exit {bash_result.exit_code}\n{bash_result.stdout}\n{bash_result.stderr}"
        )

    if name == "update_plan":
        steps = arguments.get("steps", [])
        updated = await sessions_repo.update_fields(session_id, {"plan": steps})
        session["plan"] = updated.get("plan", steps)  # kept in sync in-place so the next iteration's CURRENT_PLAN reflects it
        rendered = system_prompt.format_current_plan(steps) or "(empty plan)"
        return ExecutionOutcome(ok=True, content=f"Plan updated:\n{rendered}")

    return ExecutionOutcome(ok=False, error=f"Unknown native tool: {name}")


def _as_range(value) -> tuple[int, int] | None:
    if not value or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _safe_int(value, default: int) -> int:
    """Tool arguments come straight from the model's JSON tool call — a
    schema-compliant caller sends a real integer for `timeout_seconds`, but
    nothing enforces that at this boundary, and `shell_tools.execute_bash`'s
    `min(max(timeout_seconds, 1), ...)` would raise on a string or None
    rather than degrade gracefully. Coerced here rather than in
    shell_tools.py itself, which already has real Phase 2 test coverage
    assuming a real int comes in."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _execute_mcp(tool: tool_schemas.MergedMcpTool, arguments: dict) -> ExecutionOutcome:
    from app.services import vault

    auth_token = await vault.read_secret(tool.auth_token_ref) if tool.auth_token_ref else None
    result = await mcp_tools.call_tool(tool, arguments, auth_token)
    return ExecutionOutcome(ok=result.ok, content=result.content, error=result.error or "")


async def _execute_call_inner(
    project_id: str,
    session_id: str,
    user_id: str,
    name: str,
    arguments: dict,
    viewed_paths: set[str],
    merged_mcp: tool_schemas.MergedToolSchema,
    session: dict,
    conversation_snapshot: list | None = None,
) -> ExecutionOutcome:
    if name.startswith("mcp__"):
        tool = merged_mcp.by_model_name().get(name)
        if tool is None:
            return ExecutionOutcome(ok=False, error=f"{name} is not available to this project right now.")
        return await _execute_mcp(tool, arguments)
    return await _execute_native(project_id, session_id, user_id, name, arguments, viewed_paths, session, conversation_snapshot)


# Argument fields never worth writing into audit_log's input payload — a
# file's full before/after content, which can be arbitrarily large and is
# already captured verbatim in session_events (§27 draws that exact
# distinction: audit_log wants "what input" as a record, session_events is
# "the literal transcript"). Excluded by name rather than by tool, so a
# future native tool with its own large-content argument is covered without
# this needing an update.
_AUDIT_EXCLUDED_ARG_FIELDS = frozenset({"old_str", "new_str", "file_text"})


def _audit_input_payload(name: str, arguments: dict) -> dict:
    if name.startswith("mcp__"):
        # A connector tool's arguments are opaque to this codebase and could
        # carry a connector-specific secret-shaped value — record which
        # arguments were sent, not their values, the same conservative
        # default _resolve_permission_for_call takes for a connector tool's
        # permission state.
        return {"argument_keys": sorted(arguments.keys())}
    return {k: v for k, v in arguments.items() if k not in _AUDIT_EXCLUDED_ARG_FIELDS}


# audit_log.tool is a *category*, not a tool name — 0005_sessions.sql's own
# column comment documents the vocabulary ('bash' | 'file_edit' | 'web_search'
# | 'browser' | 'delegate_task' | 'mcp:<server_name>' | ...), and
# shell_tools.execute_bash already writes its rows as tool='bash',
# action='execute_bash'. Every row this file writes follows that same shape:
# `tool` = the category, `action` = the specific tool name within it, so a
# filter on one category ("everything that touched a file", "everything a
# given connector did") works across every writer, not just this one.
#
#   view_file / str_replace / create_file  -> 'file_edit'  (a read is grouped
#       with edits deliberately: the vocabulary has no separate read category,
#       and "which files did the agent touch" is one question, not two)
#   run_lint / run_tests                   -> 'bash'  (they run through the same
#       exec_in_workspace primitive execute_bash does — see PHASE3_NOTES.md)
#   update_plan                            -> 'plan'  (added to the vocabulary
#       for this; 0005's comment was updated to match)
#   mcp__<server>__<tool>                  -> 'mcp:<server_name>'
_NATIVE_AUDIT_CATEGORY = {
    "view_file": "file_edit",
    "str_replace": "file_edit",
    "create_file": "file_edit",
    "run_lint": "bash",
    "run_tests": "bash",
    "update_plan": "plan",
}


def _audit_labels(name: str, mcp_tool: tool_schemas.MergedMcpTool | None) -> tuple[str, str]:
    """(tool, action) for one audit_log row. `mcp_tool` is the resolved
    connector tool when `name` is an mcp__ name that's actually available to
    this project; None otherwise. A name that maps to nothing still gets a row
    (a hallucinated tool name, or a connector tool that's no longer granted, is
    exactly the kind of thing §27's "regardless of outcome" is for) — just under
    a category that says so, rather than being silently dropped or misfiled."""
    if name.startswith("mcp__"):
        if mcp_tool is not None:
            return f"mcp:{mcp_tool.server_name}", mcp_tool.real_tool_name
        return "mcp:unavailable", name
    return _NATIVE_AUDIT_CATEGORY.get(name, "unknown"), name


async def _record_tool_audit(
    user_id: str,
    project_id: str,
    session_id: str,
    name: str,
    arguments: dict,
    outcome: ExecutionOutcome,
    mcp_tool: tool_schemas.MergedMcpTool | None = None,
) -> None:
    """The one place this file writes an audit_log row — shared by
    `_execute_call` (every ordinary tool call) and `_action_resolved_approval`'s
    connector branch (the one path that executes a tool outside
    `_execute_call`), so the two can't drift apart in labelling or payload."""
    tool, action = _audit_labels(name, mcp_tool)
    await audit_repo.record(
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        tool=tool,
        action=action,
        success=outcome.ok,
        input_payload=_audit_input_payload(name, arguments),
        output_summary=(outcome.error[:500] or None) if not outcome.ok else None,
        initiated_by="agent",
    )


async def _execute_call(
    project_id: str,
    session_id: str,
    user_id: str,
    name: str,
    arguments: dict,
    viewed_paths: set[str],
    merged_mcp: tool_schemas.MergedToolSchema,
    session: dict,
    conversation_snapshot: list | None = None,
) -> ExecutionOutcome:
    """§27: "audit_log... the complete record of everything that happened,
    across every tool, regardless of outcome." `_execute_call` is the one
    chokepoint every real tool execution passes through — the normal turn
    loop below and §16.4's crash-recovery re-execution both call it, nothing
    calls `_execute_native`/`_execute_mcp` directly — so instrumenting here
    once covers every caller rather than threading an audit_repo.record call
    into each of view_file/str_replace/create_file/run_lint/run_tests/
    update_plan/every mcp__ tool individually. A tool added in a later phase
    is audited by default, with a category of 'unknown' until it's added to
    `_NATIVE_AUDIT_CATEGORY` above.

    execute_bash is the one exception, deliberately skipped here:
    shell_tools.execute_bash already writes its own audit_log row —
    including the guard-blocked case, before this function is even in a
    position to see an outcome — so auditing it again here would double the
    row for the exact same call. See shell_tools.py's own comment on that
    call for why it has to happen inside execute_bash rather than at a
    caller like this one.

    If the underlying call raises, no row is written (the exception
    propagates to the turn loop, which records the failure as its own
    transcript event) — same behavior as before this labelling change; it was
    deliberately not widened here."""
    outcome = await _execute_call_inner(
        project_id, session_id, user_id, name, arguments, viewed_paths, merged_mcp, session, conversation_snapshot
    )
    if name != "execute_bash":
        mcp_tool = merged_mcp.by_model_name().get(name) if name.startswith("mcp__") else None
        await _record_tool_audit(user_id, project_id, session_id, name, arguments, outcome, mcp_tool)
    return outcome


# ---------------------------------------------------------------------------
# Fetching project-scoped data the loop needs each round
# ---------------------------------------------------------------------------


async def _fetch_merged_tool_schema(user_id: str, project_id: str) -> tool_schemas.MergedToolSchema:
    granted_ids = set(await projects_repo.get_connector_access(project_id))
    if not granted_ids:
        return tool_schemas.MergedToolSchema()
    all_servers = await mcp_servers_repo.list_for_user(user_id)
    servers = [s for s in all_servers if s["id"] in granted_ids and s.get("enabled")]
    overrides_by_server: dict[str, dict[str, str]] = {}
    for server in servers:
        rows = await mcp_servers_repo.list_overrides(server["id"])
        overrides_by_server[server["id"]] = {r["tool_name"]: r["permission_state"] for r in rows}
    return tool_schemas.merge_mcp_tools(servers, overrides_by_server)


async def _fetch_secret_names(user_id: str, project_id: str) -> list[str]:
    rows = await project_secrets_repo.list_for_project(user_id, project_id)
    return [r["name"] for r in rows] if rows else []


def _resolve_permission_for_call(name: str, merged: tool_schemas.MergedToolSchema) -> str:
    """Native tools have no stored permission_state at all — execute_bash's
    own guard result at call time IS its Ask signal (§16.2: 'never something
    the model reports about itself'); str_replace/create_file/run_lint/
    run_tests/update_plan are always Auto. Only an mcp__ tool consults the
    merged schema's resolved state."""
    if name.startswith("mcp__"):
        return merged.permission_state_by_name().get(name, "ask")  # missing == treat cautiously, not silently Auto
    return "auto"


# ---------------------------------------------------------------------------
# The loop itself
# ---------------------------------------------------------------------------


async def _run(session_id: str, user_id: str) -> None:
    try:
        await _run_inner(session_id, user_id)
    except llm_client.NoLlmCredentialError as exc:
        await _append(session_id, "system", "error", {"text": str(exc)})
        await sessions_repo.update_fields(session_id, {"status": "failed"})
        _broadcast_done(session_id, "failed")
    except Exception as exc:  # noqa: BLE001 — never let an unhandled exception leave a session stuck at 'running' forever
        await _append(
            session_id,
            "system",
            "error",
            {"text": f"Internal error: {exc}. This session's status has been reset to failed; check the server logs."},
        )
        await sessions_repo.update_fields(session_id, {"status": "failed"})
        _broadcast_done(session_id, "failed")


async def _run_inner(session_id: str, user_id: str) -> None:
    session = await sessions_repo.get_owned(user_id, session_id)
    if session is None or session["read_only"]:
        return
    project = await projects_repo.get_by_id(session["project_id"])
    if project is None:
        return

    events = await session_events_repo.list_for_session(session_id)

    # --- §16.4: crash recovery / resume scan, on every entry, not only after
    # a literal process restart (see module docstring). Approval_request
    # dangling entries are handled separately below, against the
    # approval_requests row's real status, not just the event log — see
    # /docs/PHASE3_NOTES.md for why the event-log-only signal isn't enough
    # to tell "still pending" apart from "resolved but not yet actioned."
    dangling_events = crash_recovery.find_dangling_events(events)
    for dangling in dangling_events:
        if dangling.kind == "pending_approval":
            continue
        call_content = dangling.event["content"]
        if dangling.kind == "reexecute":
            merged = await _fetch_merged_tool_schema(user_id, project["id"])
            viewed_paths = _reconstruct_viewed_paths(events)
            outcome = await _execute_call(
                project["id"],
                session_id,
                user_id,
                call_content["name"],
                call_content["arguments"],
                viewed_paths,
                merged,
                session,
                conversation_snapshot=events,
            )
            await _append(
                session_id,
                "system",
                "tool_result",
                {"ok": outcome.ok, "content": outcome.content, "error": outcome.error, "checkpoint_id": outcome.checkpoint_id},
                parent_event_id=dangling.event["id"],
            )
        else:  # "interrupted"
            await _append(
                session_id,
                "system",
                "tool_result",
                {
                    "ok": False,
                    "content": "",
                    "error": "This step was interrupted before it could be confirmed complete — "
                    "it may have partially run. Check the current state before retrying.",
                    "checkpoint_id": None,
                },
                parent_event_id=dangling.event["id"],
            )
    if any(d.kind != "pending_approval" for d in dangling_events):
        events = await session_events_repo.list_for_session(session_id)

    # --- Ask-gate resolution: the approval_requests row is the source of
    # truth for "resolved," not the event log (see comment above).
    latest_approval = await approval_requests_repo.get_pending_for_session(session_id)
    if latest_approval is not None:
        # Still genuinely pending — nothing to do until the person resolves it.
        await sessions_repo.update_fields(session_id, {"status": "waiting_approval"})
        return

    approval_event = _find_unactioned_resolved_approval(events)
    if approval_event is not None:
        await _action_resolved_approval(session, project, user_id, approval_event, events)
        events = await session_events_repo.list_for_session(session_id)

    # --- Fresh turn loop starts here (§16.2/§16.3/§16.4: a resumed session
    # after either kind of pause is, deliberately, "a fresh turn loop").
    await sessions_repo.update_fields(session_id, {"status": "running", "turn_iteration_count": 0})

    credential = await llm_client.resolve_credential(project)
    context_window = llm_client.get_context_window(credential)
    viewed_paths = _reconstruct_viewed_paths(events)
    max_iterations = project.get("max_turn_iterations") or MAX_ITERATION_SAFETY_DEFAULT
    turn_iteration_count = 0
    already_soft_nudged_this_turn = False
    already_nudged_lint_this_turn = False
    turn_stuck_events: list[stuck_detector.StuckEvent] = []
    step = 0
    last_input_tokens: int | None = None  # the real count the provider reported for the previous call_llm, if any

    while True:
        events = await session_events_repo.list_for_session(session_id)
        events = message_builder.apply_condensation(events)

        # §17.1 compaction, checked before every call_llm. Uses the real
        # token count the provider reported for the previous call
        # (`last_input_tokens`, from `response.usage`) whenever one's
        # available — far more accurate than estimating from re-stringified
        # event content, and litellm already hands this back for free. Only
        # falls back to the crude character-based estimate
        # (token_estimate.py) for the very first call_llm of this turn loop,
        # before any real number exists yet, or for a provider that never
        # reports usage at all.
        if last_input_tokens is not None:
            approx_tokens = last_input_tokens
        else:
            message_texts = [str(e.get("content", {})) for e in events]
            approx_tokens = sum(compaction.estimate_tokens(t) for t in message_texts)
        if compaction.should_compact(approx_tokens, context_window):
            await _run_compaction(session_id, credential, events)
            events = await session_events_repo.list_for_session(session_id)
            events = message_builder.apply_condensation(events)
            last_input_tokens = None  # the message list just changed shape — the old count no longer applies

        merged_mcp = await _fetch_merged_tool_schema(user_id, project["id"])
        repo_context = await repo_map.build_repo_map(
            project["id"], opened_paths=viewed_paths, task_keywords=_extract_keywords(events)
        )
        secret_names = await _fetch_secret_names(user_id, project["id"])
        dynamic = system_prompt.DynamicSections(
            repo_context=repo_context,
            current_datetime=system_prompt.format_current_datetime(datetime.datetime.now(datetime.timezone.utc)),
            current_plan=system_prompt.format_current_plan(session.get("plan") or []),
            project_secrets=system_prompt.format_project_secrets(secret_names),
        )
        system_text = system_prompt.assemble(dynamic)
        tools = tool_schemas.build_full_tool_list(merged_mcp)
        messages = message_builder.build_messages(system_text, events)

        try:
            response = await llm_client.call_llm(messages, tools, credential)
        except llm_client.LlmCallFailedError as exc:
            await _append(
                session_id,
                "system",
                "error",
                {
                    "text": f"The turn ended because {credential.provider}/{credential.model} kept failing: {exc}. "
                    "Check Connections → LLM Providers."
                },
            )
            await sessions_repo.update_fields(session_id, {"status": "failed"})
            _broadcast_done(session_id, "failed")
            return

        step += 1
        last_input_tokens = response.input_tokens or last_input_tokens

        if not response.tool_calls:
            if not already_nudged_lint_this_turn and await _workspace_has_uncommitted_changes(project["id"]):
                already_nudged_lint_this_turn = True
                if response.text:
                    await _append(session_id, "agent", "message", {"text": response.text, "step": step})
                await _append(
                    session_id,
                    "system",
                    "stuck_notice",
                    {
                        "text": "You have unsaved code changes but haven't run run_lint or run_tests yet this "
                        "turn. Run them before finishing, or explain why verification doesn't apply to this change.",
                        "severity": "soft",
                    },
                )
                continue
            if response.text:
                await _append(session_id, "agent", "message", {"text": response.text, "step": step})
            await sessions_repo.update_fields(session_id, {"status": "completed"})
            _broadcast_done(session_id, "completed")
            return

        if response.text:
            await _append(session_id, "agent", "message", {"text": response.text, "step": step})

        side_effect_free = merged_mcp.side_effect_free_by_name()
        read_only_calls, mutating_calls = tool_partition.partition(response.tool_calls, side_effect_free)

        # --- read-only batch: appended contiguously, executed concurrently ---
        read_only_events = []
        for call in read_only_calls:
            event = await _append(
                session_id,
                "agent",
                "tool_call",
                {"step": step, "call_id": call.id, "name": call.name, "arguments": call.arguments, "read_only": True},
            )
            read_only_events.append(event)

        if read_only_calls:
            outcomes = await asyncio.gather(
                *[
                    _execute_call(
                        project["id"],
                        session_id,
                        user_id,
                        call.name,
                        call.arguments,
                        viewed_paths,
                        merged_mcp,
                        session,
                        conversation_snapshot=events,
                    )
                    for call in read_only_calls
                ]
            )
            for call, event, outcome in zip(read_only_calls, read_only_events, outcomes):
                await _append(
                    session_id,
                    "system",
                    "tool_result",
                    {"ok": outcome.ok, "content": outcome.content, "error": outcome.error, "checkpoint_id": outcome.checkpoint_id},
                    parent_event_id=event["id"],
                )
                turn_stuck_events.append(_to_stuck_event(call, outcome))

        # --- mutating batch: sequential, one at a time, gate-aware ---
        for call in mutating_calls:
            permission_state = _resolve_permission_for_call(call.name, merged_mcp)

            if call.name == "execute_bash" or permission_state != "ask":
                call_event = await _append(
                    session_id,
                    "agent",
                    "tool_call",
                    {"step": step, "call_id": call.id, "name": call.name, "arguments": call.arguments, "read_only": False},
                )
                outcome = await _execute_call(
                    project["id"],
                    session_id,
                    user_id,
                    call.name,
                    call.arguments,
                    viewed_paths,
                    merged_mcp,
                    session,
                    conversation_snapshot=events,
                )
                if outcome.needs_approval:
                    approval_row = await approval_requests_repo.create(
                        session_id,
                        "execute_bash_escalation",
                        {
                            "command": call.arguments.get("command", ""),
                            "timeout_seconds": _safe_int(call.arguments.get("timeout_seconds"), default=120),
                            "guard_reason": outcome.guard_reason,
                        },
                    )
                    await _append(
                        session_id,
                        "system",
                        "approval_request",
                        {"approval_request_id": approval_row["id"], "action_type": "execute_bash_escalation", "payload": approval_row["payload"]},
                        parent_event_id=call_event["id"],
                    )
                    await sessions_repo.update_fields(session_id, {"status": "waiting_approval"})
                    _broadcast_done(session_id, "waiting_approval")
                    return
                await _append(
                    session_id,
                    "system",
                    "tool_result",
                    {"ok": outcome.ok, "content": outcome.content, "error": outcome.error, "checkpoint_id": outcome.checkpoint_id},
                    parent_event_id=call_event["id"],
                )
                turn_stuck_events.append(_to_stuck_event(call, outcome))
            else:  # an mcp__ tool set to Ask
                call_event = await _append(
                    session_id,
                    "agent",
                    "tool_call",
                    {"step": step, "call_id": call.id, "name": call.name, "arguments": call.arguments, "read_only": False},
                )
                tool = merged_mcp.by_model_name().get(call.name)
                if tool is None:
                    # Not a real Ask-gate situation — a hallucinated or since-
                    # revoked tool name. Fails cleanly as a normal tool result
                    # rather than pausing the whole session for a human to
                    # approve or reject something that could never execute.
                    await _append(
                        session_id,
                        "system",
                        "tool_result",
                        {"ok": False, "content": "", "error": f"{call.name} is not available to this project right now.", "checkpoint_id": None},
                        parent_event_id=call_event["id"],
                    )
                    turn_stuck_events.append(
                        _to_stuck_event(call, ExecutionOutcome(ok=False, error="not available"))
                    )
                else:
                    action_type = f"mcp_tool:{tool.server_name}:{tool.real_tool_name}"
                    payload = {"model_tool_name": call.name, "arguments": call.arguments}
                    approval_row = await approval_requests_repo.create(session_id, action_type, payload)
                    await _append(
                        session_id,
                        "system",
                        "approval_request",
                        {"approval_request_id": approval_row["id"], "action_type": action_type, "payload": payload},
                        parent_event_id=call_event["id"],
                    )
                    await sessions_repo.update_fields(session_id, {"status": "waiting_approval"})
                    _broadcast_done(session_id, "waiting_approval")
                    return

            check = stuck_detector.run_stuck_detector(turn_stuck_events, already_soft_nudged_this_turn)
            if check.hard_stop:
                await _append(session_id, "system", "stuck_notice", {"text": check.explanation, "severity": "hard"})
                await sessions_repo.update_fields(session_id, {"status": "stuck"})
                _broadcast_done(session_id, "stuck")
                return
            if check.soft_warning:
                already_soft_nudged_this_turn = True
                await _append(session_id, "system", "stuck_notice", {"text": check.explanation, "severity": "soft"})

            turn_iteration_count += 1
            await sessions_repo.update_fields(session_id, {"turn_iteration_count": turn_iteration_count})
            if turn_iteration_count >= max_iterations:
                await _append(session_id, "system", "stuck_notice", {"text": "Iteration ceiling reached for this turn.", "severity": "hard"})
                await sessions_repo.update_fields(session_id, {"status": "stuck"})
                _broadcast_done(session_id, "stuck")
                return

        # every call in this response executed (or the function already
        # returned on a gate/stop/ceiling above) — loop back to call_llm


def _to_stuck_event(call, outcome: ExecutionOutcome) -> stuck_detector.StuckEvent:
    """No read-only/mutating distinction needed here — stuck_detector.py's own
    signals don't care which partition a call came from (signal 1's repeated
    call-and-result applies to a read-only call like view_file just as much
    as a mutating one; signal 2's edit/revert cycle only ever applies to
    str_replace/create_file naturally, via file_path/content_hash being set
    only for those). An earlier draft threaded a `read_only` flag through
    here defensively; it never ended up mattering, so it's gone."""
    file_path = call.arguments.get("path") if call.name in ("str_replace", "create_file") else None
    content_hash = stuck_detector.hash_content(outcome.content) if file_path and outcome.ok else None
    return stuck_detector.StuckEvent(
        tool=call.name,
        args_key=stuck_detector.normalize_args(call.name, call.arguments),
        result_key=stuck_detector.normalize_result(call.name, ok=outcome.ok, content=outcome.content, error=outcome.error),
        success=outcome.ok,
        file_path=file_path,
        content_hash=content_hash,
    )


async def _workspace_has_uncommitted_changes(project_id: str) -> bool:
    """§16.2's `diff_is_nonempty(workspace)` — a plain `git status --porcelain`
    against the workspace's own repo."""
    from app.services import workspace_service
    from app.services.workspace_paths import REPO_ROOT

    result = await workspace_service.exec_in_workspace(project_id, ["git", "status", "--porcelain"], timeout=15, cwd=REPO_ROOT)
    return bool(result.stdout.strip())


def _find_unactioned_resolved_approval(events: list[dict]) -> dict | None:
    """The most recent `approval_request` event with no `approval_response`
    event pointing back at it yet. Whether it's actually resolved (vs. still
    pending) is checked by the caller against the real approval_requests row
    — get_pending_for_session already ran and returned None by the time this
    is called, so if we're here, the DB row (if any) is resolved."""
    responded_to = {e["parent_event_id"] for e in events if e["event_type"] == "approval_response" and e.get("parent_event_id") is not None}
    for event in reversed(events):
        if event["event_type"] == "approval_request" and event["id"] not in responded_to:
            return event
    return None


async def _action_resolved_approval(session: dict, project: dict, user_id: str, approval_event: dict, events: list[dict]) -> None:
    approval_id = approval_event["content"]["approval_request_id"]
    approval_row = await approval_requests_repo.get_owned(user_id, approval_id)
    if approval_row is None or approval_row["status"] == "pending":
        return  # shouldn't happen (caller already confirmed nothing's pending) — defensive only

    approved = approval_row["status"] == "approved"
    await _append(
        session["id"],
        "user",
        "approval_response",
        {"approved": approved, "approval_request_id": approval_id},
        parent_event_id=approval_event["id"],
    )

    # find the original tool_call this approval was gating
    tool_call_event = next((e for e in events if e["id"] == approval_event["parent_event_id"]), None)
    if tool_call_event is None:
        return

    if not approved:
        await _append(
            session["id"],
            "system",
            "tool_result",
            {"ok": False, "content": "", "error": "Rejected by the user.", "checkpoint_id": None},
            parent_event_id=tool_call_event["id"],
        )
        return

    action_type = approval_row["action_type"]
    payload = approval_row["payload"]
    if action_type == "execute_bash_escalation":
        bash_result = await shell_tools.execute_bash(
            project["id"],
            session["id"],
            user_id,
            payload.get("command", ""),
            _safe_int(payload.get("timeout_seconds"), default=120),
            bypass_guard=True,
            conversation_snapshot=events,
        )
        outcome = ExecutionOutcome(
            ok=bash_result.exit_code == 0,
            content=f"exit {bash_result.exit_code}\nstdout:\n{bash_result.stdout}\nstderr:\n{bash_result.stderr}",
            checkpoint_id=bash_result.checkpoint_id,
        )
    else:
        merged = await _fetch_merged_tool_schema(user_id, project["id"])
        model_tool_name = payload.get("model_tool_name", "")
        tool = merged.by_model_name().get(model_tool_name)
        if tool is None:
            outcome = ExecutionOutcome(ok=False, error="This connector tool is no longer available to this project.")
        else:
            outcome = await _execute_mcp(tool, payload.get("arguments", {}))
        # §27: this branch calls _execute_mcp directly rather than through
        # _execute_call (there's no viewed_paths/session context an
        # already-resolved approval needs), so it doesn't get an audit row
        # for free the way the normal turn-loop path does — write one here,
        # through the same helper _execute_call uses so the labels match.
        await _record_tool_audit(
            user_id,
            project["id"],
            session["id"],
            model_tool_name or "mcp__unknown",
            payload.get("arguments", {}),
            outcome,
            tool,
        )

    await _append(
        session["id"],
        "system",
        "tool_result",
        {"ok": outcome.ok, "content": outcome.content, "error": outcome.error, "checkpoint_id": outcome.checkpoint_id},
        parent_event_id=tool_call_event["id"],
    )


async def _run_compaction(session_id: str, credential: llm_client.ResolvedCredential, events: list[dict]) -> None:
    """§17.1: an auxiliary call_llm with the compaction instruction as the
    final user turn, no tools offered. The resulting checkpoint is stored as
    a new condensation_summary event carrying `kept_from_event_id` — see
    message_builder.apply_condensation's own docstring for why that boundary
    has to be interpreted at message-build time rather than by deleting
    anything here (session_events is append-only throughout this codebase;
    checkpoints/audit_log are never mutated after the fact either)."""
    events = message_builder.apply_condensation(events)  # summarize on top of any prior condensation, not the raw full log
    kept_from_id = _last_full_step_event_id(events)
    system_text = ""  # the compaction call needs no system prompt of its own — it's summarizing, not acting
    summarize_messages = message_builder.build_messages(system_text, events) + [
        {"role": "user", "content": compaction.COMPACTION_INSTRUCTION}
    ]
    try:
        response = await llm_client.call_llm(summarize_messages, tools=[], credential=credential)
    except llm_client.LlmCallFailedError:
        return  # compaction is an optimization, not correctness-critical — skip this round, try again next round
    checkpoint_text = response.text.strip()
    if not checkpoint_text:
        return

    await session_events_repo.append(
        session_id,
        role="system",
        event_type="condensation_summary",
        content={"text": compaction.wrap_checkpoint(checkpoint_text), "kept_from_event_id": kept_from_id},
    )


def _last_full_step_event_id(events: list[dict]) -> int:
    """The id of the earliest event belonging to the most recent step — §17.1:
    'keep at least the most recent full step's tool results verbatim
    regardless of budget pressure.' Falls back to one past the last event's
    id (nothing kept) if no event has a step at all — an edge case only a
    session with zero agent turns yet could hit, and should never actually
    reach _run_compaction (there'd be nothing worth compacting)."""
    last_step = None
    for event in reversed(events):
        step = event.get("content", {}).get("step")
        if step is not None:
            last_step = step
            break
    if last_step is None:
        return (events[-1]["id"] + 1) if events else 0
    for event in events:
        if event.get("content", {}).get("step") == last_step:
            return event["id"]
    return events[-1]["id"] + 1
