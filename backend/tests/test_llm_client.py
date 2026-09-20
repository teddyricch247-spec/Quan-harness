from app.services.llm_client import (
    ResolvedCredential,
    ToolCall,
    _apply_prompt_caching,
    _litellm_model_string,
    _normalize_response,
    _to_function_tools,
)
from app.services.system_prompt import DynamicSections, assemble, assemble_static


def _cred(provider: str, model: str) -> ResolvedCredential:
    return ResolvedCredential(id="x", provider=provider, model=model, api_key="k", base_url=None, extra_headers={})


def test_model_string_mapping_per_provider():
    assert _litellm_model_string(_cred("anthropic", "claude-sonnet-4-6")) == "anthropic/claude-sonnet-4-6"
    assert _litellm_model_string(_cred("openai", "gpt-5")) == "openai/gpt-5"
    assert _litellm_model_string(_cred("google", "gemini-2.5-pro")) == "gemini/gemini-2.5-pro"
    assert _litellm_model_string(_cred("openrouter", "anthropic/claude-sonnet-4-6")) == "openrouter/anthropic/claude-sonnet-4-6"


def test_custom_provider_treated_as_openai_compatible():
    assert _litellm_model_string(_cred("custom", "my-self-hosted-model")) == "openai/my-self-hosted-model"


def test_to_function_tools_converts_input_schema_to_parameters():
    schemas = [{"name": "view_file", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    converted = _to_function_tools(schemas)
    assert converted == [
        {"type": "function", "function": {"name": "view_file", "description": "d", "parameters": {"type": "object", "properties": {}}}}
    ]


def test_to_function_tools_defaults_missing_schema_to_open_object():
    converted = _to_function_tools([{"name": "x", "description": ""}])
    assert converted[0]["function"]["parameters"] == {"type": "object", "properties": {}}


class _FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _FakeFn(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _FakeResponse:
    def __init__(self, choices, usage):
        self.choices = choices
        self.usage = usage


def test_normalize_response_with_tool_calls():
    resp = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage(None, [_FakeToolCall("call_1", "view_file", '{"path": "a.py"}')]), "tool_calls")],
        usage=_FakeUsage(100, 20),
    )
    normalized = _normalize_response(resp)
    assert normalized.text == ""
    assert normalized.tool_calls == [ToolCall(id="call_1", name="view_file", arguments={"path": "a.py"})]
    assert normalized.input_tokens == 100
    assert normalized.output_tokens == 20


def test_normalize_response_plain_text():
    resp = _FakeResponse(choices=[_FakeChoice(_FakeMessage("All done.", None), "stop")], usage=_FakeUsage(50, 10))
    normalized = _normalize_response(resp)
    assert normalized.text == "All done."
    assert normalized.tool_calls == []
    assert normalized.stop_reason == "stop"


def test_normalize_response_malformed_tool_call_arguments_do_not_raise():
    resp = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage(None, [_FakeToolCall("c2", "run_lint", "not json")]), "tool_calls")],
        usage=_FakeUsage(1, 1),
    )
    normalized = _normalize_response(resp)
    assert normalized.tool_calls[0].arguments == {}


def test_normalize_response_with_no_usage_defaults_to_zero():
    resp = _FakeResponse(choices=[_FakeChoice(_FakeMessage("hi", None), "stop")], usage=None)
    normalized = _normalize_response(resp)
    assert normalized.input_tokens == 0
    assert normalized.output_tokens == 0


# ---------------------------------------------------------------------------
# _apply_prompt_caching — §17's static/dynamic caching split
# ---------------------------------------------------------------------------

_DYNAMIC = DynamicSections(repo_context="- app.py", current_datetime="2026-01-01 00:00:00 UTC (Thursday)")


def _real_system_messages() -> list[dict]:
    return [{"role": "system", "content": assemble(_DYNAMIC)}, {"role": "user", "content": "fix the bug"}]


def test_anthropic_gets_a_cache_marked_static_prefix():
    result = _apply_prompt_caching(_real_system_messages(), _cred("anthropic", "claude-sonnet-4-6"))
    system_content = result[0]["content"]
    assert isinstance(system_content, list)
    assert system_content[0] == {"type": "text", "text": assemble_static(), "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in system_content[1]  # only the static block is marked as a cache breakpoint
    # The dynamic remainder is preserved verbatim (its own leading "\n\n" separator included), just split off from the static block.
    assert system_content[0]["text"] + system_content[1]["text"] == assemble(_DYNAMIC)
    # Nothing else in the message list is touched.
    assert result[1] == {"role": "user", "content": "fix the bug"}


def test_non_anthropic_providers_are_untouched():
    original = _real_system_messages()
    for provider in ("openai", "google", "openrouter", "custom"):
        result = _apply_prompt_caching(original, _cred(provider, "some-model"))
        assert result is original


def test_no_dynamic_remainder_still_produces_one_cached_block():
    static_only = [{"role": "system", "content": assemble_static()}]
    result = _apply_prompt_caching(static_only, _cred("anthropic", "claude-sonnet-4-6"))
    assert result[0]["content"] == [{"type": "text", "text": assemble_static(), "cache_control": {"type": "ephemeral"}}]


def test_fails_open_on_unexpected_shapes():
    # No messages at all.
    assert _apply_prompt_caching([], _cred("anthropic", "m")) == []
    # First message isn't a system message.
    only_user = [{"role": "user", "content": "hi"}]
    assert _apply_prompt_caching(only_user, _cred("anthropic", "m")) == only_user
    # system content is already a list (some other caller's shape), not a plain string.
    already_blocks = [{"role": "system", "content": [{"type": "text", "text": "x"}]}]
    assert _apply_prompt_caching(already_blocks, _cred("anthropic", "m")) == already_blocks
    # system content doesn't start with the real static prefix at all.
    mismatched = [{"role": "system", "content": "totally different system text"}]
    assert _apply_prompt_caching(mismatched, _cred("anthropic", "m")) == mismatched
