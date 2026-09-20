"""
§16.2: "'Read-only' for partitioning purposes is a fixed property per tool, the
same way its permission state is: view_file, web_search,
browser_navigate/browser_click/browser_type/browser_screenshot/
browser_get_console_logs, and any connector tool explicitly marked
side-effect-free at connection time. str_replace, create_file, and
execute_bash are always in the mutating partition, unconditionally."

Kept dependency-free and pure, same reasoning as stuck_detector.py.

Design decision the spec excerpt doesn't spell out: run_lint, run_tests, and
update_plan aren't on §16.2's own read-only allow-list, and aren't named
alongside str_replace/create_file/execute_bash as always-mutating either.
run_lint/run_tests run through exactly the same exec_in_workspace() primitive
as execute_bash (app/services/shell_tools.py) — they execute inside the same
shared workspace a concurrent str_replace/execute_bash could be writing to —
so the same "ordering matters at the filesystem level regardless" reasoning
§16.2 gives for execute_bash applies to them too. update_plan only ever
writes to this session's own `sessions.plan` row (no workspace I/O at all),
so it has no real race to avoid, but there's no benefit to special-casing a
single low-frequency call into the concurrent lane either. The simplest rule
that doesn't require guessing per-tool is: the fixed read-only allow-list is
read-only, everything else defaults to the mutating/sequential partition —
see /docs/PHASE3_NOTES.md.
"""

READ_ONLY_NATIVE_TOOLS = frozenset(
    {
        "view_file",
        "web_search",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_get_console_logs",
    }
)

ALWAYS_MUTATING_NATIVE_TOOLS = frozenset({"str_replace", "create_file", "execute_bash"})


def is_read_only(tool_name: str, mcp_side_effect_free: bool = False) -> bool:
    """`mcp_side_effect_free` is the per-connector-tool flag set at connection
    time (§9.1) — passed in by the caller for an MCP tool call; ignored for a
    native tool, where read-only-ness is the fixed property above."""
    if tool_name in READ_ONLY_NATIVE_TOOLS:
        return True
    if tool_name in ALWAYS_MUTATING_NATIVE_TOOLS:
        return False
    if tool_name.startswith("mcp__"):
        return mcp_side_effect_free
    return False  # anything else native (run_lint, run_tests, update_plan) — see module docstring


def partition(tool_calls: list, side_effect_free_by_name: dict[str, bool] | None = None) -> tuple[list, list]:
    """Splits a batch of tool calls (any object with a `.name` attribute, e.g.
    the provider-agnostic ToolCall the LLM client returns) into
    (read_only, mutating), preserving each sublist's original relative order —
    §16.2 requires mutating calls to execute "in the order the model issued
    them."""
    side_effect_free_by_name = side_effect_free_by_name or {}
    read_only, mutating = [], []
    for call in tool_calls:
        if is_read_only(call.name, side_effect_free_by_name.get(call.name, False)):
            read_only.append(call)
        else:
            mutating.append(call)
    return read_only, mutating
