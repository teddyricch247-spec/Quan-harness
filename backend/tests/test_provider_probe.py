import asyncio
import socket

from app.services import provider_probe as probe_mod
from app.services.provider_probe import ProbeNetworkError, check_public_url, parse_models, probe


def _run(coro):
    return asyncio.run(coro)


def _fake_get(responses: dict[str, tuple[int, object]], calls: list | None = None):
    """http_get stand-in: exact-URL → (status, body); any other URL fails the test."""

    async def _get(url, headers):
        if calls is not None:
            calls.append((url, headers))
        assert url in responses, f"unexpected URL {url}"
        return responses[url]

    return _get


# ---- parsing ---------------------------------------------------------------


def test_openrouter_flags_tool_support_filters_non_text_and_sorts_tools_first():
    payload = {
        "data": [
            {"id": "z/no-tools", "context_length": 8000, "supported_parameters": ["temperature"]},
            {"id": "a/has-tools", "name": "A: Has Tools", "context_length": 200000, "supported_parameters": ["tools", "temperature"]},
            {"id": "img/gen", "architecture": {"output_modalities": ["image"]}, "supported_parameters": ["tools"]},
        ]
    }
    models = parse_models("openrouter", payload)
    assert [m.id for m in models] == ["a/has-tools", "z/no-tools"]
    assert models[0].supports_tools is True and models[0].context_length == 200000
    assert models[0].name == "A: Has Tools"
    assert models[1].supports_tools is False


def test_together_returns_a_bare_array_and_non_chat_models_are_dropped():
    payload = [
        {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "type": "chat", "context_length": 131072},
        {"id": "BAAI/bge-large", "type": "embedding"},
    ]
    models = parse_models("together", payload)
    assert [m.id for m in models] == ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
    assert models[0].supports_tools is None  # provider didn't say


def test_google_strips_models_prefix_and_requires_generate_content():
    payload = {
        "models": [
            {"name": "models/gemini-2.5-pro", "displayName": "Gemini 2.5 Pro", "inputTokenLimit": 1048576,
             "supportedGenerationMethods": ["generateContent", "countTokens"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    models = parse_models("google", payload)
    assert [m.id for m in models] == ["gemini-2.5-pro"]
    assert models[0].name == "Gemini 2.5 Pro" and models[0].context_length == 1048576


def test_openai_drops_obvious_non_chat_models_but_keeps_chat_ones():
    payload = {"data": [{"id": "gpt-5"}, {"id": "text-embedding-3-large"}, {"id": "whisper-1"}, {"id": "dall-e-3"}]}
    assert [m.id for m in parse_models("openai", payload)] == ["gpt-5"]


def test_mistral_function_calling_capability_becomes_tools_flag():
    payload = {"data": [{"id": "mistral-large-latest", "max_context_length": 128000,
                         "capabilities": {"completion_chat": True, "function_calling": True}},
                        {"id": "mistral-embed", "capabilities": {"completion_chat": False}}]}
    models = parse_models("mistral", payload)
    assert [m.id for m in models] == ["mistral-large-latest"]
    assert models[0].supports_tools is True and models[0].context_length == 128000


def test_parse_is_defensive_about_garbage():
    assert parse_models("openai", None) == []
    assert parse_models("openai", {"data": "nope"}) == []
    assert parse_models("openai", {"data": [1, None, {"no_id": True}, "plain-string-id"]})[0].id == "plain-string-id"


def test_duplicate_ids_collapse():
    assert len(parse_models("groq", {"data": [{"id": "a"}, {"id": "a"}]})) == 1


# ---- probe flow ------------------------------------------------------------


def test_openai_probe_ok_sends_bearer_header():
    calls: list = []
    get = _fake_get({"https://api.openai.com/v1/models": (200, {"data": [{"id": "gpt-5"}]})}, calls)
    result = _run(probe("openai", "sk-test", http_get=get))
    assert result.status == "ok" and [m.id for m in result.models] == ["gpt-5"]
    assert calls[0][1] == {"Authorization": "Bearer sk-test"}


def test_anthropic_and_google_use_their_own_auth_headers():
    calls: list = []
    a = _fake_get({"https://api.anthropic.com/v1/models?limit=1000": (200, {"data": [{"id": "claude-sonnet-4-6"}]})}, calls)
    assert _run(probe("anthropic", "sk-ant-x", http_get=a)).status == "ok"
    assert calls[0][1] == {"x-api-key": "sk-ant-x", "anthropic-version": "2023-06-01"}

    calls.clear()
    g = _fake_get({"https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000": (200, {"models": [{"name": "models/gemini-2.5-pro"}]})}, calls)
    assert _run(probe("google", "AIza-x", http_get=g)).status == "ok"
    assert calls[0][1] == {"x-goog-api-key": "AIza-x"}


def test_openrouter_checks_the_key_first_because_models_is_public():
    calls: list = []
    get = _fake_get({
        "https://openrouter.ai/api/v1/key": (401, {"error": {"message": "nope"}}),
        "https://openrouter.ai/api/v1/models": (200, {"data": [{"id": "a/b"}]}),
    }, calls)
    result = _run(probe("openrouter", "sk-or-bad", http_get=get))
    assert result.status == "invalid_key"
    assert [c[0] for c in calls] == ["https://openrouter.ai/api/v1/key"]  # never reached /models


def test_openrouter_good_key_lists_models():
    get = _fake_get({
        "https://openrouter.ai/api/v1/key": (200, {"data": {}}),
        "https://openrouter.ai/api/v1/models": (200, {"data": [{"id": "a/b", "supported_parameters": ["tools"]}]}),
    })
    result = _run(probe("openrouter", "sk-or-good", http_get=get))
    assert result.status == "ok" and result.models[0].supports_tools is True


def test_401_and_403_are_invalid_key_and_message_never_contains_the_key():
    for code in (401, 403):
        get = _fake_get({"https://api.groq.com/openai/v1/models": (code, {"error": "bad sk-secret-123"})})
        result = _run(probe("groq", "sk-secret-123", http_get=get))
        assert result.status == "invalid_key"
        assert "sk-secret-123" not in (result.message or "")


def test_404_is_no_model_list_not_invalid_key():
    get = _fake_get({"https://api.deepseek.com/models": (404, None)})
    assert _run(probe("deepseek", "k", http_get=get)).status == "no_model_list"


def test_empty_list_is_no_model_list_so_ui_offers_manual_entry():
    get = _fake_get({"https://api.x.ai/v1/models": (200, {"data": []})})
    assert _run(probe("xai", "k", http_get=get)).status == "no_model_list"


def test_5xx_and_network_errors_are_unreachable():
    assert _run(probe("mistral", "k", http_get=_fake_get({"https://api.mistral.ai/v1/models": (503, None)}))).status == "unreachable"

    async def boom(url, headers):
        raise ProbeNetworkError("ConnectTimeout")

    result = _run(probe("cerebras", "k", http_get=boom))
    assert result.status == "unreachable" and "ConnectTimeout" in result.message


def test_unknown_provider_and_blank_key_are_bad_request():
    assert _run(probe("nope", "k")).status == "bad_request"
    assert _run(probe("openai", "   ")).status == "bad_request"


def test_custom_requires_base_url_and_appends_models_path():
    assert _run(probe("custom", "k", None)).status == "bad_request"

    calls: list = []
    get = _fake_get({"https://llm.example.com/v1/models": (200, {"data": [{"id": "my-model"}]})}, calls)
    result = _run(probe("custom", "k", "https://llm.example.com/v1/", http_get=get, url_check=lambda u: None))
    assert result.status == "ok" and result.models[0].id == "my-model"


def test_custom_url_that_fails_the_guard_never_makes_a_request():
    async def must_not_be_called(url, headers):
        raise AssertionError("request was made to a blocked URL")

    result = _run(probe("custom", "k", "http://10.0.0.5/v1", http_get=must_not_be_called, url_check=lambda u: "blocked"))
    assert result.status == "bad_request" and result.message == "blocked"


# ---- SSRF guard ------------------------------------------------------------


def _resolver_for(*ips: str):
    def _resolve(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (ip, port)) for ip in ips]

    return _resolve


def test_guard_blocks_private_loopback_and_metadata_addresses():
    for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.5", "169.254.169.254", "0.0.0.0", "100.64.0.1"):
        assert check_public_url("https://x.example", _resolver_for(ip)) is not None, ip


def test_guard_blocks_when_any_resolved_address_is_private():
    assert check_public_url("https://x.example", _resolver_for("93.184.216.34", "10.0.0.1")) is not None


def test_guard_allows_public_addresses_and_rejects_bad_schemes_and_embedded_credentials():
    assert check_public_url("https://x.example/v1", _resolver_for("93.184.216.34")) is None
    assert check_public_url("http://x.example/v1", _resolver_for("93.184.216.34")) is None
    assert check_public_url("ftp://x.example", _resolver_for("93.184.216.34")) is not None
    assert check_public_url("file:///etc/passwd") is not None
    assert check_public_url("https://user:pw@x.example", _resolver_for("93.184.216.34")) is not None


def test_guard_blocks_ip_literal_hosts_and_unresolvable_hosts():
    assert check_public_url("http://127.0.0.1:8000/v1") is not None
    assert check_public_url("http://[::1]/v1") is not None

    def nxdomain(host, port, proto=0):
        raise socket.gaierror("nope")

    assert check_public_url("https://nope.invalid", nxdomain) is not None
