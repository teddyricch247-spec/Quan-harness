"""
§14 (native tools, as built in Phase 2) + §14.10 (update_plan, given verbatim in
this phase's patch) + §9.4 (runtime merge of a project's granted MCP connector
tools into the model's tool list).

NATIVE_TOOL_SCHEMAS are authored here from Phase 2's real function signatures
(app/services/file_tools.py, shell_tools.py) — the original Phase 2 prompt
bundle that presumably defined these isn't a file that exists in this repo (see
/docs/PHASE3_NOTES.md), so these are reverse-derived from the actual, already-
shipped, already-tested implementations rather than guessed independently of
them. update_plan's schema is the one exception — reproduced exactly from
§14.10's own fenced JSON block, not re-derived.

merge_mcp_tools is pure (takes already-fetched server rows and override maps —
the I/O to fetch them lives in agent_loop.py) and unit-tested directly
(backend/tests/test_tool_schemas.py).
"""
import re
from dataclasses import dataclass, field

UPDATE_PLAN_SCHEMA = {
    "name": "update_plan",
    "description": (
        "Set or revise the session's current plan — a short, structured list of steps "
        "and their status. Overwrites the previous plan; call this whenever the plan "
        "changes, not only at the start."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                    },
                    "required": ["step", "status"],
                },
            }
        },
        "required": ["steps"],
    },
}

NATIVE_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "view_file",
        "description": (
            "Read a file from this project's workspace. Returns its full contents, or a "
            "line range if given one. A file must be viewed before str_replace can edit it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Optional [start_line, end_line], 1-indexed and inclusive.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "str_replace",
        "description": (
            "Replace one exact, unique occurrence of old_str with new_str in an already-"
            "viewed file. Fails if old_str doesn't match exactly once. Every successful "
            "edit is automatically checkpointed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
                "old_str": {"type": "string", "description": "Exact text to replace — must match uniquely."},
                "new_str": {"type": "string", "description": "Text to replace it with."},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "create_file",
        "description": "Create a new file with the given content. Fails if the path already exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repository root."},
                "file_text": {"type": "string", "description": "Full content of the new file."},
            },
            "required": ["path", "file_text"],
        },
    },
    {
        "name": "execute_bash",
        "description": (
            "Run a shell command in this project's workspace. Structurally-flagged commands "
            "(per the heuristic guard) require the person's explicit approval before they run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Optional timeout, default 120, max 600.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "run_lint",
        "description": (
            "Run the linter for this project's language against every file changed since "
            "the workspace's base state. No arguments."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_tests",
        "description": "Run this project's configured test command, optionally scoped to one path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Optional path to scope the test run to."}
            },
        },
    },
    UPDATE_PLAN_SCHEMA,
]

NATIVE_TOOL_NAMES = frozenset(t["name"] for t in NATIVE_TOOL_SCHEMAS)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.lower()).strip("_")
    return slug or "server"


@dataclass(frozen=True)
class MergedMcpTool:
    model_tool_name: str  # e.g. "mcp__github__list_issues" — what the LLM sees and calls
    server_id: str
    server_name: str
    real_tool_name: str  # the name to send back in the actual tools/call request
    description: str
    input_schema: dict
    read_only: bool  # §9.1/§16.2 — MCP annotations.readOnlyHint, captured at handshake time
    permission_state: str  # 'on' | 'ask' — never 'off' (an 'off' tool is excluded entirely, below)
    url: str
    auth_mode: str
    auth_token_ref: str | None


@dataclass
class MergedToolSchema:
    mcp_tools: list[MergedMcpTool] = field(default_factory=list)

    def llm_schemas(self) -> list[dict]:
        return [
            {"name": t.model_tool_name, "description": t.description, "input_schema": t.input_schema}
            for t in self.mcp_tools
        ]

    def by_model_name(self) -> dict[str, MergedMcpTool]:
        return {t.model_tool_name: t for t in self.mcp_tools}

    def side_effect_free_by_name(self) -> dict[str, bool]:
        return {t.model_tool_name: t.read_only for t in self.mcp_tools}

    def permission_state_by_name(self) -> dict[str, str]:
        return {t.model_tool_name: t.permission_state for t in self.mcp_tools}


def resolve_permission_state(tool_name: str, default_permission_state: str, overrides: dict[str, str]) -> str:
    """§9.4's own resolution rule, factored out of connectors.py's _to_out so
    agent_loop.py uses the exact same rule the Connections UI displays —
    `mcp_tool_overrides.permission_state` if set for this tool, else the
    server's own default_permission_state."""
    return overrides.get(tool_name) or default_permission_state


def merge_mcp_tools(
    granted_servers: list[dict], overrides_by_server_id: dict[str, dict[str, str]]
) -> MergedToolSchema:
    """`granted_servers` — the mcp_servers rows for the connectors this project
    has been granted (already `enabled=true`; agent_loop.py filters that before
    calling this — a disabled server is a different state than a per-tool
    'off', but has the same effect here: nothing from it appears). Each row's
    `discovered_tools` entries carry `input_schema`/`read_only` since the
    mcp_handshake.py fix landed this phase. `overrides_by_server_id` maps
    server id -> {tool_name: permission_state}.

    A server-name collision (two connectors whose names slugify the same) gets
    the losing one's model-facing tool names suffixed with a short id fragment
    so both remain callable and distinguishable — rare, but a real name isn't
    guaranteed unique across a user's connectors the way it is within one
    server's own tool list.
    """
    slug_counts: dict[str, int] = {}
    for server in granted_servers:
        slug_counts[_slugify(server["name"])] = slug_counts.get(_slugify(server["name"]), 0) + 1

    merged: list[MergedMcpTool] = []
    for server in granted_servers:
        base_slug = _slugify(server["name"])
        if slug_counts[base_slug] > 1:
            slug = f"{base_slug}_{server['id'][:8]}"
        else:
            slug = base_slug

        overrides = overrides_by_server_id.get(server["id"], {})
        for tool in server.get("discovered_tools") or []:
            permission_state = resolve_permission_state(tool["name"], server["default_permission_state"], overrides)
            if permission_state == "off":
                continue  # §18: "will not even appear in your tool list"
            merged.append(
                MergedMcpTool(
                    model_tool_name=f"mcp__{slug}__{tool['name']}",
                    server_id=server["id"],
                    server_name=server["name"],
                    real_tool_name=tool["name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("input_schema") or {"type": "object", "properties": {}},
                    read_only=bool(tool.get("read_only", False)),
                    permission_state=permission_state,
                    url=server["url"],
                    auth_mode=server["auth_mode"],
                    auth_token_ref=server.get("auth_token_ref"),
                )
            )
    return MergedToolSchema(mcp_tools=merged)


def build_full_tool_list(merged: MergedToolSchema) -> list[dict]:
    """Native tools first, then this project's granted connector tools —
    concatenation order has no behavioral meaning, just kept stable/readable."""
    return list(NATIVE_TOOL_SCHEMAS) + merged.llm_schemas()
