"""
Thinking-level controls (OpenRouter's unified `reasoning` object) — the pure parts:
what gets sent, how the completion cap follows it, the degrade-to-default fallback,
and pulling the model's thinking text back out of a response.

Nothing here touches the network or a real provider (same standing gap as
test_llm_client.py). What it does NOT prove: that OpenRouter/Novita accept each level
for Ling 3.1 Flash, or that litellm 1.55.4 forwards `extra_body` and surfaces the
`reasoning` field — those need one real call with a real key.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.services import llm_client, provider_catalog as catalog
from app.services.llm_client import ResolvedCredential

LING = "inclusionai/ling-3.1-flash"


def _cred(provider="openrouter", model=LING, reasoning=None) -> ResolvedCredential:
    return ResolvedCredential(
        id="x", provider=provider, model=model, api_key="k", base_url=None, extra_headers={}, reasoning=reasoning or {}
    )


# --- catalog ---------------------------------------------------------------


def test_ling_quick_model_points_at_the_exact_openrouter_slug():
    quick = catalog.get_quick_model("ling-3.1-flash")
    assert quick is not None
    assert (quick.provider, quick.model) == ("openrouter", LING)
    assert quick.free is True
    # the quick model must resolve to a real preset, or "paste only the key" can't connect
    assert catalog.get_preset(quick.provider) is not None


def test_ling_has_every_native_level_and_can_be_switched_off():
    profile = catalog.reasoning_profile("openrouter", LING)
    assert profile.accepted_efforts() == ("none", "low", "medium", "high", "xhigh")
    assert profile.supports_budget is True
    assert profile.max_output_tokens == 32_768


def test_unknown_openrouter_model_gets_the_conservative_generic_profile():
    profile = catalog.reasoning_profile("openrouter", "some/other-model")
    assert profile is catalog.GENERIC_REASONING
    assert "none" not in profile.accepted_efforts()  # many always-thinking models reject "off"


def test_non_openrouter_providers_have_no_thinking_controls():
    for pid in ("anthropic", "openai", "google", "groq", "custom"):
        assert catalog.reasoning_profile(pid, "anything") is None


def test_public_quick_models_expose_levels_but_no_routing_internals():
    (entry,) = catalog.public_quick_models()
    assert entry["reasoning"]["efforts"][0] == "none"
    assert "litellm_prefix" not in entry and "models_url" not in entry


def test_every_profile_effort_is_a_value_openrouter_defines():
    for profile in [catalog.GENERIC_REASONING, *catalog.MODEL_REASONING.values()]:
        assert set(profile.accepted_efforts()) <= set(catalog.ALL_EFFORTS)


# --- request building ------------------------------------------------------


def test_no_config_sends_nothing_so_the_model_uses_its_own_default():
    assert llm_client.build_reasoning_body(_cred()) is None
    assert llm_client.completion_token_cap(_cred(), None) == 8192


def test_effort_is_sent_as_openrouters_unified_reasoning_object():
    assert llm_client.build_reasoning_body(_cred(reasoning={"effort": "high"})) == {"effort": "high"}


def test_off_is_effort_none_and_does_not_raise_the_token_cap():
    body = llm_client.build_reasoning_body(_cred(reasoning={"effort": "none"}))
    assert body == {"effort": "none"}
    assert llm_client.completion_token_cap(_cred(), body) == 8192


def test_budget_and_hide_thinking_are_independent_of_the_level():
    body = llm_client.build_reasoning_body(_cred(reasoning={"max_tokens": 6000, "show": False}))
    assert body == {"max_tokens": 6000, "exclude": True}


def test_hide_thinking_alone_is_not_treated_as_thinking_being_on():
    body = llm_client.build_reasoning_body(_cred(reasoning={"show": False}))
    assert body == {"exclude": True}
    assert llm_client.completion_token_cap(_cred(), body) == 8192


def test_effort_wins_if_a_row_somehow_carries_both():
    body = llm_client.build_reasoning_body(_cred(reasoning={"effort": "low", "max_tokens": 5000}))
    assert body == {"effort": "low"}


def test_other_providers_never_get_a_reasoning_object_even_if_one_is_stored():
    assert llm_client.build_reasoning_body(_cred(provider="openai", model="gpt-5", reasoning={"effort": "high"})) is None


def test_thinking_on_widens_the_completion_cap_to_the_models_own_limit():
    body = {"effort": "xhigh"}
    cap = llm_client.completion_token_cap(_cred(), body)
    assert cap == llm_client.THINKING_MAX_COMPLETION_TOKENS
    assert cap > 8192 and cap <= 32_768


def test_a_big_thinking_budget_leaves_headroom_for_the_answer_but_never_exceeds_the_model():
    cap = llm_client.completion_token_cap(_cred(), {"max_tokens": 22_000})
    assert cap == 22_000 + llm_client.THINKING_ANSWER_HEADROOM  # 26,096 > the 24,576 default, < 32,768
    assert llm_client.completion_token_cap(_cred(), {"max_tokens": 32_000}) == 32_768


# --- fallback --------------------------------------------------------------


class _StatusError(Exception):
    def __init__(self, status_code, msg):
        super().__init__(msg)
        self.status_code = status_code


def test_only_a_400_or_422_that_mentions_thinking_counts_as_a_rejection():
    assert llm_client._looks_like_reasoning_rejection(_StatusError(400, "Unsupported value for reasoning effort 'xhigh'"))
    assert llm_client._looks_like_reasoning_rejection(_StatusError(422, "thinking budget too small"))
    assert not llm_client._looks_like_reasoning_rejection(_StatusError(400, "context length exceeded"))
    assert not llm_client._looks_like_reasoning_rejection(_StatusError(401, "bad reasoning key"))
    assert not llm_client._looks_like_reasoning_rejection(TimeoutError("reason: read timed out"))  # no status at all


def test_strip_drops_the_level_but_keeps_hide_thinking():
    kwargs = {"max_tokens": 24_576, "extra_body": {"reasoning": {"effort": "xhigh", "exclude": True}}}
    assert llm_client._strip_reasoning_level(kwargs) is True
    assert kwargs["extra_body"] == {"reasoning": {"exclude": True}}
    assert kwargs["max_tokens"] == 8192


def test_strip_removes_extra_body_entirely_when_nothing_else_is_left():
    kwargs = {"max_tokens": 24_576, "extra_body": {"reasoning": {"effort": "high"}}}
    assert llm_client._strip_reasoning_level(kwargs) is True
    assert "extra_body" not in kwargs


def test_strip_is_a_noop_without_a_level_so_the_fallback_cannot_loop():
    assert llm_client._strip_reasoning_level({"max_tokens": 8192}) is False
    assert llm_client._strip_reasoning_level({"extra_body": {"reasoning": {"exclude": True}}}) is False


def test_call_llm_degrades_to_the_default_level_once_then_succeeds(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if "extra_body" in kwargs:
            raise _StatusError(400, "reasoning.effort 'xhigh' is not supported by this model")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
        )

    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(acompletion=fake_acompletion))
    cred = _cred(reasoning={"effort": "xhigh"})
    out = asyncio.run(llm_client.call_llm([{"role": "user", "content": "hi"}], [], cred))
    assert out.text == "done"
    assert len(calls) == 2 and "extra_body" in calls[0] and "extra_body" not in calls[1]


# --- response parsing ------------------------------------------------------


def test_reasoning_is_read_from_whichever_field_the_provider_path_used():
    assert llm_client._extract_reasoning(SimpleNamespace(reasoning_content="a")) == "a"
    assert llm_client._extract_reasoning(SimpleNamespace(reasoning="b")) == "b"
    assert llm_client._extract_reasoning(SimpleNamespace(provider_specific_fields={"reasoning": "c"})) == "c"
    assert llm_client._extract_reasoning(SimpleNamespace(reasoning_content="  ")) == ""
    assert llm_client._extract_reasoning(SimpleNamespace(content="x")) == ""


def test_normalize_response_carries_the_thinking_text():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer", tool_calls=None, reasoning_content="let me think"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    out = llm_client._normalize_response(response)
    assert (out.text, out.reasoning) == ("answer", "let me think")
