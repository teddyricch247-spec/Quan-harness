"""Offline tests for the 2026-10-05 speed-first routing work: app/provider_routing.py,
the `session_id` / `provider` fields in response_api.build_chat_completions_body(),
the served-by capture, and the routing values in models/kael/config.py.

Stdlib only (provider_routing.py, response_api.py and models/kael/config.py import
nothing outside the standard library), so this runs without `pip install`:

    python3 test_provider_routing.py        # or: pytest test_provider_routing.py
"""
import json

from app import provider_routing as pr
from app import response_api as ra
from app.models.kael.config import KAEL_BETA as MODEL


# ---------------------------------------------------------------- session id
def _conv(first="Explain DNS", extra=None):
    items = [{"role": "user", "content": first}]
    if extra:
        items += extra
    return items


def test_session_id_is_stable_across_turns():
    turn1 = _conv()
    turn2 = _conv(extra=[{"role": "assistant", "content": "DNS maps names to IPs."}, {"role": "user", "content": "and TTL?"}])
    assert pr.derive_session_id("u1", turn1) == pr.derive_session_id("u1", turn2)


def test_session_id_differs_per_account_and_per_conversation():
    assert pr.derive_session_id("u1", _conv()) != pr.derive_session_id("u2", _conv())
    assert pr.derive_session_id("u1", _conv("a")) != pr.derive_session_id("u1", _conv("b"))


def test_session_id_ignores_a_leading_system_prompt_but_not_the_user_turn():
    with_sys = [{"role": "system", "content": "be terse"}] + _conv()
    without = _conv()
    assert pr.derive_session_id("u1", with_sys) == pr.derive_session_id("u1", without)


def test_session_id_handles_content_parts_and_empty_input():
    parts = [{"role": "user", "content": [{"type": "text", "text": "Explain DNS"}]}]
    assert pr.derive_session_id("u1", parts) == pr.derive_session_id("u1", _conv("Explain DNS"))
    for sid in (pr.derive_session_id(None, []), pr.derive_session_id("u1", None)):
        assert sid.startswith("kael-") and len(sid) <= 256


def test_session_id_never_contains_conversation_text():
    sid = pr.derive_session_id("someone@example.com", _conv("my secret plan"))
    assert "secret" not in sid and "example" not in sid
    assert len(sid) == len("kael-") + 32


# ------------------------------------------------------------ request body
def _body(**kw):
    base = dict(provider="openrouter", model="deepseek/deepseek-v4.1-flash", input_items=_conv(), tools=None,
                reasoning_effort="low", max_output_tokens=1000, stream=False)
    base.update(kw)
    return ra.build_chat_completions_body(**base)


def test_body_carries_provider_object_and_session_id():
    routing = MODEL["draft_provider_routing"]
    body = _body(provider_routing=routing, session_id="kael-abc")
    assert body["provider"] == routing
    assert body["session_id"] == "kael-abc"
    json.dumps(body)  # must be serializable as-is


def test_body_omits_session_id_when_absent_and_for_direct_glm():
    assert "session_id" not in _body(provider_routing=MODEL["draft_provider_routing"])
    assert "session_id" not in _body(provider="glm", session_id="kael-abc")


# ------------------------------------------------------------ config values
def test_routing_is_speed_first_with_owner_price_ceilings():
    d, c = MODEL["draft_provider_routing"], MODEL["critic_provider_routing"]
    for r in (d, c):
        assert r["sort"] == "throughput"
        assert r["allow_fallbacks"] is True
        assert r["preferred_max_latency"] == {"p90": 2.0}
        # nothing may pin a host: these fields are what the old setup used
        # and what OpenRouter documents as switching sticky routing off
        for banned in ("order", "only"):
            assert banned not in r
        # `ignore` only EXCLUDES a host. config.py has excluded "relace" since
        # 2026-10-09 (a standing exclusion, not a pin), and nothing else may be
        # added without a decision: OpenRouter does not say what `ignore` does
        # to sticky routing (see provider_routing.py).
        assert r.get("ignore") == ["relace"]
    assert d["max_price"] == {"prompt": 0.30, "completion": 1.20}
    assert c["max_price"] == {"prompt": 0.30, "completion": 1.20}


def test_draft_and_critic_are_both_deepseek_4_1_flash():
    assert MODEL["draft_model"] == "deepseek/deepseek-v4.1-flash"
    assert MODEL["critic_model"] == "deepseek/deepseek-v4.1-flash"


# -------------------------------------------------- no-provider-fits-the-cap
def test_no_provider_statuses_are_recognised():
    assert pr.is_no_provider_error(503) and pr.is_no_provider_error(404)
    assert not pr.is_no_provider_error(429) and not pr.is_no_provider_error(500) and not pr.is_no_provider_error(402)


def test_no_provider_client_payload_names_no_vendor():
    text = json.dumps(pr.NO_PROVIDER_CLIENT_PAYLOAD).lower()
    for vendor in ("openrouter", "deepseek", "glm", "z.ai", "relace", "price"):
        assert vendor not in text


def test_log_lines_are_greppable_and_report_cache_use():
    line = pr.no_provider_log_line("deepseek/deepseek-v4.1-flash", 503, "no endpoints")
    assert "NO_ELIGIBLE_PROVIDER" in line
    usage = {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 1024}}
    served = pr.describe_served_by("stream", "deepseek/deepseek-v4.1-flash", "Together", usage)
    assert "served_by=Together" in served and "prompt_tokens=1200" in served and "cached_tokens=1024" in served
    assert "served_by=unknown" in pr.describe_served_by("stream", "m", None, None)


# ------------------------------------------- serving host is captured, never leaked
def test_stream_accumulator_captures_host_and_it_is_stripped_for_callers():
    acc = ra.new_cc_accumulator()
    acc = ra.accumulate_cc_chunk(acc, {"id": "g1", "provider": "Together", "choices": [{"delta": {"content": "Hi"}}]})
    acc = ra.accumulate_cc_chunk(acc, {"id": "g1", "provider": "Together", "choices": [{"delta": {}, "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    data = ra.cc_accumulator_to_responses_shape(acc)
    assert data["served_by"] == "Together"
    for shape in ("responses", "chat_completions"):
        out = ra.reshape(data, shape, "kael-beta", billed_usage={"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 0, "total_tokens": 12})
        assert "Together" not in json.dumps(out) and "served_by" not in json.dumps(out)


def test_non_stream_response_captures_host():
    cc = {"id": "g2", "provider": "BaseTen", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}
    assert ra.chat_completion_to_responses_shape(cc)["served_by"] == "BaseTen"
    assert ra.chat_completion_to_responses_shape({**cc, "provider": None})["served_by"] is None


# ------------------------------------------------------------ backup host
def test_fallback_routing_pins_baseten_and_keeps_the_same_price_cap():
    for key in ("draft_provider_routing", "critic_provider_routing"):
        r = MODEL[key]
        fb = pr.fallback_routing(r)
        assert fb == {"order": ["baseten"], "allow_fallbacks": False, "max_price": r["max_price"], "data_collection": "deny"}
        assert fb["max_price"] is not r["max_price"]  # a copy, never shared
        json.dumps(fb)


def test_fallback_routing_refuses_to_run_without_a_price_cap():
    assert pr.fallback_routing(None) is None
    assert pr.fallback_routing({}) is None
    assert pr.fallback_routing({"sort": "throughput"}) is None



def test_titles_session_id_is_its_own_stable_key():
    sid = pr.derive_session_id("u1", [{"role": "user", "content": "hi"}])
    t = pr.titles_session_id(sid)
    assert t and t != sid and t.startswith(sid)
    assert pr.titles_session_id(sid) == t
    assert len(t) <= 256


def test_titles_session_id_none_stays_none():
    assert pr.titles_session_id(None) is None
    assert pr.titles_session_id("") is None


# ------------------------------------------- thinking-title summarizer (2026-10-08)
def test_summarizer_has_its_own_cheap_first_model_list():
    models = MODEL["summarizer_models"]
    assert models == [
        "inclusionai/ling-3.0-flash",
        "deepseek/deepseek-v4.1-flash",
    ]
    # DeepSeek is the last resort, never the first choice
    assert models[-1] == MODEL["draft_model"] and models[0] != MODEL["draft_model"]
    assert len(set(models)) == len(models)
    # Ling 3.1 Flash was a free launch promotion; the owner chose not to build on it
    assert not any("ling-3.1" in m for m in models)


def test_summarizer_routing_sorts_by_price_and_has_a_hard_ceiling():
    r = MODEL["summarizer_provider_routing"]
    assert r["sort"] == "price"
    assert r["allow_fallbacks"] is True
    assert r["preferred_max_latency"] == {"p50": 2.0}
    assert r["max_price"] == {"prompt": 0.15, "completion": 0.60}
    # the summarizer's ceiling must stay below the draft/critic ceiling it used to borrow
    d = MODEL["draft_provider_routing"]["max_price"]
    assert r["max_price"]["prompt"] < d["prompt"] and r["max_price"]["completion"] < d["completion"]
    # nothing may pin a host: that switches OpenRouter's sticky routing off
    for banned in ("order", "only", "ignore"):
        assert banned not in r
    json.dumps(r)  # sent verbatim as the request's `provider` object


# ------------------------------------------- mid-stream failover (2026-10-09)
def _err_chunk(host="CoreWeave", finish="error", code=502):
    return {"id": "gen-1", "provider": host, "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": finish}],
            "error": {"code": code, "message": "Provider disconnected: THE CALLER'S PROMPT", "metadata": {"error_type": "provider_error", "raw": "THE CALLER'S PROMPT"}}}


def test_error_chunk_is_captured_with_safe_fields_only():
    acc = ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk())
    assert acc["upstream_error"] == {"code": "502", "error_type": "provider_error", "provider": "CoreWeave"}
    assert "PROMPT" not in json.dumps(acc["upstream_error"])
    done = ra.cc_accumulator_to_responses_shape(acc)
    assert done["status"] == "failed" and done["upstream_finish_reason"] == "error"
    assert done["upstream_error"] == acc["upstream_error"]


def test_error_object_without_failed_finish_reason_still_fails_the_pass():
    acc = ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk(finish=None))
    assert ra.cc_accumulator_to_responses_shape(acc)["status"] == "failed"


def test_clean_stream_has_no_upstream_error():
    acc = ra.accumulate_cc_chunk(ra.new_cc_accumulator(), {"provider": "X", "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]})
    done = ra.cc_accumulator_to_responses_shape(acc)
    assert done["status"] == "completed" and done["upstream_error"] is None


def test_nonstream_error_body_is_captured_and_fails():
    body = {"id": "x", "provider": "CoreWeave", "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "error"}],
            "error": {"code": 502, "message": "secret", "metadata": {"error_type": "provider_error"}}}
    done = ra.chat_completion_to_responses_shape(body)
    assert done["status"] == "failed" and done["upstream_error"]["provider"] == "CoreWeave"


def test_unsafe_error_fields_are_dropped():
    out = pr.safe_error_fields({"code": "has spaces and prose", "type": "ok_type", "metadata": {"provider_name": "<script>"}}, "Good Host")
    assert out == {"error_type": "ok_type", "provider": "Good Host"}
    assert pr.safe_error_fields("not a dict") is None


def test_failed_pass_summary_is_content_free():
    done = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk()))
    line = pr.failed_pass_summary(done)
    assert line == "finish_reason=error code=502 error_type=provider_error host=CoreWeave"
    assert "PROMPT" not in line


def test_only_error_failures_are_failover_candidates():
    mk = lambda finish: ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk(finish=finish)))
    assert pr.is_failover_candidate(mk("error")) is True
    assert pr.is_failover_candidate(mk("content_filter")) is False
    assert pr.is_failover_candidate({"status": "completed"}) is False


def test_ignore_slug():
    assert pr.ignore_slug("CoreWeave") == "coreweave"
    assert pr.ignore_slug("Google Vertex") == "google-vertex"
    assert pr.ignore_slug(None) is None and pr.ignore_slug("a|b") is None


def test_failover_routing_ignores_the_failed_host_and_keeps_the_rest():
    routing = MODEL["draft_provider_routing"]
    done = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk()))
    got, how = pr.failover_routing(routing, done)
    # config.py already ignores "relace" (2026-10-09), so the failed host is added to it
    assert got["ignore"] == ["coreweave", "relace"]
    assert {k: v for k, v in got.items() if k != "ignore"} == {k: v for k, v in routing.items() if k != "ignore"}   # sort / fallbacks / ceiling untouched
    assert routing["ignore"] == ["relace"]                              # the shared config dict is never mutated
    assert got["max_price"] is not routing["max_price"]
    # an existing ignore list is extended, not replaced
    got2, _ = pr.failover_routing({**routing, "ignore": ["foo"]}, done)
    assert got2["ignore"] == ["coreweave", "foo"]


def test_failover_routing_pins_the_backup_when_the_host_is_unknown_and_never_runs_uncapped():
    routing = MODEL["draft_provider_routing"]
    unknown = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk(host=None)))
    got, _ = pr.failover_routing(routing, unknown)
    assert got == {"order": ["baseten"], "allow_fallbacks": False, "max_price": routing["max_price"], "data_collection": "deny"}
    assert pr.failover_routing({"sort": "throughput"}, unknown) is None
    assert pr.failover_routing(None, unknown) is None


def test_responses_caller_never_sees_failure_details():
    done = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk()))
    shown = ra.rebrand_responses(done, "kael-beta")
    for key in ("served_by", "upstream_error", "upstream_finish_reason"):
        assert key not in shown
    assert "CoreWeave" not in json.dumps(shown)


# ----------------------------------------------- data policy (2026-10-13)
def test_every_upstream_routing_object_denies_data_collection():
    from app.models.kael import config as kael_config
    from app.models.kael.config import KAEL_PRO_BETA
    for model in (MODEL, KAEL_PRO_BETA):
        for key in ("draft_provider_routing", "critic_provider_routing", "fusor_provider_routing", "summarizer_provider_routing"):
            assert model[key].get("data_collection") == "deny", (model["key"], key)
    # The four objects sit in _SHARED and both models spread it: no model carries its own copy to forget.
    assert all(kael_config._SHARED[k].get("data_collection") == "deny" for k in (
        "draft_provider_routing", "critic_provider_routing", "fusor_provider_routing", "summarizer_provider_routing"))


def test_the_data_policy_reaches_the_request_body_and_survives_every_retry_path():
    routing = MODEL["draft_provider_routing"]
    body = ra.build_chat_completions_body(
        provider="openrouter", model="m", input_items=[{"role": "user", "content": "hi"}], tools=None,
        reasoning_effort="low", max_output_tokens=10, system_identity="x", trailing_messages=[], stream=False,
        provider_routing=routing, session_id="kael-abc",
    )
    assert body["provider"]["data_collection"] == "deny"
    # the backup-host retry
    assert pr.fallback_routing(routing)["data_collection"] == "deny"
    # the mid-stream failover, with and without a known failed host
    known = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk()))
    assert pr.failover_routing(routing, known)[0]["data_collection"] == "deny"
    unknown = ra.cc_accumulator_to_responses_shape(ra.accumulate_cc_chunk(ra.new_cc_accumulator(), _err_chunk(host=None)))
    assert pr.failover_routing(routing, unknown)[0]["data_collection"] == "deny"
    # zero-data-retention, if it is ever added to a pass, is carried too
    assert pr.fallback_routing({**routing, "zdr": True})["zdr"] is True


def test_the_data_policy_switch_only_turns_off_on_an_explicit_false():
    import importlib
    import os
    from app.models.kael import config as kael_config
    saved = os.environ.get("UPSTREAM_REQUIRE_NO_DATA_COLLECTION")
    try:
        for value, expected in (("false", False), ("0", False), ("No", False), ("off", False),
                                ("true", True), ("", True), ("flase", True), ("maybe", True)):
            os.environ["UPSTREAM_REQUIRE_NO_DATA_COLLECTION"] = value
            importlib.reload(kael_config)
            assert ("data_collection" in kael_config._SHARED["draft_provider_routing"]) is expected, value
        del os.environ["UPSTREAM_REQUIRE_NO_DATA_COLLECTION"]
        importlib.reload(kael_config)
        assert kael_config._SHARED["summarizer_provider_routing"]["data_collection"] == "deny"  # default is ON
    finally:
        if saved is None:
            os.environ.pop("UPSTREAM_REQUIRE_NO_DATA_COLLECTION", None)
        else:
            os.environ["UPSTREAM_REQUIRE_NO_DATA_COLLECTION"] = saved
        importlib.reload(kael_config)


def test_unexpected_exceptions_are_logged_by_type_only():
    secret = "my secret prompt text"
    for exc in (ValueError(f"invalid literal for int(): {secret!r}"), KeyError(secret), RuntimeError(secret)):
        summary = pr.safe_exception_summary(exc)
        assert secret not in summary
        assert summary == type(exc).__name__


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print(f"{len(tests)} passed")
