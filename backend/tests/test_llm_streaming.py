"""Word-by-word streaming: reading a provider stream into one LlmResponse, and when/how call_llm streams to a viewer.

No network and no litellm: a fake `litellm` module whose `acompletion` returns scripted chunks is put in sys.modules."""
import asyncio
import sys
from types import SimpleNamespace

from app.services import live_text, llm_client, system_prompt


def _chunk(content=None, tool_calls=None, finish=None, usage=None, reasoning=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage)


def _tool_delta(index=0, id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))


async def _aiter(items):
    for item in items:
        if isinstance(item, Exception):
            raise item
        yield item


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------------------------- consume_stream


def test_text_is_collected_whole_and_delivered_in_order():
    delivered = []
    chunks = [_chunk("Hel"), _chunk("lo "), _chunk("world", finish="stop"), SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3))]
    response = _run(llm_client.consume_stream(_aiter(chunks), delivered.append))
    assert response.text == "Hello world" and "".join(delivered) == "Hello world"
    assert response.stop_reason == "stop" and (response.input_tokens, response.output_tokens) == (11, 3)
    assert response.tool_calls == []


def test_fast_chunks_are_coalesced_into_few_deliveries():
    delivered = []
    chunks = [_chunk(w) for w in "abcdefghij"] + [_chunk(None, finish="stop")]
    _run(llm_client.consume_stream(_aiter(chunks), delivered.append))
    assert "".join(delivered) == "abcdefghij" and len(delivered) < 10  # not one delivery per token


def test_a_tool_call_streamed_in_fragments_is_rebuilt():
    chunks = [
        _chunk("Looking."),
        _chunk(tool_calls=[_tool_delta(0, "call_1", "view_file", '{"pa')]),
        _chunk(tool_calls=[_tool_delta(0, None, None, 'th": "a.py"}')]),
        _chunk(None, finish="tool_calls"),
    ]
    delivered = []
    response = _run(llm_client.consume_stream(_aiter(chunks), delivered.append))
    assert response.text == "Looking." and "".join(delivered) == "Looking."  # text before a tool call is not held back
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("call_1", "view_file", {"path": "a.py"})]
    assert response.stop_reason == "tool_calls"


def test_parallel_calls_numbered_zero_are_told_apart_by_id():
    chunks = [
        _chunk(tool_calls=[_tool_delta(0, "a", "view_file", '{"path": "x"}')]),
        _chunk(tool_calls=[_tool_delta(0, "b", "view_file", '{"path": "y"}')]),
        _chunk(None, finish="tool_calls"),
    ]
    response = _run(llm_client.consume_stream(_aiter(chunks)))
    assert [(c.id, c.arguments["path"]) for c in response.tool_calls] == [("a", "x"), ("b", "y")]


def test_two_calls_with_their_own_indexes_stay_separate_and_a_missing_id_gets_one():
    chunks = [
        _chunk(tool_calls=[_tool_delta(0, "a", "run_lint", "{}"), _tool_delta(1, None, "run_tests", '{"test_path": "t"}')]),
        _chunk(None, finish="tool_calls"),
    ]
    response = _run(llm_client.consume_stream(_aiter(chunks)))
    assert [c.name for c in response.tool_calls] == ["run_lint", "run_tests"]
    assert response.tool_calls[1].id and response.tool_calls[1].arguments == {"test_path": "t"}


def test_garbled_tool_arguments_become_empty_arguments_not_a_crash():
    chunks = [_chunk(tool_calls=[_tool_delta(0, "a", "view_file", '{"path": ')]), _chunk(None, finish="tool_calls")]
    response = _run(llm_client.consume_stream(_aiter(chunks)))
    assert response.tool_calls[0].arguments == {}


def test_thinking_text_is_kept_apart_from_the_reply():
    response = _run(llm_client.consume_stream(_aiter([_chunk(None, reasoning="hmm "), _chunk("Answer", reasoning="ok", finish="stop")])))
    assert response.text == "Answer" and response.reasoning == "hmm ok"


def test_a_stream_with_nothing_in_it_is_an_error_so_it_gets_retried():
    try:
        _run(llm_client.consume_stream(_aiter([SimpleNamespace(choices=[], usage=None)])))
    except RuntimeError:
        return
    raise AssertionError("an empty stream should raise")


def test_a_stream_that_finishes_with_no_text_is_a_valid_empty_reply():
    response = _run(llm_client.consume_stream(_aiter([_chunk(None, finish="stop")])))
    assert response.text == "" and response.tool_calls == []


# ---------------------------------------------------------------------------------------------------- call_llm


def _credential(provider="openai"):
    return llm_client.ResolvedCredential(id="c", provider=provider, model="m", api_key="k", base_url=None, extra_headers={})


def _main_messages():
    return [{"role": "system", "content": system_prompt.assemble_static() + "\n\n(dynamic)"}, {"role": "user", "content": "hi"}]


class _FakeLitellm:
    def __init__(self, script):
        self.script = list(script)  # one entry per call: a list of chunks / exceptions, or an Exception to raise at once
        self.requests = []

    async def acompletion(self, **kwargs):
        self.requests.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if kwargs.get("stream"):
            return _aiter(step)
        # a non-streamed reply
        text = "".join(c.choices[0].delta.content or "" for c in step)
        message = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)


def _setup(monkeypatch, script):
    fake = _FakeLitellm(script)
    monkeypatch.setitem(sys.modules, "litellm", fake)
    monkeypatch.setattr(llm_client, "RETRY_BASE_DELAY_SECONDS", 0)
    seen = []
    monkeypatch.setattr(live_text.registry, "_broadcast", lambda sid, payload: seen.append((sid, payload)))
    live_text.registry._live.clear()
    return fake, seen


def _kinds(seen):
    return [p["event_type"] for _sid, p in seen]


def test_a_bound_main_call_streams_and_returns_one_complete_response(monkeypatch):
    fake, seen = _setup(monkeypatch, [[_chunk("Hello "), _chunk("there", finish="stop")]])
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "Hello there"
    assert fake.requests[0]["stream"] is True
    assert "".join(p["text"] for _s, p in seen if p["event_type"] == live_text.DELTA) == "Hello there"
    assert {sid for sid, _p in seen} == {"s1"} and live_text.snapshot("s1") is None  # finished: nothing left "live"


def test_an_unbound_call_is_one_plain_request(monkeypatch):
    fake, seen = _setup(monkeypatch, [[_chunk("Hi", finish="stop")]])
    response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "Hi" and "stream" not in fake.requests[0] and seen == []


def test_a_bound_call_that_is_not_the_main_agent_call_does_not_stream(monkeypatch):
    fake, seen = _setup(monkeypatch, [[_chunk("summary", finish="stop")]])
    other = [{"role": "system", "content": ""}, {"role": "user", "content": "summarise"}]
    with live_text.streaming_for("s1"):
        _run(llm_client.call_llm(other, [], _credential()))
    assert "stream" not in fake.requests[0] and seen == []


def test_a_failure_after_some_text_tells_the_viewer_to_drop_it_before_the_retry(monkeypatch):
    broken = [_chunk("part of an ans"), RuntimeError("connection reset")]
    fake, seen = _setup(monkeypatch, [broken, [_chunk("The real answer", finish="stop")]])
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "The real answer"
    kinds = _kinds(seen)
    assert kinds.index(live_text.RESET) > kinds.index(live_text.DELTA)  # something was shown, then dropped
    after_reset = "".join(p["text"] for _s, p in seen[kinds.index(live_text.RESET):] if p["event_type"] == live_text.DELTA)
    assert after_reset == "The real answer"


def test_stream_options_is_dropped_when_the_provider_rejects_it(monkeypatch):
    err = RuntimeError("Unsupported parameter: stream_options")
    fake, seen = _setup(monkeypatch, [err, [_chunk("ok", finish="stop")]])
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "ok"
    assert "stream_options" in fake.requests[0] and "stream_options" not in fake.requests[1]


def test_a_provider_that_cannot_stream_falls_back_to_a_whole_reply(monkeypatch):
    err = RuntimeError("this model does not support stream")
    err.status_code = 400
    fake, seen = _setup(monkeypatch, [err, [_chunk("whole reply", finish="stop")]])
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "whole reply" and fake.requests[0]["stream"] is True and "stream" not in fake.requests[1]


def test_when_every_attempt_fails_the_viewer_is_reset_and_the_error_is_raised(monkeypatch):
    err = RuntimeError("boom")
    fake, seen = _setup(monkeypatch, [[_chunk("start"), err], [_chunk("again"), err], [_chunk("third"), err]])
    with live_text.streaming_for("s1"):
        try:
            _run(llm_client.call_llm(_main_messages(), [], _credential()))
        except llm_client.LlmCallFailedError:
            pass
        else:
            raise AssertionError("should have failed")
    assert _kinds(seen)[-1] == live_text.RESET and live_text.snapshot("s1") is None


# ------------------------------------------------------------------------------------------------------ thinking


def _setup_saving(monkeypatch, script, reasoning=None):
    fake, seen = _setup(monkeypatch, script)
    saved = []

    async def append_event(session_id, role, event_type, content):
        saved.append((event_type, content["text"]))
        seen.append((session_id, {"event_type": "SAVED:" + event_type}))
        return {"id": 9, "event_type": event_type}

    monkeypatch.setattr(live_text.registry, "_append_event", append_event)
    return fake, seen, saved


def test_thinking_streams_live_then_is_saved_before_the_reply_event(monkeypatch):
    chunks = [_chunk(None, reasoning="Let me "), _chunk(None, reasoning="think."), _chunk("The answer", finish="stop")]
    fake, seen, saved = _setup_saving(monkeypatch, [chunks])
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "The answer" and response.reasoning == "Let me think."
    live = "".join(p["text"] for _s, p in seen if p["event_type"] == live_text.THINKING_DELTA)
    assert live == "Let me think."
    assert saved == [("thinking", "Let me think.")]
    kinds = _kinds(seen)
    assert kinds.index(live_text.THINKING_DELTA) < kinds.index(live_text.DELTA)  # the thinking comes first
    assert live_text.snapshot("s1", live_text.THINKING) is None


def test_a_credential_that_hides_thinking_neither_shows_nor_saves_it(monkeypatch):
    chunks = [_chunk(None, reasoning="secret reasoning"), _chunk("Answer", finish="stop")]
    fake, seen, saved = _setup_saving(monkeypatch, [chunks])
    credential = _credential()
    credential.reasoning = {"show": False}
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], credential))
    assert response.text == "Answer"
    assert saved == [] and live_text.THINKING_DELTA not in _kinds(seen)


def test_a_failure_to_save_thinking_does_not_fail_the_call(monkeypatch):
    chunks = [_chunk(None, reasoning="hmm"), _chunk("Answer", finish="stop")]
    fake, seen, saved = _setup_saving(monkeypatch, [chunks])

    async def boom(*_a, **_k):
        raise RuntimeError("check constraint")

    monkeypatch.setattr(live_text.registry, "_append_event", boom)
    with live_text.streaming_for("s1"):
        response = _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert response.text == "Answer"


def test_a_call_with_no_thinking_saves_nothing(monkeypatch):
    fake, seen, saved = _setup_saving(monkeypatch, [[_chunk("Hi", finish="stop")]])
    with live_text.streaming_for("s1"):
        _run(llm_client.call_llm(_main_messages(), [], _credential()))
    assert saved == []


# ------------------------------------------------------------- the session comes from the turn, not from a binding


def _fake_turn_module():
    import importlib.util
    import os
    import tempfile
    import textwrap

    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "services"))
    path = os.path.join(root, "services", "agent_loop.py")
    with open(path, "w") as f:
        f.write(textwrap.dedent(
            """
            from app.services import llm_client

            async def _run(session_id, user_id, messages, credential):
                return await llm_client.call_llm(messages, [], credential)
            """
        ))
    spec = importlib.util.spec_from_file_location("fake_turn_for_stream", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_model_call_inside_a_turn_streams_to_that_session_with_no_binding_at_all(monkeypatch):
    # This is the first message of a new project: routers/projects.py starts that turn, not the router that binds.
    fake, seen = _setup(monkeypatch, [[_chunk("Hello ", finish=None), _chunk("again", finish="stop")]])
    turn = _fake_turn_module()

    async def main():
        return await asyncio.create_task(turn._run("session-first", "u", _main_messages(), _credential()))

    response = asyncio.run(main())
    assert response.text == "Hello again" and fake.requests[0]["stream"] is True
    assert {sid for sid, _p in seen} == {"session-first"}
    assert "".join(p["text"] for _s, p in seen if p["event_type"] == live_text.DELTA) == "Hello again"
