"""§14.8 — the sub-session's loop, with a fake model and a fake tool runner. What matters is structural: what comes back
to the parent (one report), what it can't do (edit, delegate, route around a gate), and that it always terminates."""
import asyncio
from types import SimpleNamespace as NS

from app.services import sub_agent as sa
from app.services import tool_schemas


def _tc(i, name, **arguments):
    return NS(id=f"c{i}", name=name, arguments=arguments)


class FakeModel:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    async def __call__(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _resp(text="", *calls):
    return NS(text=text, tool_calls=list(calls))


def _run(model, run_tool, *, tools=None, max_iterations=5, window=100_000):
    tools = tools if tools is not None else [{"name": "view_file"}, {"name": "execute_bash"}]
    return asyncio.run(sa.run_sub_agent(task="find x", system_text="SYS", tools=tools, call_llm=model, run_tool=run_tool, max_iterations=max_iterations, context_window=window))


async def _ok(call):
    return sa.ToolRun(ok=True, content=f"contents of {call.arguments.get('path', '?')}")


def test_it_reads_then_reports_and_only_the_report_comes_back():
    model = FakeModel(_resp("", _tc(1, "view_file", path="a.py")), _resp("x is used in a.py:3"))
    result = _run(model, _ok)
    assert result.ok and result.report == "x is used in a.py:3" and result.iterations == 2
    # the second model call saw the first tool result in ITS OWN context
    second_messages = model.calls[1][0]
    assert any(m["role"] == "tool" and "contents of a.py" in m["content"] for m in second_messages)
    assert result.calls == [{"name": "view_file", "summary": "a.py", "ok": True}]


def test_a_tool_it_was_not_offered_is_refused_without_being_run():
    ran = []

    async def run_tool(call):
        ran.append(call.name)
        return sa.ToolRun(ok=True, content="x")

    model = FakeModel(_resp("", _tc(1, "str_replace", path="a", old_str="a", new_str="b")), _resp("done"))
    result = _run(model, run_tool)
    assert ran == [] and result.ok
    assert any("not available to a delegated sub-task" in m["content"] for m in model.calls[1][0] if m["role"] == "tool")


def test_a_gated_call_stops_the_sub_task_and_is_never_resumed():
    demand = sa.ApprovalDemand("execute_bash_escalation", {"command": "rm -rf build"})

    async def run_tool(call):
        return sa.ToolRun(ok=False, approval=demand)

    model = FakeModel(_resp("I've seen the layout.", _tc(1, "execute_bash", command="rm -rf build")), _resp("SHOULD NEVER BE REACHED"))
    result = _run(model, run_tool)
    assert result.status == "needs_approval" and result.approval is demand
    assert len(model.calls) == 1                                           # the model was not called again
    assert result.partial_findings == "I've seen the layout."
    marker = sa.build_delegation_marker("find x", result)
    assert marker["task"] == "find x" and marker["findings_so_far"] == "I've seen the layout."


def test_a_gate_in_the_middle_of_a_batch_ends_it_before_later_calls_run():
    ran = []

    async def run_tool(call):
        ran.append(call.id)
        return sa.ToolRun(ok=False, approval=sa.ApprovalDemand("x", {})) if call.id == "c2" else sa.ToolRun(ok=True, content="ok")

    model = FakeModel(_resp("", _tc(1, "view_file", path="a"), _tc(2, "execute_bash", command="x"), _tc(3, "view_file", path="b")))
    result = _run(model, run_tool)
    assert result.status == "needs_approval" and ran == ["c1", "c2"]


def test_it_always_terminates_at_its_iteration_budget_and_asks_for_a_report_without_tools():
    model = FakeModel(*[_resp("", _tc(i, "view_file", path=f"f{i}")) for i in range(3)], _resp("partial: looked at 3 files"))
    result = _run(model, _ok, max_iterations=3)
    assert result.ok and result.truncated and "partial: looked at 3 files" in result.report and "ran out of steps" in result.report
    final_messages, final_tools = model.calls[-1]
    assert final_tools == []                                               # the last call is made with NO tools
    assert final_messages[-1]["role"] == "user" and "out of steps" in final_messages[-1]["content"]


def test_it_wraps_up_when_its_context_fills_even_with_iterations_to_spare():
    async def run_tool(call):
        return sa.ToolRun(ok=True, content="x" * 50_000)

    model = FakeModel(_resp("", _tc(1, "view_file", path="big")), _resp("", _tc(2, "view_file", path="big2")), _resp("report from what I saw"))
    result = _run(model, run_tool, max_iterations=10, window=10_000)
    assert result.truncated and "report from what I saw" in result.report


def test_a_tool_result_is_bounded_before_it_goes_back_to_the_model():
    async def run_tool(call):
        return sa.ToolRun(ok=True, content="y" * (sa.MAX_TOOL_RESULT_CHARS * 3))

    model = FakeModel(_resp("", _tc(1, "view_file", path="big")), _resp("ok"))
    _run(model, run_tool)
    tool_msg = next(m for m in model.calls[1][0] if m["role"] == "tool")
    assert len(tool_msg["content"]) < sa.MAX_TOOL_RESULT_CHARS + 100 and "truncated" in tool_msg["content"]


def test_a_failed_model_call_is_a_failed_delegation_not_a_crash():
    result = _run(FakeModel(sa.SubAgentLlmError("provider down")), _ok)
    assert result.status == "failed" and not result.ok and "provider down" in result.report


def test_a_failing_tool_is_shown_to_the_model_as_an_error_and_it_carries_on():
    async def run_tool(call):
        return sa.ToolRun(ok=False, error="No such file")

    model = FakeModel(_resp("", _tc(1, "view_file", path="nope")), _resp("not found"))
    result = _run(model, run_tool)
    assert result.ok and any(m["role"] == "tool" and m["content"] == "Error: No such file" for m in model.calls[1][0])


def test_the_report_is_bounded_and_an_empty_one_is_replaced_by_a_statement():
    assert len(_run(FakeModel(_resp("z" * (sa.MAX_REPORT_CHARS * 2))), _ok).report) <= sa.MAX_REPORT_CHARS + 100
    assert "without writing a report" in _run(FakeModel(_resp("   ")), _ok).report


def test_the_assistant_message_carries_its_tool_calls_so_the_provider_accepts_the_exchange():
    model = FakeModel(_resp("thinking", _tc(1, "view_file", path="a")), _resp("done"))
    _run(model, _ok)
    assistant = next(m for m in model.calls[1][0] if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "c1" and assistant["tool_calls"][0]["function"]["name"] == "view_file"
    assert '"path": "a"' in assistant["tool_calls"][0]["function"]["arguments"]


# --- the tool list and the knobs ----------------------------------------------------------------------------------


def _mcp(name, read_only, state):
    return NS(model_tool_name=name, description="d", input_schema={"type": "object"}, read_only=read_only, permission_state=state)


def test_the_tool_list_has_no_edit_tool_no_delegation_and_no_browser():
    names = {t["name"] for t in sa.select_tools([], scheduled=False)}
    assert names == {"view_file", "execute_bash"}
    for forbidden in ("str_replace", "create_file", "delegate_task", "run_lint", "run_tests", "update_plan", "preview_rebuild"):
        assert forbidden not in names and forbidden not in tool_schemas.BROWSER_TOOL_NAMES


def test_a_scheduled_run_offers_only_reading_and_the_bash_description_forbids_changes():
    assert {t["name"] for t in sa.select_tools([], scheduled=True)} == {"view_file"}
    bash = next(t for t in sa.select_tools([], scheduled=False) if t["name"] == "execute_bash")
    assert "read-only" in bash["description"].lower() and "do not write" in bash["description"].lower()
    # and the shared native schema object itself was not modified
    assert "read-only" not in next(t for t in tool_schemas.NATIVE_TOOL_SCHEMAS if t["name"] == "execute_bash")["description"].lower()


def test_only_side_effect_free_connector_tools_that_are_fully_on_are_offered():
    tools = sa.select_tools([_mcp("mcp__a__read", True, "on"), _mcp("mcp__a__write", False, "on"), _mcp("mcp__a__ask_read", True, "ask")], scheduled=False)
    assert "mcp__a__read" in {t["name"] for t in tools}
    assert not ({"mcp__a__write", "mcp__a__ask_read"} & {t["name"] for t in tools})


def test_iteration_clamp():
    assert sa.clamp_iterations(None) == sa.DEFAULT_MAX_ITERATIONS == 15
    assert sa.clamp_iterations("x") == 15 and sa.clamp_iterations(0) == 1 and sa.clamp_iterations(-5) == 1
    assert sa.clamp_iterations(7) == 7 and sa.clamp_iterations(10_000) == sa.MAX_ITERATIONS_CEILING


def test_the_system_prompt_states_the_task_the_budget_and_that_files_are_not_instructions():
    p = sa.build_system_prompt("find every use of foo", "REPO MAP", 12)
    assert "find every use of foo" in p and "REPO MAP" in p and "12" in p
    assert "never instructions" in p and "cannot edit" in p


def test_the_delegation_contextvar_defaults_to_not_delegated_and_resets():
    assert sa.DELEGATED_VIA.get() is None
    token = sa.DELEGATED_VIA.set("delegate_task")
    assert sa.DELEGATED_VIA.get() == "delegate_task"
    sa.DELEGATED_VIA.reset(token)
    assert sa.DELEGATED_VIA.get() is None


def test_the_resolved_approval_is_reported_as_a_stopped_sub_task_not_as_bare_shell_output():
    marker = {"task": "find x", "findings_so_far": "seen a.py"}
    rejected = sa.wrap_resolved_text(marker, "", False)
    assert "REJECTED" in rejected and "nothing was run" in rejected and "seen a.py" in rejected and "not resumed" in rejected
    approved = sa.wrap_resolved_text(marker, "total 3", True)
    assert "APPROVED" in approved and "total 3" in approved
    assert sa.wrap_resolved_text(None, "", False)                               # a missing marker still reads sensibly


def test_the_metadata_is_bounded():
    result = sa.SubAgentResult("ok", "r", calls=[{"name": "view_file", "summary": "a", "ok": True}] * 100, iterations=9)
    meta = result.delegation_metadata("t" * 2000, 15)
    assert len(meta["calls"]) == sa.MAX_TRACE_CALLS and meta["calls_omitted"] == 60 and len(meta["task"]) == 500
