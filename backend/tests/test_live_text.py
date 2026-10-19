"""The ephemeral "reply so far" channel (live_text.py): no network, no event loop."""
from app.services import live_text


def _registry():
    sent = []
    return live_text.LiveTextRegistry(lambda sid, payload: sent.append((sid, payload))), sent


def test_deltas_accumulate_and_carry_a_rising_sequence_number():
    reg, sent = _registry()
    reg.delta("s", "Hel")
    reg.delta("s", "lo")
    assert reg.snapshot("s") == {"text": "Hello", "seq": 2}
    assert [p["seq"] for _s, p in sent] == [1, 2] and [p["text"] for _s, p in sent] == ["Hel", "lo"]
    assert all(p["event_type"] == live_text.DELTA and p["id"] == 0 for _s, p in sent)


def test_sessions_are_independent_and_empty_text_is_ignored():
    reg, sent = _registry()
    reg.delta("a", "x")
    reg.delta("b", "")
    assert reg.snapshot("a") == {"text": "x", "seq": 1} and reg.snapshot("b") is None and len(sent) == 1


def test_reset_discards_and_tells_the_watchers_but_only_if_something_was_live():
    reg, sent = _registry()
    reg.reset("s")
    assert sent == []
    reg.delta("s", "abc")
    reg.reset("s")
    assert reg.snapshot("s") is None and sent[-1][1]["event_type"] == live_text.RESET
    reg.delta("s", "new")
    assert reg.snapshot("s") == {"text": "new", "seq": 1}  # a fresh stream starts counting again


def test_end_is_silent():
    reg, sent = _registry()
    reg.delta("s", "abc")
    n = len(sent)
    reg.end("s")
    assert reg.snapshot("s") is None and len(sent) == n


def test_a_broadcast_that_raises_never_propagates():
    def boom(_sid, _payload):
        raise RuntimeError("queue gone")

    reg = live_text.LiveTextRegistry(boom)
    reg.delta("s", "abc")  # must not raise
    assert reg.snapshot("s") == {"text": "abc", "seq": 1}


def test_binding_is_scoped_to_the_block():
    assert live_text.bound_session() is None
    with live_text.streaming_for("s1"):
        assert live_text.bound_session() == "s1"
    assert live_text.bound_session() is None


def test_a_task_started_inside_the_block_keeps_the_binding_after_the_block_ends():
    import asyncio

    async def main():
        seen = []

        async def child():
            await asyncio.sleep(0)
            seen.append(live_text.bound_session())

        with live_text.streaming_for("s1"):
            task = asyncio.create_task(child())
        await task  # the block has exited, the task still sees the session it was started under
        return seen

    assert asyncio.run(main()) == ["s1"]


def test_the_sink_speaks_for_one_session():
    reg, sent = _registry()
    sink = live_text.LiveSink("s9", reg)
    sink.delta("hi")
    sink.reset()
    sink.delta("again")
    sink.end()
    assert [(s, p["event_type"]) for s, p in sent] == [("s9", live_text.DELTA), ("s9", live_text.RESET), ("s9", live_text.DELTA)]


def test_a_watcher_with_no_snapshot_gets_every_delta_and_the_resets():
    viewer = live_text.LiveViewer(None)
    assert viewer.first_frames == []
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 1, "text": "a", "id": 0}) == ("delta", {"text": "a", "seq": 1})
    assert viewer.frame_for({"event_type": live_text.RESET, "id": 0}) == ("reset", {})


def test_a_watcher_who_joins_mid_reply_gets_the_text_so_far_and_skips_what_it_already_has():
    viewer = live_text.LiveViewer({"text": "Hello wor", "seq": 5})
    assert viewer.first_frames == [("delta", {"text": "Hello wor", "seq": 5, "replace": True})]
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 4, "text": "r", "id": 0}) is None  # inside the snapshot
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 5, "text": "o", "id": 0}) is None
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 6, "text": "ld", "id": 0}) == ("delta", {"text": "ld", "seq": 6})


def test_after_a_reset_the_sequence_starts_over_and_nothing_is_skipped():
    viewer = live_text.LiveViewer({"text": "old", "seq": 9})
    viewer.frame_for({"event_type": live_text.RESET, "id": 0})
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 1, "text": "new", "id": 0}) == ("delta", {"text": "new", "seq": 1})


def test_only_live_payloads_are_recognised_as_live():
    assert live_text.is_live_payload({"event_type": live_text.DELTA}) and live_text.is_live_payload({"event_type": live_text.RESET})
    assert not live_text.is_live_payload({"event_type": "__session_status__"}) and not live_text.is_live_payload({"event_type": "message"})


def test_thinking_is_its_own_channel_with_its_own_sequence():
    reg, sent = _registry()
    reg.delta("s", "hmm ", live_text.THINKING)
    reg.delta("s", "Answer")
    reg.delta("s", "ok", live_text.THINKING)
    assert reg.snapshot("s", live_text.THINKING) == {"text": "hmm ok", "seq": 2}
    assert reg.snapshot("s") == {"text": "Answer", "seq": 1}
    assert [p["event_type"] for _s, p in sent] == [live_text.THINKING_DELTA, live_text.DELTA, live_text.THINKING_DELTA]


def test_reset_and_end_clear_both_channels():
    reg, sent = _registry()
    reg.delta("s", "t", live_text.THINKING)
    reg.delta("s", "a")
    reg.reset("s")
    assert reg.snapshot("s") is None and reg.snapshot("s", live_text.THINKING) is None
    assert sent[-1][1]["event_type"] == live_text.RESET
    reg.delta("s", "t", live_text.THINKING)
    reg.end("s")
    assert reg.snapshot("s", live_text.THINKING) is None


def test_a_watcher_joining_mid_thinking_gets_both_snapshots_and_skips_what_it_has():
    viewer = live_text.LiveViewer({"text": "Ans", "seq": 2}, {"text": "think", "seq": 4})
    assert viewer.first_frames == [
        ("thinking", {"text": "think", "seq": 4, "replace": True}),
        ("delta", {"text": "Ans", "seq": 2, "replace": True}),
    ]
    assert viewer.frame_for({"event_type": live_text.THINKING_DELTA, "seq": 4, "text": "k", "id": 0}) is None
    assert viewer.frame_for({"event_type": live_text.THINKING_DELTA, "seq": 5, "text": "!", "id": 0}) == ("thinking", {"text": "!", "seq": 5})
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 2, "text": "s", "id": 0}) is None
    assert viewer.frame_for({"event_type": live_text.DELTA, "seq": 3, "text": "w", "id": 0}) == ("delta", {"text": "w", "seq": 3})


def test_thinking_payloads_count_as_live_payloads():
    assert live_text.is_live_payload({"event_type": live_text.THINKING_DELTA})


def test_saving_thinking_appends_one_agent_event_and_tells_the_watchers():
    import asyncio

    saved, sent = [], []

    async def append_event(session_id, role, event_type, content):
        saved.append((session_id, role, event_type, content))
        return {"id": 41, "session_id": session_id, "role": role, "event_type": event_type, "content": content}

    reg = live_text.LiveTextRegistry(lambda sid, p: sent.append((sid, p)), append_event)
    asyncio.run(reg.save_thinking("s", "  I should check the file first.  "))
    assert saved == [("s", "agent", "thinking", {"text": "I should check the file first."})]
    assert sent[0][1]["id"] == 41 and sent[0][1]["event_type"] == "thinking"


def test_empty_thinking_is_not_saved_and_long_thinking_is_capped():
    import asyncio

    saved = []

    async def append_event(session_id, role, event_type, content):
        saved.append(content["text"])
        return {"id": 1, "content": content}

    reg = live_text.LiveTextRegistry(lambda *_: None, append_event)
    asyncio.run(reg.save_thinking("s", "   "))
    asyncio.run(reg.save_thinking("s", "x" * (live_text.MAX_THINKING_CHARS + 500)))
    assert len(saved) == 1 and len(saved[0]) <= live_text.MAX_THINKING_CHARS + 1 and saved[0].endswith("…")


def test_a_failed_save_is_swallowed_so_the_turn_is_unaffected():
    import asyncio

    async def append_event(*_a, **_k):
        raise RuntimeError("violates check constraint session_events_event_type_check")

    sent = []
    reg = live_text.LiveTextRegistry(lambda sid, p: sent.append(p), append_event)
    asyncio.run(reg.save_thinking("s", "some thinking"))  # must not raise
    asyncio.run(reg.save_thinking("s", "more thinking"))
    assert sent == []


def test_the_sink_exposes_the_thinking_verbs():
    import asyncio

    reg, sent = _registry()
    saved = []

    async def append_event(session_id, role, event_type, content):
        saved.append(event_type)
        return {"id": 3, "event_type": event_type}

    reg._append_event = append_event
    sink = live_text.LiveSink("s9", reg)
    sink.thinking_delta("hm")
    asyncio.run(sink.save_thinking("hm"))
    assert [p["event_type"] for _s, p in sent][0] == live_text.THINKING_DELTA and saved == ["thinking"]
