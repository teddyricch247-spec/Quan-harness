"""
§27 audit trail, as written by app/services/agent_loop.py.

agent_loop.py is the I/O shell around the loop's pure modules, and until now had
no test file at all (see /docs/PHASE3_NOTES.md). These tests drive its tool
dispatch (`_execute_call`) and its approval-resume path
(`_action_resolved_approval`) with every collaborator — the file/shell tools,
the MCP transport, the session/approval repositories, `audit_repo.record` —
replaced by in-memory doubles, and assert on exactly what would have been
written to `audit_log`. Nothing here touches a database, a workspace, or an LLM.

What this does NOT cover: `_run_inner`'s full turn loop (LLM call, Ask-gating,
stuck detection, SSE) — exercising that needs the throwaway-repo smoke run
described in PHASE3_NOTES.md against real Supabase/LLM/workspace credentials.
"""
import asyncio
from types import SimpleNamespace
from unittest import mock

from app.services import agent_loop, file_tools, mcp_tools, shell_tools, tool_schemas

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

SECRET_ARG_VALUE = "sk-live-THIS-MUST-NEVER-REACH-THE-AUDIT-TABLE"


def _mcp_tool(server_name: str = "github", real_tool_name: str = "create_issue") -> tool_schemas.MergedMcpTool:
    return tool_schemas.MergedMcpTool(
        model_tool_name=f"mcp__abc123__{real_tool_name}",
        server_id="abc123",
        server_name=server_name,
        real_tool_name=real_tool_name,
        description="d",
        input_schema={},
        read_only=False,
        permission_state="ask",
        url="https://mcp.example.test",
        auth_mode="oauth",
        auth_token_ref="vault-ref",
    )


class _Merged:
    """Just enough of tool_schemas.MergedToolSchema for the dispatcher."""

    def __init__(self, *tools: tool_schemas.MergedMcpTool):
        self._by_name = {t.model_tool_name: t for t in tools}

    def by_model_name(self) -> dict:
        return self._by_name


class _AuditSink:
    def __init__(self):
        self.rows: list[dict] = []

    async def record(self, **kwargs) -> None:
        self.rows.append(kwargs)


def _world(sink: _AuditSink, overrides: dict | None = None):
    """The list of (not-yet-started) patches covering every collaborator
    `_execute_call` can reach. `overrides` swaps individual doubles (e.g. a
    failing view_file), keyed the same way as `doubles` below."""
    doubles = {
        ("audit", "record"): sink.record,
        ("file_tools", "view_file"): mock.AsyncMock(return_value=file_tools.ToolResult(ok=True, content="file body")),
        ("file_tools", "str_replace"): mock.AsyncMock(return_value=file_tools.ToolResult(ok=True, content="edited", checkpoint_id="cp1")),
        ("file_tools", "create_file"): mock.AsyncMock(return_value=file_tools.ToolResult(ok=True, content="created", checkpoint_id="cp2")),
        ("shell_tools", "run_lint"): mock.AsyncMock(return_value=shell_tools.BashResult(executed=True, exit_code=0)),
        ("shell_tools", "run_tests"): mock.AsyncMock(return_value=shell_tools.BashResult(executed=True, exit_code=1)),
        ("shell_tools", "execute_bash"): mock.AsyncMock(return_value=shell_tools.BashResult(executed=True, exit_code=0)),
        ("sessions", "update_fields"): mock.AsyncMock(side_effect=lambda session_id, fields: {"plan": fields["plan"]}),
        ("mcp_tools", "call_tool"): mock.AsyncMock(return_value=SimpleNamespace(ok=True, content="done", error=None)),
    }
    doubles.update(overrides or {})
    targets = {
        "audit": agent_loop.audit_repo,
        "file_tools": file_tools,
        "shell_tools": shell_tools,
        "sessions": agent_loop.sessions_repo,
        "mcp_tools": mcp_tools,
    }
    patches = [mock.patch.object(targets[owner], attr, double) for (owner, attr), double in doubles.items()]
    patches.append(mock.patch("app.services.vault.read_secret", mock.AsyncMock(return_value="TOKEN")))
    return patches


def _call(name: str, arguments: dict, merged: _Merged | None = None, overrides: dict | None = None):
    sink = _AuditSink()
    patches = _world(sink, overrides)
    for p in patches:
        p.start()
    try:
        outcome = asyncio.run(
            agent_loop._execute_call("p1", "s1", "u1", name, arguments, set(), merged or _Merged(), {"id": "s1"}, [])
        )
    finally:
        for p in reversed(patches):
            p.stop()
    return outcome, sink.rows


def _resolve_approval(payload: dict, merged: _Merged):
    """Drives `_action_resolved_approval` for an approved connector-tool call."""
    sink = _AuditSink()
    approval_row = {"status": "approved", "action_type": "mcp_tool:github:create_issue", "payload": payload}
    approval_event = {"id": 10, "parent_event_id": 9, "content": {"approval_request_id": "ap1"}}
    events = [{"id": 9, "event_type": "tool_call"}, approval_event]
    patches = _world(sink) + [
        mock.patch.object(agent_loop.approval_requests_repo, "get_owned", mock.AsyncMock(return_value=approval_row)),
        mock.patch.object(agent_loop, "_append", mock.AsyncMock()),
        mock.patch.object(agent_loop, "_fetch_merged_tool_schema", mock.AsyncMock(return_value=merged)),
    ]
    for p in patches:
        p.start()
    try:
        asyncio.run(agent_loop._action_resolved_approval({"id": "s1"}, {"id": "p1"}, "u1", approval_event, events))
    finally:
        for p in reversed(patches):
            p.stop()
    return sink.rows


# ---------------------------------------------------------------------------
# Labelling: (tool, action) follows 0005_sessions.sql's vocabulary
# ---------------------------------------------------------------------------


def test_native_tools_map_to_the_schema_vocabulary():
    expected = {
        "view_file": ("file_edit", "view_file"),
        "str_replace": ("file_edit", "str_replace"),
        "create_file": ("file_edit", "create_file"),
        "run_lint": ("bash", "run_lint"),
        "run_tests": ("bash", "run_tests"),
        "update_plan": ("plan", "update_plan"),
    }
    for name, labels in expected.items():
        assert agent_loop._audit_labels(name, None) == labels, name


def test_connector_tool_maps_to_its_server_category_and_real_tool_name():
    tool = _mcp_tool(server_name="github", real_tool_name="create_issue")
    assert agent_loop._audit_labels(tool.model_tool_name, tool) == ("mcp:github", "create_issue")


def test_unavailable_connector_tool_and_unknown_native_tool_still_get_a_label():
    assert agent_loop._audit_labels("mcp__gone__thing", None) == ("mcp:unavailable", "mcp__gone__thing")
    assert agent_loop._audit_labels("delete_everything", None) == ("unknown", "delete_everything")


def test_labels_are_consistent_with_execute_bashs_own_rows():
    # shell_tools.execute_bash writes tool='bash', action='execute_bash' itself.
    # run_lint/run_tests must land in the same 'bash' category so one filter finds all of them.
    assert agent_loop._audit_labels("run_lint", None)[0] == "bash"
    assert agent_loop._audit_labels("run_tests", None)[0] == "bash"


# ---------------------------------------------------------------------------
# Payload hygiene
# ---------------------------------------------------------------------------


def test_audit_payload_omits_file_bodies_but_keeps_the_path():
    payload = agent_loop._audit_input_payload("str_replace", {"path": "a.py", "old_str": "x" * 5000, "new_str": "y" * 5000})
    assert payload == {"path": "a.py"}
    assert agent_loop._audit_input_payload("create_file", {"path": "b.py", "file_text": "z" * 5000}) == {"path": "b.py"}


def test_audit_payload_for_a_connector_keeps_argument_names_only():
    payload = agent_loop._audit_input_payload("mcp__abc123__create_issue", {"title": "t", "api_key": SECRET_ARG_VALUE})
    assert payload == {"argument_keys": ["api_key", "title"]}
    assert SECRET_ARG_VALUE not in str(payload)


# ---------------------------------------------------------------------------
# _execute_call: one labelled row per call
# ---------------------------------------------------------------------------


def test_every_native_tool_call_writes_exactly_one_labelled_agent_row():
    cases = [
        ("view_file", {"path": "a.py"}, ("file_edit", "view_file"), True),
        ("str_replace", {"path": "a.py", "old_str": "a", "new_str": "b"}, ("file_edit", "str_replace"), True),
        ("create_file", {"path": "b.py", "file_text": "x"}, ("file_edit", "create_file"), True),
        ("run_lint", {}, ("bash", "run_lint"), True),
        ("run_tests", {"test_path": "tests/"}, ("bash", "run_tests"), False),  # the double reports exit 1
        ("update_plan", {"steps": [{"step": "a", "status": "pending"}]}, ("plan", "update_plan"), True),
    ]
    for name, arguments, (tool, action), ok in cases:
        _outcome, rows = _call(name, arguments)
        assert len(rows) == 1, f"{name}: expected one audit row, got {len(rows)}"
        row = rows[0]
        assert (row["tool"], row["action"]) == (tool, action), name
        assert row["success"] is ok, name
        assert row["initiated_by"] == "agent"
        assert (row["user_id"], row["project_id"], row["session_id"]) == ("u1", "p1", "s1")


def test_a_large_file_edit_does_not_put_the_file_into_the_audit_row():
    big = "x" * 50_000
    _outcome, rows = _call("str_replace", {"path": "a.py", "old_str": big, "new_str": big})
    assert rows[0]["input_payload"] == {"path": "a.py"}


def test_execute_bash_is_not_audited_by_the_dispatcher():
    # shell_tools.execute_bash audits itself (incl. the guard-blocked case);
    # a second row from the dispatcher would double-count the same call.
    outcome, rows = _call("execute_bash", {"command": "ls"})
    assert outcome.ok
    assert rows == []


def test_a_failed_call_is_audited_with_success_false_and_a_bounded_error():
    failing = mock.AsyncMock(return_value=file_tools.ToolResult(ok=False, error="boom " * 400))
    outcome, rows = _call("view_file", {"path": "missing.py"}, overrides={("file_tools", "view_file"): failing})
    assert not outcome.ok
    assert rows[0]["success"] is False
    assert len(rows[0]["output_summary"]) == 500


def test_a_successful_call_has_no_output_summary():
    _outcome, rows = _call("view_file", {"path": "a.py"})
    assert rows[0]["output_summary"] is None


def test_connector_call_is_labelled_by_server_and_carries_no_argument_values():
    tool = _mcp_tool()
    outcome, rows = _call(tool.model_tool_name, {"title": "t", "api_key": SECRET_ARG_VALUE}, _Merged(tool))
    assert outcome.ok
    assert len(rows) == 1
    assert (rows[0]["tool"], rows[0]["action"]) == ("mcp:github", "create_issue")
    assert rows[0]["input_payload"] == {"argument_keys": ["api_key", "title"]}
    assert SECRET_ARG_VALUE not in str(rows[0])


def test_call_to_a_connector_tool_that_is_not_available_is_audited_as_a_failure():
    outcome, rows = _call("mcp__abc123__gone", {"x": 1}, _Merged())
    assert not outcome.ok
    assert len(rows) == 1
    assert (rows[0]["tool"], rows[0]["action"], rows[0]["success"]) == ("mcp:unavailable", "mcp__abc123__gone", False)


def test_call_to_an_unknown_native_tool_is_audited_as_unknown():
    outcome, rows = _call("delete_everything", {})
    assert not outcome.ok
    assert (rows[0]["tool"], rows[0]["action"], rows[0]["success"]) == ("unknown", "delete_everything", False)


# ---------------------------------------------------------------------------
# The second audit site: an approved Ask-gated connector call resumed later
# ---------------------------------------------------------------------------


def test_approved_connector_call_resumed_after_approval_is_audited_with_the_same_labels():
    tool = _mcp_tool()
    rows = _resolve_approval(
        {"model_tool_name": tool.model_tool_name, "arguments": {"title": "t", "api_key": SECRET_ARG_VALUE}}, _Merged(tool)
    )
    assert len(rows) == 1
    assert (rows[0]["tool"], rows[0]["action"], rows[0]["success"]) == ("mcp:github", "create_issue", True)
    assert rows[0]["input_payload"] == {"argument_keys": ["api_key", "title"]}
    assert SECRET_ARG_VALUE not in str(rows[0])
    assert rows[0]["session_id"] == "s1" and rows[0]["project_id"] == "p1" and rows[0]["user_id"] == "u1"


def test_approved_call_to_a_connector_tool_no_longer_granted_is_audited_as_unavailable():
    rows = _resolve_approval({"model_tool_name": "mcp__abc123__create_issue", "arguments": {"title": "t"}}, _Merged())
    assert len(rows) == 1
    assert (rows[0]["tool"], rows[0]["success"]) == ("mcp:unavailable", False)
