from app.services.tool_schemas import (
    NATIVE_TOOL_NAMES,
    build_full_tool_list,
    merge_mcp_tools,
    resolve_permission_state,
    should_attempt_oauth_refresh,
)


def _server(id_, name, default_state="ask", tools=None, enabled=True, auth_mode="static_token", **extra):
    return {
        "id": id_,
        "name": name,
        "url": f"https://{name}.example.com/mcp",
        "auth_mode": auth_mode,
        "auth_token_ref": f"ref-{id_}",
        "default_permission_state": default_state,
        "enabled": enabled,
        "discovered_tools": tools or [],
        **extra,
    }


def test_native_tool_names_include_every_phase_1_2_tool_plus_update_plan():
    for name in ("view_file", "str_replace", "create_file", "execute_bash", "run_lint", "run_tests", "update_plan"):
        assert name in NATIVE_TOOL_NAMES


def test_resolve_permission_state_uses_override_when_set():
    assert resolve_permission_state("t", "ask", {"t": "on"}) == "on"


def test_resolve_permission_state_falls_back_to_server_default():
    assert resolve_permission_state("t", "ask", {}) == "ask"


def test_resolve_permission_state_null_override_falls_back_too():
    # a stored override row with permission_state=None means "inherit" (§9.2)
    assert resolve_permission_state("t", "on", {"t": None}) == "on"


def test_off_tools_are_excluded_entirely():
    server = _server(
        "s1", "GitHub", tools=[{"name": "delete_repo", "description": "", "input_schema": {}, "read_only": False}]
    )
    merged = merge_mcp_tools([server], {"s1": {"delete_repo": "off"}})
    assert merged.mcp_tools == []


def test_on_and_ask_tools_both_appear():
    server = _server(
        "s1",
        "GitHub",
        tools=[
            {"name": "list_issues", "description": "", "input_schema": {}, "read_only": True},
            {"name": "create_issue", "description": "", "input_schema": {}, "read_only": False},
        ],
    )
    merged = merge_mcp_tools([server], {"s1": {"list_issues": "on", "create_issue": "ask"}})
    names = {t.real_tool_name: t.permission_state for t in merged.mcp_tools}
    assert names == {"list_issues": "on", "create_issue": "ask"}


def test_model_tool_name_is_namespaced_by_server_slug():
    server = _server("s1", "My GitHub!", tools=[{"name": "list_issues", "description": "", "input_schema": {}}])
    merged = merge_mcp_tools([server], {})
    assert merged.mcp_tools[0].model_tool_name == "mcp__my_github__list_issues"


def test_colliding_server_names_get_disambiguated():
    s1 = _server("11111111-aaaa", "GitHub", tools=[{"name": "x", "description": "", "input_schema": {}}])
    s2 = _server("22222222-bbbb", "GitHub", tools=[{"name": "x", "description": "", "input_schema": {}}])
    merged = merge_mcp_tools([s1, s2], {})
    model_names = {t.model_tool_name for t in merged.mcp_tools}
    assert len(model_names) == 2  # both distinguishable, neither silently dropped


def test_missing_input_schema_defaults_to_an_open_object():
    server = _server("s1", "X", tools=[{"name": "y", "description": "d"}])  # no input_schema key at all
    merged = merge_mcp_tools([server], {})
    assert merged.mcp_tools[0].input_schema == {"type": "object", "properties": {}}


def test_read_only_flag_carried_through():
    server = _server(
        "s1",
        "X",
        tools=[{"name": "a", "description": "", "input_schema": {}, "read_only": True}],
    )
    merged = merge_mcp_tools([server], {})
    assert merged.side_effect_free_by_name()["mcp__x__a"] is True


def test_llm_schemas_shape_matches_anthropic_tool_format():
    server = _server("s1", "X", tools=[{"name": "a", "description": "desc", "input_schema": {"type": "object"}}])
    merged = merge_mcp_tools([server], {})
    schemas = merged.llm_schemas()
    assert schemas == [{"name": "mcp__x__a", "description": "desc", "input_schema": {"type": "object"}}]


def test_by_model_name_is_a_full_dispatch_table():
    server = _server("s1", "X", tools=[{"name": "a", "description": "", "input_schema": {}}])
    merged = merge_mcp_tools([server], {})
    entry = merged.by_model_name()["mcp__x__a"]
    assert entry.server_id == "s1"
    assert entry.real_tool_name == "a"
    assert entry.url == "https://X.example.com/mcp"
    assert entry.auth_token_ref == "ref-s1"


def test_build_full_tool_list_includes_native_and_mcp():
    server = _server("s1", "X", tools=[{"name": "a", "description": "", "input_schema": {}}])
    merged = merge_mcp_tools([server], {})
    full = build_full_tool_list(merged)
    names = {t["name"] for t in full}
    assert "view_file" in names
    assert "update_plan" in names
    assert "mcp__x__a" in names
    assert len(full) == len(NATIVE_TOOL_NAMES) + 1


def test_empty_grants_yields_native_only():
    merged = merge_mcp_tools([], {})
    full = build_full_tool_list(merged)
    assert len(full) == len(NATIVE_TOOL_NAMES)


# --- Phase 4.3: oauth_session_ref / oauth_client_secret_ref threading, and
# should_attempt_oauth_refresh's own decision logic. ---------------------


def test_oauth_refs_default_to_none_for_a_server_dict_without_them():
    # every existing server dict in this file (static_token mode) has neither
    # key at all — merge_mcp_tools must not raise, and both fields default to
    # None rather than requiring every caller to start passing them.
    server = _server("s1", "X", tools=[{"name": "a", "description": "", "input_schema": {}}])
    merged = merge_mcp_tools([server], {})
    entry = merged.mcp_tools[0]
    assert entry.oauth_session_ref is None
    assert entry.oauth_client_secret_ref is None


def test_oauth_refs_are_carried_through_when_present():
    server = _server(
        "s1",
        "GitHub",
        auth_mode="oauth",
        tools=[{"name": "list_issues", "description": "", "input_schema": {}}],
        oauth_session_ref="vault-session-ref",
        oauth_client_secret_ref="vault-client-secret-ref",
    )
    merged = merge_mcp_tools([server], {})
    entry = merged.mcp_tools[0]
    assert entry.auth_mode == "oauth"
    assert entry.oauth_session_ref == "vault-session-ref"
    assert entry.oauth_client_secret_ref == "vault-client-secret-ref"


def test_should_attempt_oauth_refresh_true_only_for_401_oauth_with_session():
    server = _server(
        "s1", "GitHub", auth_mode="oauth", tools=[{"name": "a"}], oauth_session_ref="vault-session-ref"
    )
    tool = merge_mcp_tools([server], {}).mcp_tools[0]
    assert should_attempt_oauth_refresh(tool, 401) is True


def test_should_attempt_oauth_refresh_false_for_non_401():
    server = _server(
        "s1", "GitHub", auth_mode="oauth", tools=[{"name": "a"}], oauth_session_ref="vault-session-ref"
    )
    tool = merge_mcp_tools([server], {}).mcp_tools[0]
    assert should_attempt_oauth_refresh(tool, 403) is False
    assert should_attempt_oauth_refresh(tool, 500) is False
    assert should_attempt_oauth_refresh(tool, None) is False


def test_should_attempt_oauth_refresh_false_for_static_token_mode():
    # a 401 from a static-token tool means the token itself is wrong/revoked,
    # not expired — nothing to refresh, so this must stay False even though
    # the status code matches.
    server = _server("s1", "X", auth_mode="static_token", tools=[{"name": "a"}])
    tool = merge_mcp_tools([server], {}).mcp_tools[0]
    assert should_attempt_oauth_refresh(tool, 401) is False


def test_should_attempt_oauth_refresh_false_when_oauth_but_no_session_on_file():
    # an oauth-mode server whose authorization server never issued a
    # refresh_token (some don't) has nothing to refresh with either.
    server = _server("s1", "X", auth_mode="oauth", tools=[{"name": "a"}])  # no oauth_session_ref
    tool = merge_mcp_tools([server], {}).mcp_tools[0]
    assert should_attempt_oauth_refresh(tool, 401) is False
