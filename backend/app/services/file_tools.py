"""
§14.2: the three structured file tools — view_file, str_replace, create_file —
plus §22's automatic, per-edit syntax check. Implementation order step 6.

Design note on "already viewed this session" (§14.2: "The tool layer rejects a
call against any path not opened via view_file earlier in the same session"):
Phase 2 has no turn loop and therefore no persistent per-session state store yet
(that's Phase 3 — see /docs/PHASE1_NOTES.md and /docs/PHASE2_NOTES.md). Rather
than invent a session-state table now and guess at a shape Phase 3 might not
want, str_replace() below takes the caller-tracked set of viewed paths as an
explicit argument and enforces the rule against it. Phase 3's turn loop owns
that set (trivially — it's just "every path seen in a tool_call/tool_result
event this session," which Phase 3 already has to track for the transcript).
This keeps the actual guarantee real and unit-tested now (see
backend/tests/test_str_replace_logic.py) without fabricating a schema for
state that belongs to a phase that hasn't been designed yet.

Every function here operates against exactly one project's workspace (§23) —
never GitHub, directly or indirectly (§14.5: "there is no github_commit_and_push
tool and never has been"). The actual matching/syntax-check logic lives in the
dependency-free app/services/text_edit.py — this module is just the I/O shell
around it (workspace exec calls + checkpoint triggering).
"""
import base64
import json
from dataclasses import dataclass

from app.services import checkpoints, workspace_service
from app.services.text_edit import StrReplaceMatchError, apply_str_replace, check_syntax
from app.services.workspace_paths import resolve_repo_path

__all__ = [
    "ToolResult",
    "PathNotViewedError",
    "StrReplaceMatchError",
    "view_file",
    "str_replace",
    "create_file",
    "apply_str_replace",
    "check_syntax",
]


class PathNotViewedError(ValueError):
    pass


@dataclass
class ToolResult:
    ok: bool
    content: str = ""
    syntax_check: str | None = None
    error: str | None = None
    checkpoint_id: str | None = None


# ---------------------------------------------------------------------------
# view_file
# ---------------------------------------------------------------------------


async def view_file(project_id: str, path: str, view_range: tuple[int, int] | None = None) -> ToolResult:
    try:
        full_path = resolve_repo_path(path)
    except ValueError as exc:
        # A path outside the repo root, an absolute path, or an otherwise
        # malformed path argument — a normal, recoverable tool failure the
        # model can see and correct, same as any other bad-argument case,
        # not a raised exception. Phase 2 never had a live caller that could
        # hand this an untrusted path (only tests did); Phase 3's turn loop
        # does, so this now needs to degrade instead of propagate.
        return ToolResult(ok=False, error=str(exc))
    result = await workspace_service.exec_in_workspace(project_id, ["cat", full_path], timeout=30)
    if result.exit_code != 0:
        return ToolResult(ok=False, error=result.stderr.strip() or f"Could not read {path}.")
    content = result.stdout
    if view_range:
        start, end = view_range
        lines = content.splitlines()
        content = "\n".join(lines[max(start - 1, 0):end])
    return ToolResult(ok=True, content=content)


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------


async def str_replace(
    project_id: str,
    path: str,
    old_str: str,
    new_str: str,
    viewed_paths: set[str],
    session_id: str,
    conversation_snapshot: list | None = None,
) -> ToolResult:
    """`conversation_snapshot` — the caller's own current session_events list
    (oldest first), the same one it just built this iteration's `messages`
    from — passed straight through to checkpoints.create_checkpoint. Phase 2
    left this permanently empty (see checkpoints.py's own docstring); Phase
    3's turn loop is exactly the caller PHASE2_NOTES.md said would populate
    it for real, since it's the only caller that actually has the
    accumulated event log in hand. Optional and defaults to None (stored as
    empty) so every existing Phase 2 call/test that doesn't pass it is
    unaffected."""
    if path not in viewed_paths:
        raise PathNotViewedError(f"{path} must be read with view_file before it can be edited.")

    read = await view_file(project_id, path)
    if not read.ok:
        return read

    try:
        new_content = apply_str_replace(read.content, old_str, new_str)
    except StrReplaceMatchError as exc:
        return ToolResult(ok=False, error=str(exc))

    try:
        full_path = resolve_repo_path(path)
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc))
    write = await _write_file(project_id, full_path, new_content)
    if not write.ok:
        return write

    syntax = check_syntax(path, new_content)
    # §14.2: checkpoint creation is "unconditional backend behavior — not
    # something the model decides to do or skip" — happens after every
    # successful edit, syntax-broken or not.
    checkpoint_id = await checkpoints.create_checkpoint(project_id, session_id, conversation_snapshot)
    return ToolResult(ok=True, content=new_content, syntax_check=syntax, checkpoint_id=checkpoint_id)


# ---------------------------------------------------------------------------
# create_file
# ---------------------------------------------------------------------------


async def create_file(
    project_id: str, path: str, file_text: str, session_id: str, conversation_snapshot: list | None = None
) -> ToolResult:
    try:
        full_path = resolve_repo_path(path)
    except ValueError as exc:
        # create_file has no "must be viewed first" gate the way str_replace
        # does, so this is the most directly reachable of the three — a
        # model-supplied path is resolved here with nothing upstream that
        # would have already validated it.
        return ToolResult(ok=False, error=str(exc))
    check = await workspace_service.exec_in_workspace(project_id, ["test", "-e", full_path], timeout=15)
    if check.exit_code == 0:
        return ToolResult(ok=False, error=f"{path} already exists — use str_replace to modify it.")

    write = await _write_file(project_id, full_path, file_text)
    if not write.ok:
        return write

    syntax = check_syntax(path, file_text)
    checkpoint_id = await checkpoints.create_checkpoint(project_id, session_id, conversation_snapshot)
    return ToolResult(ok=True, content=file_text, syntax_check=syntax, checkpoint_id=checkpoint_id)


async def _write_file(project_id: str, full_path: str, content: str) -> ToolResult:
    """Writes via a Python one-liner executed in the workspace, fed its payload as
    a base64-encoded argv element — never interpolated into a shell string, so
    arbitrary file content (quotes, backticks, `$(...)`, newlines) is never a
    shell-injection concern the way it would be building a heredoc/echo command."""
    payload = base64.b64encode(json.dumps({"path": full_path, "content": content}).encode()).decode()
    script = (
        "import sys, base64, json, os\n"
        "p = json.loads(base64.b64decode(sys.argv[1]))\n"
        "os.makedirs(os.path.dirname(p['path']), exist_ok=True)\n"
        "with open(p['path'], 'w') as f:\n"
        "    f.write(p['content'])\n"
    )
    result = await workspace_service.exec_in_workspace(
        project_id, ["python3", "-c", script, payload], timeout=30
    )
    if result.exit_code != 0:
        return ToolResult(ok=False, error=result.stderr.strip() or "Write failed.")
    return ToolResult(ok=True)
