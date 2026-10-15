"""§23.10 — the security principles checklist, as tests that read the CODE (import graph + AST), not the docs.

Each test names the checklist bullet it enforces. They fail ON PURPOSE when someone adds a capability that changes the
answer: a new tool, a new place that calls a model, a new host the backend talks to. The fix is never to loosen the test;
it is to review the change, update `app/services/data_flows.py` (the in-product "what leaves this workspace" screen) in the
same change, and say why the new capability doesn't give the agent both "read the repo" and "write to GitHub".

Pure: parses source files, imports nothing from app/ except data_flows (itself pure).

Bullet 4 — short-lived, least-privilege tokens for the initial clone and for Push/Pull — is NOT enforced here because it is
NOT MET: the GitHub OAuth token is broad (the `repo` scope) and long-lived. See docs/PHASE5_6_5_7_5_8_NOTES.md.
"""
import ast
import os
import re

from app.services import data_flows

APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _modules() -> dict[str, str]:
    out = {}
    for root, _, files in os.walk(APP):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, os.path.join(APP, "..")).replace(os.sep, ".")[:-3]
                out[rel.removesuffix(".__init__")] = path
    return out


MODULES = _modules()
TREES = {m: ast.parse(open(p, encoding="utf-8").read()) for m, p in MODULES.items()}


def _imports(module: str) -> set[str]:
    out = set()
    for n in ast.walk(TREES[module]):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names if a.name in MODULES}
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
            for a in n.names:
                out.add(f"{n.module}.{a.name}" if f"{n.module}.{a.name}" in MODULES else n.module)
    return {m for m in out if m in MODULES}


def _reach(*starts: str) -> set[str]:
    seen, todo = set(), list(starts)
    while todo:
        m = todo.pop()
        if m not in seen and m in MODULES:
            seen.add(m)
            todo += _imports(m)
    return seen


# Everything the model's own tool calls can execute, directly or through anything they import.
AGENT_FACING = ("app.services.agent_loop", "app.services.sub_agent", "app.services.visual_qa", "app.services.file_tools", "app.services.shell_tools")


# --- bullet 2: "The agent never holds a git-push credential — Push is a user-triggered button only" ---------------------


def test_nothing_the_agent_can_reach_imports_the_push_credential_or_any_http_route():
    reachable = _reach(*AGENT_FACING)
    forbidden = {"app.services.git_sync", "app.services.github_oauth", "app.repositories.github_credentials"}
    assert not (reachable & forbidden), f"the agent can now reach a push credential: {sorted(reachable & forbidden)}"
    assert not [m for m in reachable if m.startswith("app.routers")], "agent-facing code imports an HTTP router"


def test_push_and_pull_are_only_ever_called_from_the_user_facing_router_and_project_import():
    callers = set()
    for module, tree in TREES.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("push", "pull") \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "git_sync":
                callers.add(module)
    assert callers <= {"app.routers.workspace", "app.routers.projects"}, f"git_sync.push/pull called from {sorted(callers)}"


# --- bullet 3: "no native credential or tool for any external platform" ------------------------------------------------


def test_no_tool_the_agent_is_offered_is_named_for_an_external_platform_or_a_credential():
    from app.services import tool_schemas as ts

    names = [t["name"] for t in ts.NATIVE_TOOL_SCHEMAS + ts.BROWSER_TOOL_SCHEMAS + ts.PREVIEW_TOOL_SCHEMAS]
    bad = [n for n in names if re.search(r"push|pull|github|token|credential|secret|oauth|deploy_key|publish", n)]
    assert not bad, bad


def test_the_agents_browser_never_gets_a_context_wide_credential_or_a_url_parameter():
    src = open(MODULES["app.services.visual_qa"], encoding="utf-8").read()
    assert "extra_http_headers" not in src and "set_extra_http_headers" not in src      # the token is attached per request, to ONE origin
    assert '"per-context"' in src and "chromium_proxy_bypass" in src                      # the network-level wall (redirects can't escape)
    assert "<-loopback>" in open(MODULES["app.services.visual_qa_rules"], encoding="utf-8").read()
    from app.services import tool_schemas as ts

    for tool in ts.BROWSER_TOOL_SCHEMAS:
        props = tool["input_schema"].get("properties", {})
        assert "url" not in props and "host" not in props, tool["name"]                    # §14.9: a PATH on the project's own preview


# --- bullet 1: secrets only in the workspace's runtime environment ------------------------------------------------------


def _callers_of(attr: str) -> set[str]:
    out = set()
    for module, tree in TREES.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr:
                out.add(module)
    return out


def test_preview_secret_values_are_only_ever_turned_into_a_runtime_environment_by_the_deploy_path():
    assert _callers_of("get_runtime_env") <= {"app.services.deploy_pipeline", "app.services.preview_runtime"}


def test_nothing_the_model_reads_is_built_from_secret_values_directly():
    # The prompt/message builders and tool schemas never touch the secret stores at all.
    for module in ("app.services.system_prompt", "app.services.message_builder", "app.services.tool_schemas", "app.services.sub_agent"):
        imported = _imports(module)
        assert not (imported & {"app.repositories.project_secrets", "app.repositories.preview_secrets", "app.services.vault"}), module


# --- bullet 5: "Be explicit and honest in-product about exactly what leaves the workspace and when" ------------------


def test_every_module_that_can_send_text_to_a_model_is_listed_in_the_data_flows_screen():
    callers = _callers_of("call_llm") | _callers_of("acompletion")
    callers -= {"app.services.llm_client"}                     # the one function that does it
    callers -= {"app.services.sub_agent"}                      # takes the call as a PARAMETER; agent_loop supplies it (and is listed)
    assert callers <= data_flows.LLM_CALLING_MODULES, (
        f"{sorted(callers - data_flows.LLM_CALLING_MODULES)} now send text to a model but data_flows.py doesn't say so"
    )
    assert data_flows.LLM_CALLING_MODULES <= set(MODULES), "data_flows lists a module that no longer exists"


def test_every_model_call_outside_the_agent_loop_is_tool_less():
    """§23.2: "the boundary is tool access, not model involvement"."""
    for module, tree in TREES.items():
        if module in ("app.services.agent_loop", "app.services.llm_client"):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "call_llm" \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "llm_client":
                tools = next((k.value for k in n.keywords if k.arg == "tools"), None)
                assert isinstance(tools, ast.List) and not tools.elts, f"{module}:{n.lineno} gives a model tools outside the agent loop"


_URL_HOST = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})")
# Hosts that appear in code only as documentation, examples, namespaces or placeholders — never contacted.
_NOT_CONTACTED = {"example.com", "www.w3.org", "json-schema.org", "supabase.co", "supabase.com", "ngrok.io"}
# Provider API hosts are CONFIGURATION (the model provider the person chose) and are covered by the data_flows `llm` row.
_CONFIGURED_PROVIDER_FILES = {"app.services.provider_catalog", "app.services.provider_probe"}


def test_the_backend_names_no_external_host_that_data_flows_does_not_account_for():
    unknown: dict[str, set[str]] = {}
    for module, tree in TREES.items():
        if module in _CONFIGURED_PROVIDER_FILES:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                for host in _URL_HOST.findall(n.value):
                    host = host.lower().rstrip(".")
                    if host in data_flows.KNOWN_EGRESS_HOSTS or host in _NOT_CONTACTED or host.endswith(".example.com"):
                        continue
                    unknown.setdefault(host, set()).add(module)
    assert not unknown, f"the backend now names hosts the data_flows screen doesn't explain: { {h: sorted(m) for h, m in unknown.items()} }"
