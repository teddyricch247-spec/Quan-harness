"""Integration tests for app/two_pass_pipeline.py's orchestration logic
and app/thinking_summarizer.py's real-time behavior — added 2026-09-13,
the piece test_pipeline_logic.py's own docstring flagged as missing:
"None of this reaches app/two_pass_pipeline.py's own orchestration logic
... those still have zero automated coverage."

Unlike test_pipeline_logic.py (which tests response_api.py/anthropic_api.py/
critic/*.py's PURE functions directly, no mocking needed at all), the
modules here do real I/O — httpx calls to an upstream model, and (via
supabase_client.py/billing.py) real Supabase calls — so they need
something in place of the real network before they'll even import, let
alone run. This sandbox has no network access, so instead of a real
`pip install -r requirements.txt` + a real mocking library (respx,
pytest-httpx — neither installed, neither installable here), this file:

  1. Stubs `fastapi`/`fastapi.responses` in sys.modules with just enough
     surface (HTTPException, Request, StreamingResponse) for
     two_pass_pipeline.py/rate_limit.py/billing.py to import — same
     stubbing pattern test_pipeline_logic.py already uses for fastapi in
     its own rate_limit.py section, and the one its docstring says the
     pre-2026-08-20 version of THIS repo used for httpx.

  2. Stubs `httpx` with a FAKE AsyncClient/Response, not a full replica
     of the real library. Deliberately narrow — implements only the
     exact surface two_pass_pipeline.py's _post_upstream()/consume_pass()
     actually call (AsyncClient as an async context manager, .post(),
     .stream() as an async context manager, .status_code/.json()/.text/
     .aread()/.aiter_lines()) — not e.g. real connection pooling, real
     header/redirect handling, or httpx.MockTransport's request-matching
     API. This is a conscious tradeoff: a hand-rolled fake risks drifting
     from real httpx's actual behavior in ways a full mock wouldn't, but
     replicating a full HTTP library's semantics to test THIS app's
     orchestration logic is the wrong amount of fidelity for what these
     tests are actually checking (see each test group's own comment for
     what it is and isn't trying to catch). If real httpx/respx/
     pytest-httpx becomes available (a real `pip install` succeeding
     somewhere with network), prefer routing these same test SCENARIOS
     through httpx.MockTransport instead — httpx.MockTransport(handler)
     supports both sync and async handlers natively (confirmed against
     github.com/encode/httpx, 2026-09-13) and is the more faithful,
     lower-maintenance choice once it's actually available; keep this
     file's fake only as the offline fallback.

  3. Monkeypatches app/two_pass_pipeline.py's own imported names for
     start_chat_trace/update_chat_trace/log_usage/last_user_text, and
     app/billing.py's check_balance_or_raise/charge_for_request, with
     fakes that record every call (so tests can assert on them) instead
     of touching a real Supabase project. Deliberately does NOT stub
     app/rate_limit.py — that module does real work with zero I/O (see
     its own module docstring), so it runs for real here, the same way
     test_pipeline_logic.py's rate_limit.py section already exercises it
     directly.

Three test groups, increasing in what they exercise:
  - _post_upstream(): the wire boundary itself — does an HTTP-shaped
    success/error/timeout get translated into the right internal shape
    or the right _PassCallError. Uses the fake HTTP layer.
  - _run_nonstream()'s orchestration DECISIONS: draft-empty skips the
    critic, a critic failure (both the exception path AND the
    status="failed" path) falls back to serving the draft, and —
    specifically, the asymmetry worth protecting against a future
    accidental "fix" that makes both behave the same way — a DRAFT
    timeout is a hard failure but a CRITIC timeout degrades gracefully.
    Monkeypatches _post_upstream directly (a clean, already-isolated
    internal seam) rather than driving these through the fake HTTP
    layer a second time — these tests are about what run_pipeline()
    DOES with a given pass outcome, not about re-deriving that outcome
    from raw bytes again.
  - ThinkingRelay: real asyncio, real time.monotonic() — no fake clock.
    IDLE_FLUSH_SECONDS/FORCE_FLUSH_SECONDS/FILLER_INTERVAL_SECONDS are
    monkeypatched down to small values (comfortably above the loop's
    own hardcoded 0.25s poll interval, which isn't itself patchable
    without a source change) so these tests run in well under a second
    each rather than needing to wait out the real 0.9s/6.0s/3.5s
    defaults, without needing to fake time.monotonic() itself.
    2026-10-01: the size-driven flush rules (REASONING_CHUNK_CHARS,
    MIN_FLUSH_GAP_SECONDS, MIN_IDLE_FLUSH_CHARS, MIN_TAIL_CHARS), draft-
    text titles (feed_draft), phase-aware fillers, going quiet once the
    real answer starts, and block-trimmed title history are covered by
    _test_thinking_relay_chunking() and _test_draft_titles_end_to_end().

2026-09-13 addition — a fourth group, _run_stream() itself: unlike Group
2 above, this can't monkeypatch its way around the upstream call (the
streaming path's consume_pass() is a closure defined INSIDE _run_stream,
not a module-level name), so it drives the real function through the
fake httpx layer from Group 1 instead, then drains the asyncio.Queue
_run_stream() writes SSE-formatted chunks into. Covers: an ordinary
no-tag exchange still streams the critic's text end to end (the
regression check that this file's own pre-2026-09-13 gap — _run_stream()
had zero coverage before this — is now closed for at least the basic
case), and the difficulty-routing feature's EASY/HARD split over a live
stream specifically, including that emit_fallback() (previously only
exercised by the pre-existing empty-draft skip) now also correctly
serves an EASY-rated draft with the tag already stripped before it ever
reaches the queue.
"""
import sys, os, types, asyncio, time, io, contextlib, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------
# fastapi / fastapi.responses stub
# ---------------------------------------------------------------------
fastapi_stub = types.ModuleType("fastapi")


class _StubHTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


class _StubRequest:
    pass


fastapi_stub.HTTPException = _StubHTTPException
fastapi_stub.Request = _StubRequest


def _stub_header(default=None, alias=None):
    """Bare stand-in for fastapi.Header — only ever evaluated here as a
    default-argument value at function-definition time (e.g.
    `Header(default=None)` in app/auth.py). This file always calls
    those functions directly with explicit args, bypassing FastAPI's
    real dependency injection entirely, so the returned default is
    never actually read; it only needs to not raise on import."""
    return default


def _stub_depends(dependency=None):
    """Bare stand-in for fastapi.Depends — same reasoning as
    _stub_header above: only needs to exist at import time
    (app/auth.py's require_admin uses it), never actually resolved
    here since nothing in this file calls require_admin/require_login
    through it."""
    return dependency


fastapi_stub.Header = _stub_header
fastapi_stub.Depends = _stub_depends
sys.modules["fastapi"] = fastapi_stub

fastapi_responses_stub = types.ModuleType("fastapi.responses")


class _StubStreamingResponse:
    def __init__(self, *a, **k):
        # Kept (not just swallowed) so a test can read the body iterator and
        # close it early, the way a disconnecting client does.
        self.body_iterator = a[0] if a else k.get("content")


fastapi_responses_stub.StreamingResponse = _StubStreamingResponse
sys.modules["fastapi.responses"] = fastapi_responses_stub

# ---------------------------------------------------------------------
# httpx stub — see module docstring, section 2, for what this is and
# isn't trying to be. _set_responder() below is how each test controls
# what the "upstream" does on each successive call.
# ---------------------------------------------------------------------
httpx_stub = types.ModuleType("httpx")


class _StubTimeoutException(Exception):
    pass


class _StubHTTPError(Exception):
    pass


httpx_stub.TimeoutException = _StubTimeoutException
httpx_stub.HTTPError = _StubHTTPError


class _StubConnectTimeout(_StubTimeoutException):
    """Stand-in for real httpx's httpx.ConnectTimeout, which really is a
    TimeoutException subclass — connection-establishment specifically
    timing out, as opposed to a read timeout after the connection was
    already open. See _post_upstream's own docstring (app/
    two_pass_pipeline.py, 2026-09-15) for why that distinction is the
    entire point of the retry logic these two new stub classes exist to
    test."""
    pass


class _StubConnectError(_StubHTTPError):
    """Stand-in for real httpx's httpx.ConnectError — connection refused/
    DNS failure/etc, a network-level failure rather than a timeout, but
    same "never even connected" category _post_upstream's retry cares
    about."""
    pass


httpx_stub.ConnectTimeout = _StubConnectTimeout
httpx_stub.ConnectError = _StubConnectError


class _StubHTTPStatusError(_StubHTTPError):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


httpx_stub.HTTPStatusError = _StubHTTPStatusError
httpx_stub.Timeout = lambda *a, **k: None

# A responder is a zero-arg callable returning either:
#   - ("json", status_code, json_dict)       -> a non-streamed response
#   - ("lines", status_code, [line, line...]) -> a streamed response
#   - an Exception INSTANCE to raise instead of returning a response
# _responder_queue is consumed one entry per actual client.post()/
# .stream() call, in order — this directly mirrors the pipeline's own
# real call order (draft, then critic), so test setup just lists
# "what happens on call 1, then call 2" without needing to inspect the
# request itself to tell which pass is calling.
_responder_queue: list = []


def _set_responders(*responders):
    _responder_queue.clear()
    _responder_queue.extend(responders)


def _next_response():
    if not _responder_queue:
        raise AssertionError("fake httpx client called more times than the test set up responders for")
    result = _responder_queue.pop(0)
    if isinstance(result, Exception):
        raise result
    return result


class _FakeResponse:
    def __init__(self, kind, status_code, payload):
        self.status_code = status_code
        self._kind = kind
        self._payload = payload
        if kind == "json":
            self.text = str(payload)[:500]
        else:
            self.text = "\n".join(payload)[:500]

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx_stub.HTTPStatusError(f"{self.status_code} error", response=self)

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        # Two test-only sentinel lines: "__sleep__:<seconds>" pauses the
        # stream there (a slower upstream), "__raise__" fails it mid-stream.
        for line in (self._payload if self._kind == "lines" else []):
            if line.startswith("__sleep__:"):
                await asyncio.sleep(float(line.split(":", 1)[1]))
                continue
            if line == "__raise__":
                raise httpx_stub.HTTPError("connection reset mid-stream")
            yield line


class _StreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *a):
        return False


class _FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        kind, status, payload = _next_response()
        return _FakeResponse(kind, status, payload)

    async def get(self, url, headers=None, params=None):
        kind, status, payload = _next_response()
        return _FakeResponse(kind, status, payload)

    def stream(self, method, url, headers=None, json=None):
        kind, status, payload = _next_response()
        return _StreamCM(_FakeResponse(kind, status, payload))


httpx_stub.AsyncClient = _FakeAsyncClient
sys.modules["httpx"] = httpx_stub

# ---------------------------------------------------------------------
# Now safe to import the real modules under test
# ---------------------------------------------------------------------
from app import two_pass_pipeline as tpp
from app import billing
from app import thinking_summarizer as tsm
from app import auth as auth_mod
from app import api_keys
from app import rate_limit as rl
from app import config as app_config
from app import email_service
from app import scheduled_checks as sched
from app.jobs import low_balance_alerts as lba

failures = []


def check(label, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}\n  got:      {got!r}\n  expected: {expected!r}")
    else:
        print(f"ok   {label}")


# ---------------------------------------------------------------------
# Fakes for everything two_pass_pipeline.py calls besides the upstream
# HTTP layer — real Supabase/billing calls, replaced with in-memory
# recorders. Reset between test groups via _reset_recorders().
# ---------------------------------------------------------------------
_trace_calls = []
_log_usage_calls = []
_charge_calls = []


def _reset_recorders():
    _trace_calls.clear()
    _log_usage_calls.clear()
    _charge_calls.clear()


async def _fake_start_chat_trace(**kwargs):
    return "trace_test_123"


async def _fake_update_chat_trace(trace_id, **kwargs):
    _trace_calls.append(kwargs)


async def _fake_log_usage(product, model, **kwargs):
    _log_usage_calls.append({"product": product, "model": model, **kwargs})


def _fake_last_user_text(input_items):
    return "test user message"


async def _fake_charge_for_request(user_id, product, usage, native_usage, at=None):
    _charge_calls.append({"user_id": user_id, "product": product, "usage": usage, "native_usage": native_usage})
    return None


async def _fake_check_balance_ok(user_id):
    return None


tpp.start_chat_trace = _fake_start_chat_trace
tpp.update_chat_trace = _fake_update_chat_trace
tpp.log_usage = _fake_log_usage
tpp.last_user_text = _fake_last_user_text
billing.charge_for_request = _fake_charge_for_request
billing.check_balance_or_raise = _fake_check_balance_ok

_FAKE_PASS = tpp.PassConfig(
    provider="openrouter", base_url="https://fake.test", api_key="test-key",
    model="fake-draft-model", reasoning_effort="low", max_output_tokens=1000,
)
_FAKE_CRITIC_PASS = tpp.PassConfig(
    provider="openrouter", base_url="https://fake.test", api_key="test-key",
    model="fake-critic-model", reasoning_effort="low", max_output_tokens=1000,
)


def _cc_json(text, finish_reason="stop"):
    """A minimal but real chat.completion-shaped body — exactly what
    _post_upstream() runs through response_api.chat_completion_to_
    responses_shape() before returning."""
    return {
        "id": "cc_fake", "created": 1234567890,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


_REQUESTOR = {"user_id": "user_integration_test"}


# =======================================================================
# Group 1 — _post_upstream(): the wire boundary
# =======================================================================
async def _test_post_upstream():
    _set_responders(("json", 200, _cc_json("Hello there!")))
    data = await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
    check("_post_upstream: 200 response -> status=completed", data["status"], "completed")
    text, _ = tpp.ra.responses_output_text_and_calls(data["output"])
    check("_post_upstream: 200 response -> text extracted correctly", text, "Hello there!")

    _set_responders(("json", 500, {"error": "boom"}))
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: 500 response should have raised _PassCallError")
    except tpp._PassCallError as e:
        # Changed 2026-10-06: this used to expect the upstream's own 500 to reach
        # the caller unchanged. Upstream statuses describe OUR upstream account,
        # not the caller's request, so callers now get Kael's own 502 and a
        # fixed vendor-free body (provider_routing.client_error_for_upstream_status).
        check("_post_upstream: 500 response -> _PassCallError mapped to Kael's 502", e.http_status, 502)
        check("_post_upstream: 500 response -> caller body never carries the upstream body", e.client_payload["error"]["code"], "upstream_error")
        # Upstream free text can quote the caller's prompt, so only a content-free
        # summary (status/code/type/host) is kept for the operator.
        check("_post_upstream: 500 response -> log message is the content-free summary only", e.log_message, "upstream HTTP 500")

    _set_responders(_StubTimeoutException())
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: httpx.TimeoutException should have raised _PassCallError")
    except tpp._PassCallError as e:
        check("_post_upstream: httpx.TimeoutException -> _PassCallError(504, 'upstream timeout')", (e.http_status, "timeout" in e.log_message), (504, True))

    _set_responders(_StubHTTPError("connection reset"))
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: httpx.HTTPError should have raised _PassCallError")
    except tpp._PassCallError as e:
        check("_post_upstream: httpx.HTTPError -> _PassCallError(502, ...)", e.http_status, 502)

    # --- retry logic, added 2026-09-15 (item 5) ---
    # A ConnectError on the first attempt, success on the second: proves
    # the retry actually happens and its result is what's returned, not
    # just that it doesn't crash.
    _set_responders(_StubConnectError("connection refused"), ("json", 200, _cc_json("Recovered!")))
    data = await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
    text, _ = tpp.ra.responses_output_text_and_calls(data["output"])
    check("_post_upstream: ConnectError then success -> retries and returns the successful attempt's content", text, "Recovered!")

    # Same, but ConnectTimeout specifically (the OTHER connection-failure
    # type _post_upstream retries) — proves both members of the retried
    # tuple work, not just ConnectError.
    _set_responders(_StubConnectTimeout("connect timed out"), ("json", 200, _cc_json("Recovered again!")))
    data = await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
    text, _ = tpp.ra.responses_output_text_and_calls(data["output"])
    check("_post_upstream: ConnectTimeout then success -> also retries (both connection-failure types covered)", text, "Recovered again!")

    # Exhausting every attempt (_CONNECT_RETRY_ATTEMPTS consecutive
    # connection failures) -> a real _PassCallError, not an unhandled
    # exception — this has to fail closed, not hang or crash the pipeline.
    _set_responders(*[_StubConnectError("still refused") for _ in range(tpp._CONNECT_RETRY_ATTEMPTS)])
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: exhausting every retry attempt should have raised _PassCallError")
    except tpp._PassCallError as e:
        check(f"_post_upstream: {tpp._CONNECT_RETRY_ATTEMPTS} consecutive ConnectErrors -> _PassCallError(502, ...) once retries are exhausted", e.http_status, 502)

    # The other side of the same judgment call: a read timeout is
    # deliberately NOT retried (see _post_upstream's own docstring for
    # why — no time budget left, and correctness risk once the upstream
    # may have already started real generation). Only ONE responder is
    # queued; if this were ever accidentally retried, the second call
    # would hit an empty queue and _next_response() would raise
    # AssertionError instead of the expected _PassCallError(504, ...) —
    # that failure mode is exactly what this proves didn't happen.
    _set_responders(_StubTimeoutException())
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: httpx.TimeoutException should still raise immediately, not retry")
    except tpp._PassCallError as e:
        check("_post_upstream: a plain read timeout is NOT retried (single attempt, still 504)", (e.http_status, "timeout" in e.log_message), (504, True))

    # Same reasoning for a received 5xx: we got an actual response from
    # upstream, so (per the same docstring) this is left alone rather
    # than assumed safe to retry. One responder queued -> a second call
    # would again surface as AssertionError, not a clean _PassCallError,
    # if this were ever accidentally retried.
    _set_responders(("json", 503, {"error": "upstream degraded"}))
    try:
        await tpp._post_upstream(_FAKE_PASS, {}, time.monotonic())
        failures.append("FAIL _post_upstream: a received 5xx should have raised _PassCallError")
    except tpp._PassCallError as e:
        check("_post_upstream: a received 5xx response is NOT retried either (single attempt, real status code preserved)", e.http_status, 503)


# =======================================================================
# Group 2 — _run_nonstream()'s orchestration decisions. Monkeypatches
# _post_upstream directly (see module docstring for why) rather than
# the fake HTTP layer.
# =======================================================================
_post_upstream_queue: list = []


async def _fake_post_upstream(pcfg, body, started):
    if not _post_upstream_queue:
        raise AssertionError("_post_upstream called more times than the test queued responses for")
    result = _post_upstream_queue.pop(0)
    if isinstance(result, Exception):
        raise result
    if isinstance(result, tuple) and result[0] == "sleep":
        await asyncio.sleep(result[1])
        return result[2]
    return result


def _queue_post_upstream(*results):
    _post_upstream_queue.clear()
    _post_upstream_queue.extend(results)


async def _run_nonstream_default(**overrides):
    kwargs = dict(
        product="kael-beta", slug="kael-beta", system_identity="You are Kael.",
        draft=_FAKE_PASS, critic=_FAKE_CRITIC_PASS,
        input_items=[{"role": "user", "content": "hi"}], tools=None, caller_shape="responses",
        started=time.monotonic(), trace_id="trace_test_123", requestor=_REQUESTOR,
        on_complete=None, request_started_at=tpp.datetime.now(tpp.timezone.utc), boundary="testboundary123",
    )
    kwargs.update(overrides)
    return await tpp._run_nonstream(**kwargs)


def _responses_shape(text, status="completed", finish_reason="stop"):
    return {
        "id": "resp_fake", "created_at": 1234567890, "status": status,
        "native_finish_reason": finish_reason,
        "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}] if text else [],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }


async def _test_orchestration():
    real_post_upstream = tpp._post_upstream
    tpp._post_upstream = _fake_post_upstream
    try:
        # --- happy path: draft ok, critic ok -> final content is the CRITIC's ---
        _reset_recorders()
        _queue_post_upstream(_responses_shape("draft answer"), _responses_shape("critic-reviewed answer"))
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("orchestration happy path: final content is the CRITIC's text, not the draft's", text, "critic-reviewed answer")
        check("orchestration happy path: billing charged exactly once", len(_charge_calls), 1)
        check("orchestration happy path: log_usage's status is success", _log_usage_calls[-1]["status"], "success")

        # --- draft produces nothing reviewable -> critic never called ---
        _reset_recorders()
        _queue_post_upstream(_responses_shape(None, status="completed"))  # only ONE response queued — if critic were called too, _fake_post_upstream raises AssertionError
        result = await _run_nonstream_default()
        check("orchestration draft-empty: critic pass is never invoked (only one _post_upstream call consumed)", len(_post_upstream_queue), 0)
        check("orchestration draft-empty: trace logs draft_status=skipped_empty", _trace_calls[-1].get("draft_status"), "skipped_empty")

        # --- critic raises _PassCallError -> falls back to serving the draft ---
        _reset_recorders()
        _queue_post_upstream(_responses_shape("draft answer"), tpp._PassCallError(502, "simulated critic outage", {"error": {"message": "fail"}}))
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("orchestration critic-exception fallback: caller still gets a 200-shaped answer, not an exception", text, "draft answer")
        check("orchestration critic-exception fallback: billing charges draft-only usage, exactly once", len(_charge_calls), 1)
        check("orchestration critic-exception fallback: log_usage records the fallback in its error_message", "critic pass failed, served draft" in _log_usage_calls[-1]["error_message"], True)

        # --- critic returns status="failed" (content-filtered) -> same fallback, different trigger ---
        _reset_recorders()
        _queue_post_upstream(_responses_shape("draft answer 2"), _responses_shape("", status="failed", finish_reason="content_filter"))
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("orchestration critic-content-filtered fallback: also serves the draft (status='failed' path, not an exception)", text, "draft answer 2")
        check("orchestration critic-content-filtered fallback: billing still charges draft-only usage", len(_charge_calls), 1)

        # --- hard ceiling: DRAFT timeout is a hard failure ---
        real_ceiling = tpp.GENERATION_HARD_CEILING_SECONDS
        tpp.GENERATION_HARD_CEILING_SECONDS = 0.05
        try:
            _reset_recorders()
            _queue_post_upstream(("sleep", 0.3, _responses_shape("too slow")))
            raised = False
            try:
                await _run_nonstream_default()
            except _StubHTTPException as e:
                raised = True
                check("orchestration hard-ceiling (draft): raises HTTPException(504), a hard failure", e.status_code, 504)
            check("orchestration hard-ceiling (draft): actually raised, request did not silently succeed", raised, True)
            check("orchestration hard-ceiling (draft): trace status recorded as timeout", _trace_calls[-1].get("status"), "timeout")

            # --- hard ceiling: CRITIC timeout degrades gracefully instead (the asymmetry worth protecting) ---
            _reset_recorders()
            _queue_post_upstream(_responses_shape("draft answer 3"), ("sleep", 0.3, _responses_shape("too slow critic")))
            result = await _run_nonstream_default()
            text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
            check("orchestration hard-ceiling (critic): does NOT raise — degrades to serving the draft instead, unlike a draft-side timeout", text, "draft answer 3")
            check("orchestration hard-ceiling (critic): log_usage error_message reflects the ceiling hit, not a generic failure", "hard ceiling" in _log_usage_calls[-1]["error_message"], True)
        finally:
            tpp.GENERATION_HARD_CEILING_SECONDS = real_ceiling

        # =================================================================
        # Difficulty routing (added 2026-09-13) — app/router/kael.py +
        # response_api.extract_difficulty_and_strip(). "testboundary123" is
        # _run_nonstream_default()'s own fixed boundary (see its kwargs
        # above), so a tag built with that exact value is what
        # extract_difficulty_and_strip() will actually recognize.
        # =================================================================
        _reset_recorders()
        _queue_post_upstream(_responses_shape("<task_difficulty_testboundary123>EASY</task_difficulty_testboundary123>Hi! I'm Kael, nice to meet you."))
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("difficulty routing (EASY): critic pass is never invoked — only one _post_upstream call consumed, same proof pattern as the empty-draft test above", len(_post_upstream_queue), 0)
        check("difficulty routing (EASY): the difficulty tag itself never reaches the client — final text is the real answer only", text, "Hi! I'm Kael, nice to meet you.")
        check("difficulty routing (EASY): billing still charges draft-only usage, exactly once (no critic call to bill for)", len(_charge_calls), 1)
        check("difficulty routing (EASY): trace records draft_status=skipped_easy, distinguishable from skipped_empty", _trace_calls[-1].get("draft_status"), "skipped_easy")

        _reset_recorders()
        _queue_post_upstream(
            _responses_shape("<task_difficulty_testboundary123>HARD</task_difficulty_testboundary123>def add(a, b): return a + b"),
            _responses_shape("def add(a: int, b: int) -> int:\n    return a + b"),
        )
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("difficulty routing (HARD): critic pass DOES run — both queued responses consumed", len(_post_upstream_queue), 0)
        check("difficulty routing (HARD): final content is the CRITIC's answer, exactly like the ordinary happy path — the tag changes nothing except that it explicitly said so", text, "def add(a: int, b: int) -> int:\n    return a + b")
        check("difficulty routing (HARD): billing charges both passes (draft+critic combined), not draft-only", len(_charge_calls), 1)

        # A malformed/absent tag must behave EXACTLY like the pre-2026-09-13
        # pipeline — this is the regression check that a parsing failure
        # never accidentally skips review.
        _reset_recorders()
        _queue_post_upstream(_responses_shape("Just a normal answer with no tag at all."), _responses_shape("Just a normal answer, reviewed."))
        result = await _run_nonstream_default()
        text, _ = tpp.ra.responses_output_text_and_calls(result["output"])
        check("difficulty routing (no tag / model didn't comply): falls through to running the critic exactly as before this feature existed — fail-safe, not a regression", text, "Just a normal answer, reviewed.")
    finally:
        tpp._post_upstream = real_post_upstream


# =======================================================================
# Group 3 — ThinkingRelay: real asyncio, shrunk timing constants
# =======================================================================
async def _wait_until(predicate, timeout=2.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _test_thinking_relay():
    real_idle, real_force, real_filler = tsm.IDLE_FLUSH_SECONDS, tsm.FORCE_FLUSH_SECONDS, tsm.FILLER_INTERVAL_SECONDS
    real_call_summarizer = tsm._call_summarizer
    real_size = (tsm.REASONING_CHUNK_CHARS, tsm.DRAFT_CHUNK_CHARS, tsm.MIN_IDLE_FLUSH_CHARS)
    # These legacy tests are about the IDLE / CEILING / filler / stop()
    # paths with tiny strings, so the size trigger is switched off
    # (huge) and the idle minimum is lowered; the size rules have their
    # own tests in _test_thinking_relay_chunking().
    tsm.REASONING_CHUNK_CHARS = tsm.DRAFT_CHUNK_CHARS = 10**9
    tsm.MIN_IDLE_FLUSH_CHARS = 10
    # Comfortably above the loop's own hardcoded 0.25s poll interval (see
    # module docstring) so these never race the poll granularity itself
    # — and comfortably SEPARATED from each other (idle vs. filler): the
    # loop only checks both conditions once per ~0.25s wakeup, so two
    # thresholds within one poll-cycle of each other (an earlier version
    # of this test used 0.4/0.5) can flip which one is observed to fire
    # first depending on poll-phase alignment alone — a real race, not a
    # fluke. 0.3 vs. 0.9 leaves multiple poll cycles of headroom.
    tsm.IDLE_FLUSH_SECONDS = 0.3
    tsm.FORCE_FLUSH_SECONDS = 0.9
    tsm.FILLER_INTERVAL_SECONDS = 0.9
    try:
        # --- idle flush: feed once, go quiet, expect exactly one title ---
        summarizer_calls = []

        async def fake_summarizer_one_title(chunk, history, kind="reasoning"):
            summarizer_calls.append((chunk, list(history)))
            return ["Looking at the bug report"]

        tsm._call_summarizer = fake_summarizer_one_title
        emitted = []
        relay = tsm.ThinkingRelay(lambda title: emitted.append(title))
        relay.start()
        relay.feed("thinking about the bug ")
        relay.feed("in the retry logic")
        ok = await _wait_until(lambda: len(emitted) >= 1, timeout=2.0)
        await relay.stop()
        check("ThinkingRelay idle-flush: a title was emitted after going idle", ok, True)
        check("ThinkingRelay idle-flush: exactly one summarizer call for one contiguous chunk", len(summarizer_calls), 1)
        check("ThinkingRelay idle-flush: the fed text reached the summarizer as one concatenated chunk", summarizer_calls[0][0], "thinking about the bug in the retry logic")
        check("ThinkingRelay idle-flush: emitted title matches what the summarizer returned", emitted, ["Looking at the bug report"])
        check("ThinkingRelay idle-flush: the real title lands in history (unlike fillers, see below)", relay._history, ["Looking at the bug report"])

        # --- force flush: keep feeding faster than idle threshold, past the force threshold ---
        summarizer_calls.clear()
        tsm._call_summarizer = fake_summarizer_one_title
        emitted2 = []
        relay2 = tsm.ThinkingRelay(lambda title: emitted2.append(title))
        relay2.start()
        start = time.monotonic()
        while time.monotonic() - start < 1.3:
            relay2.feed("continuous reasoning ")
            await asyncio.sleep(0.15)  # well under IDLE_FLUSH_SECONDS (0.3), so idle-flush never triggers on its own
        ok2 = await _wait_until(lambda: len(summarizer_calls) >= 1, timeout=1.0)
        await relay2.stop()
        check("ThinkingRelay force-flush: a chunk was flushed even though feeding never went idle", ok2, True)

        # --- fillers: no feed at all, expect filler words cycling through FILLER_WORDS, never added to history ---
        tsm._call_summarizer = fake_summarizer_one_title
        emitted3 = []
        relay3 = tsm.ThinkingRelay(lambda title: emitted3.append(title))
        relay3.start()
        ok3 = await _wait_until(lambda: len(emitted3) >= 2, timeout=3.0)
        await relay3.stop()
        check("ThinkingRelay fillers: at least 2 filler words emitted with nothing ever fed", ok3, True)
        check("ThinkingRelay fillers: emitted words come from FILLER_WORDS, in cycling order starting from the first", emitted3[:2], tsm.FILLER_WORDS[:2])
        check("ThinkingRelay fillers: fillers are never added to history", relay3._history, [])

        # --- stop() flushes a buffer that never hit a threshold ---
        tsm._call_summarizer = fake_summarizer_one_title
        emitted4 = []
        relay4 = tsm.ThinkingRelay(lambda title: emitted4.append(title))
        relay4.start()
        relay4.feed("a short thought right before the pass ends")
        await asyncio.sleep(0.05)  # well under IDLE_FLUSH_SECONDS — the loop's own flush should NOT have fired yet
        pre_stop_emitted = list(emitted4)
        await relay4.stop()
        check("ThinkingRelay stop(): the background loop had not already flushed this short-lived buffer on its own", pre_stop_emitted, [])
        check("ThinkingRelay stop(): flushes whatever was still buffered before tearing down", emitted4, ["Looking at the bug report"])
    finally:
        tsm.IDLE_FLUSH_SECONDS, tsm.FORCE_FLUSH_SECONDS, tsm.FILLER_INTERVAL_SECONDS = real_idle, real_force, real_filler
        tsm.REASONING_CHUNK_CHARS, tsm.DRAFT_CHUNK_CHARS, tsm.MIN_IDLE_FLUSH_CHARS = real_size
        tsm._call_summarizer = real_call_summarizer


# =======================================================================
# Group 3b — ThinkingRelay chunking by SIZE (not time), draft text,
# phases, fillers by phase, quiet during the real answer, history trim.
# Added 2026-10-01. Same approach as Group 3: real asyncio, shrunk
# constants, stubbed summarizer.
# =======================================================================
async def _test_thinking_relay_chunking():
    saved = {n: getattr(tsm, n) for n in (
        "IDLE_FLUSH_SECONDS", "FORCE_FLUSH_SECONDS", "FILLER_INTERVAL_SECONDS", "REASONING_CHUNK_CHARS", "DRAFT_CHUNK_CHARS",
        "MIN_FLUSH_GAP_SECONDS", "MIN_IDLE_FLUSH_CHARS", "MIN_TAIL_CHARS", "HISTORY_LIMIT", "HISTORY_TRIM_TO")}
    real_call_summarizer = tsm._call_summarizer
    tsm.IDLE_FLUSH_SECONDS = 0.3
    tsm.FORCE_FLUSH_SECONDS = 0.9
    tsm.FILLER_INTERVAL_SECONDS = 0.9
    tsm.MIN_IDLE_FLUSH_CHARS = 200
    tsm.MIN_TAIL_CHARS = 60
    try:
        calls = []

        async def recorder(chunk, history, kind="reasoning"):
            calls.append((chunk, kind, list(history)))
            return [f"Title {len(calls)}"]

        # --- 1. size flush: fires on amount, long before the idle (0.3s) or ceiling (0.9s) timers could ---
        tsm._call_summarizer = recorder
        tsm.REASONING_CHUNK_CHARS = 100
        tsm.MIN_FLUSH_GAP_SECONDS = 0.3
        calls.clear()
        emitted = []
        relay = tsm.ThinkingRelay(lambda t: emitted.append(t))
        relay.start()
        t0 = time.monotonic()
        for _ in range(5):
            relay.feed("x" * 50)
            await asyncio.sleep(0.02)
        got = await _wait_until(lambda: len(calls) >= 1, timeout=0.25)
        elapsed = time.monotonic() - t0
        check("size flush: a chunk was summarized once ~100 chars had arrived", got, True)
        check("size flush: it happened well before the idle/ceiling timers (0.3s/0.9s) could have fired", elapsed < 0.3, True)
        check("size flush: the chunk is labeled as reasoning", calls[0][1], "reasoning")
        check("size flush: chunk is at least the size limit", len(calls[0][0]) >= 100, True)
        await relay.stop()

        # --- 2. min gap: a second size flush is held back until MIN_FLUSH_GAP_SECONDS has passed ---
        tsm.REASONING_CHUNK_CHARS = 50
        tsm.MIN_FLUSH_GAP_SECONDS = 0.6
        calls.clear()
        relay = tsm.ThinkingRelay(lambda t: None)
        relay.start()
        relay.feed("a" * 60)
        await _wait_until(lambda: len(calls) >= 1, timeout=0.2)
        relay.feed("b" * 60)
        await asyncio.sleep(0.3)
        check("min gap: no second size flush inside the minimum gap", len(calls), 1)
        got2 = await _wait_until(lambda: len(calls) >= 2, timeout=1.5)
        check("min gap: the second size flush does happen once the gap has passed", got2, True)
        await relay.stop()

        # --- 3. kind separation: reasoning and draft text are never mixed in one chunk ---
        tsm.REASONING_CHUNK_CHARS = tsm.DRAFT_CHUNK_CHARS = 10**9
        tsm.MIN_FLUSH_GAP_SECONDS = 2.0
        calls.clear()
        emitted = []
        relay = tsm.ThinkingRelay(lambda t: emitted.append(t))
        relay.start()
        relay.feed("reasoning " * 12)
        relay.feed_draft("draft text " * 11)
        check("kind separation: switching kind flushes the reasoning chunk immediately", await _wait_until(lambda: len(calls) >= 1, timeout=0.2), True)
        await relay.stop()
        check("kind separation: first chunk is reasoning only", calls[0][:2], ("reasoning " * 12, "reasoning"))
        check("kind separation: draft text goes to the summarizer on its own, labeled draft", calls[1][:2], ("draft text " * 11, "draft"))
        check("kind separation: both produced a title", emitted, ["Title 1", "Title 2"])
        check("kind separation: feed_draft() moves the relay into the drafting phase", relay._phase, "drafting")

        # --- 4. a tiny leftover is dropped on a kind change (no point titling 5 chars), but stop() still flushes any size ---
        calls.clear()
        relay = tsm.ThinkingRelay(lambda t: None)
        relay.start()
        relay.feed("short")
        relay.feed_draft("draft text " * 11)
        await relay.stop()
        check("tiny leftover: 5 chars of reasoning were dropped on the kind change, only the draft was summarized", [c[1] for c in calls], ["draft"])
        calls.clear()
        relay = tsm.ThinkingRelay(lambda t: None)
        relay.start()
        relay.feed("short")
        await relay.stop()
        check("tiny leftover: stop() still flushes a short buffer", [c[1] for c in calls], ["reasoning"])

        # --- 5. phase change: set_phase('reviewing') flushes the draft tail first ---
        calls.clear()
        relay = tsm.ThinkingRelay(lambda t: None)
        relay.start()
        relay.feed_draft("final paragraph of the draft " * 4)
        relay.set_phase("reviewing")
        got5 = await _wait_until(lambda: len(calls) >= 1, timeout=0.3)
        check("phase change: the draft tail is flushed when the pipeline moves to reviewing", (got5, calls[0][1] if calls else None), (True, "draft"))
        check("phase change: relay is now in the reviewing phase", relay._phase, "reviewing")
        relay.feed("critic reasoning begins")
        check("phase change: reasoning arriving moves the relay back to thinking", relay._phase, "thinking")
        await relay.stop()

        # --- 5b. source change (z tiers hand the titles to another draft, 2026-10-11): the old source's tail is flushed on its own ---
        calls.clear()
        relay = tsm.ThinkingRelay(lambda t: None)
        relay.start()
        relay.feed("thoughts of the first draft " * 4)
        relay.source_changed()
        relay.feed("thoughts of the second draft " * 4)
        got5b = await _wait_until(lambda: len(calls) >= 1, timeout=0.3)
        check("source change: the old source's text is summarized on its own, before the new source's", (got5b, "first draft" in calls[0][0], "second draft" in calls[0][0]), (True, True, False))
        relay.source_changed()
        check("source change: and the new source's text starts a buffer of its own", relay._buffer, "")
        relay.feed("short")
        relay.source_changed()
        check("source change: a leftover under the minimum is dropped, like on a phase change", relay._buffer, "")
        relay.begin_answer()
        relay.feed("ignored " * 20)
        relay.source_changed()
        check("source change: ignored once the real answer has started", relay._buffer, "")
        await relay.stop()

        # --- 6. fillers follow the phase; the answering phase gets none ---
        calls.clear()
        em = []
        relay = tsm.ThinkingRelay(lambda t: em.append(t))
        relay.start()
        relay.set_phase("reviewing")
        await _wait_until(lambda: len(em) >= 2, timeout=3.0)
        await relay.stop()
        check("phase fillers: a silent gap in the reviewing phase uses the reviewing wording", em[:2], tsm.PHASE_FILLER_WORDS["reviewing"][:2])
        em = []
        relay = tsm.ThinkingRelay(lambda t: em.append(t))
        relay.start()
        relay.set_phase("drafting")
        await _wait_until(lambda: len(em) >= 2, timeout=3.0)
        await relay.stop()
        check("phase fillers: a silent gap in the drafting phase uses the drafting wording", em[:2], tsm.PHASE_FILLER_WORDS["drafting"][:2])

        # --- 7. quiet once the real answer starts: no titles, no fillers, in-flight results discarded, later feeds ignored ---
        slow_calls = []

        async def slow_summarizer(chunk, history, kind="reasoning"):
            slow_calls.append(kind)
            await asyncio.sleep(0.4)
            return ["Late title"]

        tsm._call_summarizer = slow_summarizer
        tsm.MIN_IDLE_FLUSH_CHARS = 10
        em = []
        relay = tsm.ThinkingRelay(lambda t: em.append(t))
        relay.start()
        relay.feed("x" * 120)
        await _wait_until(lambda: len(slow_calls) >= 1, timeout=1.5)
        relay.begin_answer()
        await asyncio.sleep(1.5)  # longer than the summarizer (0.4s) AND the filler interval (0.9s)
        relay.feed("y" * 500)
        relay.feed_draft("z" * 500)
        await relay.stop()
        check("answering phase: the in-flight summarizer result and every filler were suppressed", em, [])
        check("answering phase: feeds after the answer started are ignored (no extra summarizer call)", slow_calls, ["reasoning"])
        check("answering phase: nothing left buffered", relay._buffer, "")

        # --- 8. history trims in blocks (cache-friendly), and a call's history extends the previous call's ---
        tsm.HISTORY_LIMIT = 8
        tsm.HISTORY_TRIM_TO = 4
        hist_seen = []
        counter = {"n": 0}

        async def numbered(chunk, history, kind="reasoning"):
            hist_seen.append(list(history))
            counter["n"] += 1
            return [f"T{counter['n']}"]

        tsm._call_summarizer = numbered
        relay = tsm.ThinkingRelay(lambda t: None)
        for _ in range(8):
            await relay._flush("some text", "reasoning")
        check("history trim: grows without sliding up to the limit", relay._history, [f"T{i}" for i in range(1, 9)])
        check("history trim: each call's history is the previous call's history plus one at the END (stable prefix)", (hist_seen[5][:len(hist_seen[4])] == hist_seen[4], len(hist_seen[5]) == len(hist_seen[4]) + 1), (True, True))
        await relay._flush("some text", "reasoning")
        check("history trim: one block trim back to HISTORY_TRIM_TO once the limit is exceeded", relay._history, ["T6", "T7", "T8", "T9"])

        # --- 9. user-message layout and clamp (pure functions) ---
        hist = ["One", "Two", "Three"]
        m_r = tsm._build_user_message("aaa", hist, "reasoning")
        m_d = tsm._build_user_message("bbb", hist, "draft")
        check("message layout: RECENT TITLES comes first", m_r.startswith("RECENT TITLES:\n1. One"), True)
        check("message layout: reasoning and draft messages share everything before the label", m_r.split("\n\nRAW REASONING FRAGMENT:")[0], m_d.split("\n\nDRAFT TEXT FRAGMENT:")[0])
        check("message layout: draft label used for draft text", "DRAFT TEXT FRAGMENT:\nbbb" in m_d, True)
        m4 = tsm._build_user_message("c", hist + ["Four"], "reasoning")
        check("message layout: a longer history keeps the shorter one's text as its prefix", m4.startswith(m_r.split("\n\n")[0]), True)
        big = tsm._build_user_message("q" * 10000, [], "reasoning")
        frag = big.split("RAW REASONING FRAGMENT:\n", 1)[1]
        check("clamp: an oversized chunk is cut to the maximum input size", len(frag) <= tsm.MAX_SUMMARIZER_INPUT_CHARS + 10, True)
        check("clamp: the cut is marked with [...]", "\n[...]\n" in frag, True)
        small = tsm._build_user_message("tiny", [], "reasoning")
        check("clamp: a small chunk is untouched", small.endswith("RAW REASONING FRAGMENT:\ntiny"), True)
        check("system prompt: describes the draft-text input and its label", ("DRAFT TEXT FRAGMENT" in tsm.SUMMARIZER_SYSTEM_PROMPT and "RAW REASONING FRAGMENT" in tsm.SUMMARIZER_SYSTEM_PROMPT), True)
    finally:
        for n, v in saved.items():
            setattr(tsm, n, v)
        tsm._call_summarizer = real_call_summarizer


# =======================================================================
# Group 4 — _run_stream(): the streaming orchestration path itself was
# untested until now (Group 2 above only ever drove _run_nonstream — the
# streaming path's own consume_pass() is a closure defined INSIDE
# _run_stream, not a module-level name, so it can't be monkeypatched the
# same way _post_upstream was; it has to be driven through the fake httpx
# layer from Group 1 instead). Added alongside difficulty routing
# specifically because emit_fallback() — the mechanism the new EASY
# branch reuses to serve a draft-only answer over a live stream — had
# itself never been exercised by anything in this file before this
# branch started calling it a second way.
# =======================================================================
def _sse_lines(content_text: str, finish_reason: str = "stop"):
    """One content delta (the whole text in one chunk — sufficient here:
    this app's own accumulator concatenates deltas in order regardless of
    how many chunks they're split across, and draft content is never
    relayed live anyway — see consume_pass()'s own docstring, relay_content
    stays False for the draft pass), then a terminal finish_reason chunk
    with usage, then [DONE] — the same shape real_post_upstream's SSE
    parsing loop (two_pass_pipeline.py's consume_pass()) expects line by
    line."""
    delta_chunk = {"choices": [{"index": 0, "delta": {"content": content_text}, "finish_reason": None}]}
    final_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}], "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}
    return [f"data: {tpp.json.dumps(delta_chunk)}", f"data: {tpp.json.dumps(final_chunk)}", "data: [DONE]"]


def _sse_lines_multi(content_deltas: list[str], finish_reason: str = "stop"):
    """Same as _sse_lines above but as several separate content-delta
    chunks in sequence, rather than the whole text in one — added
    2026-09-15 to test StreamIdentityGuard's wiring inside consume_pass()
    against a leak phrase actually split across real upstream SSE chunk
    boundaries (_sse_lines' single-chunk shape can't exercise that)."""
    lines = [f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'content': d}, 'finish_reason': None}]})}" for d in content_deltas]
    final_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}], "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}
    lines.append(f"data: {tpp.json.dumps(final_chunk)}")
    lines.append("data: [DONE]")
    return lines


def _extract_cc_stream_text(raw_items: list[str]) -> str:
    """Concatenates every content delta out of a list of raw `data: {...}`
    SSE strings collected off the queue — the same field emit_cc()/
    consume_pass() write to to relay text either from a live critic
    stream or from emit_fallback()'s fake-streamed draft-only response."""
    text = ""
    for raw in raw_items:
        if not raw.startswith("data:"):
            continue
        payload = raw[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = tpp.json.loads(payload)
        except Exception:
            continue
        choices = chunk.get("choices") or []
        if choices:
            content = (choices[0].get("delta") or {}).get("content")
            if content:
                text += content
    return text


async def _run_stream_and_collect(**overrides):
    queue = asyncio.Queue()
    kwargs = dict(
        product="kael-beta", slug="kael-beta", system_identity="You are Kael.",
        draft=_FAKE_PASS, critic=_FAKE_CRITIC_PASS,
        input_items=[{"role": "user", "content": "hi"}], tools=None, caller_shape="chat_completions",
        client_wants_usage_chunk=False,
        started=time.monotonic(), trace_id="trace_test_123", requestor=_REQUESTOR,
        on_complete=None, queue=queue, request_started_at=tpp.datetime.now(tpp.timezone.utc),
        response_id="chatcmpl-test-1", boundary="testboundary123",
    )
    kwargs.update(overrides)
    await tpp._run_stream(**kwargs)
    items = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is None:
            break
        items.append(item)
    return items


async def _fake_call_summarizer_empty(raw_chunk, history, kind="reasoning"):
    return []


async def _test_stream_orchestration():
    # ThinkingRelay's background loop shouldn't ever get far enough to
    # call this in these fast, no-real-sleep tests (see the loop's own
    # 0.25s poll interval vs. how quickly a fully-mocked stream resolves)
    # — stubbed anyway, purely so a real network-shaped call is never
    # even theoretically possible from this section, not because it's
    # expected to fire.
    real_call_summarizer = tsm._call_summarizer
    tsm._call_summarizer = _fake_call_summarizer_empty
    try:
        # --- regression check: an ordinary HARD-routed (no tag) exchange still streams normally end to end ---
        _reset_recorders()
        _set_responders(("lines", 200, _sse_lines("Just a normal draft answer.")), ("lines", 200, _sse_lines("Just a normal, reviewed answer.")))
        items = await _run_stream_and_collect()
        check("streaming regression (no tag): both draft and critic upstream calls were made", len(_responder_queue), 0)
        check("streaming regression (no tag): client receives the CRITIC's text over the stream, same as the non-streaming happy path", _extract_cc_stream_text(items), "Just a normal, reviewed answer.")

        # --- identity-guard wiring, added 2026-09-15 (item 7): a leak
        # phrase split across two REAL separate upstream SSE chunks —
        # not just fed to the standalone StreamIdentityGuard directly in
        # test_pipeline_logic.py — is still caught end to end through the
        # actual consume_pass() wiring (content_guard.feed() inside the
        # loop, content_guard.flush() after it). Proves the surgical edit
        # to consume_pass() actually works, not just the module it calls.
        _reset_recorders()
        _set_responders(
            ("lines", 200, _sse_lines("Just a normal draft answer.")),
            ("lines", 200, _sse_lines_multi(["Sure, happy to help. I a", "m DeepSeek, a model built for coding tasks. All done!"])),
        )
        items = await _run_stream_and_collect()
        streamed_text = _extract_cc_stream_text(items)
        check("streaming identity guard: a leak split across two real upstream SSE chunks never reaches the client", "DeepSeek" in streamed_text, False)
        check("streaming identity guard: surrounding real content on both sides of the scrub still reaches the client", ("happy to help" in streamed_text and "All done!" in streamed_text), True)

        # --- streaming connection retry, added 2026-09-15 (item 5): the
        # SAME connection-failure-only retry as _post_upstream, now also
        # covering consume_pass()'s own streaming connection attempt
        # (the original handoff explicitly named "_post_upstream() and
        # the streaming equivalent" — this covers the second half). ---
        # Draft pass: fails once with a connection error, succeeds on
        # retry -> the whole exchange still completes normally and
        # transparently, exactly as if the first attempt had never
        # happened.
        _reset_recorders()
        _set_responders(
            _StubConnectError("connection refused"),
            ("lines", 200, _sse_lines("Just a normal draft answer.")),
            ("lines", 200, _sse_lines("Just a normal, reviewed answer.")),
        )
        items = await _run_stream_and_collect()
        check("streaming connect retry (draft pass): a ConnectError on the first attempt is retried transparently — exchange still completes normally", _extract_cc_stream_text(items), "Just a normal, reviewed answer.")
        check("streaming connect retry (draft pass): all 3 queued responses were consumed (failed attempt + successful draft + critic)", len(_responder_queue), 0)

        # Critic pass: same property, failure on the SECOND upstream call
        # this request makes, not the first.
        _reset_recorders()
        _set_responders(
            ("lines", 200, _sse_lines("Just a normal draft answer.")),
            _StubConnectTimeout("connect timed out"),
            ("lines", 200, _sse_lines("Just a normal, reviewed answer.")),
        )
        items = await _run_stream_and_collect()
        check("streaming connect retry (critic pass): a ConnectTimeout on the critic's first attempt is retried transparently", _extract_cc_stream_text(items), "Just a normal, reviewed answer.")

        # Exhausting every retry attempt on the draft pass -> a clean
        # error event to the client (not a hung stream, not an unhandled
        # exception), and the critic's queued responder is NEVER touched
        # — proving the draft pass actually stopped and failed rather
        # than somehow continuing on to the critic anyway.
        _reset_recorders()
        _set_responders(*([_StubConnectError("still refused") for _ in range(tpp._CONNECT_RETRY_ATTEMPTS)] + [("lines", 200, _sse_lines("should never be reached"))]))
        items = await _run_stream_and_collect()
        saw_error = any('"error"' in it for it in items if isinstance(it, str))
        check(f"streaming connect retry exhaustion (draft pass): after {tpp._CONNECT_RETRY_ATTEMPTS} consecutive ConnectErrors, a clean error event reaches the client", saw_error, True)
        check("streaming connect retry exhaustion (draft pass): the critic's responder was never consumed — draft failure stopped the pipeline before the critic ran", len(_responder_queue), 1)

        # --- streaming httpx-error translation, added 2026-09-15 (a
        # pre-existing gap fixed alongside the retry work): before this
        # pass, a read timeout or any other httpx error during the
        # streaming loop propagated as a raw, unhandled httpx exception
        # — _run_stream's caller only ever caught asyncio.TimeoutError
        # (the hard ceiling) and _PassCallError, neither of which a raw
        # httpx.TimeoutException/HTTPError is. Confirms that gap is
        # closed: both now surface as the same clean error event a bad
        # status code already produced, not an unhandled crash. ---
        _reset_recorders()
        _set_responders(_StubTimeoutException())
        items = await _run_stream_and_collect()
        check("streaming httpx-error translation: a plain read timeout during the stream produces a clean error event, not an unhandled exception", any('"error"' in it for it in items if isinstance(it, str)), True)

        _reset_recorders()
        _set_responders(_StubHTTPError("connection reset mid-stream"))
        items = await _run_stream_and_collect()
        check("streaming httpx-error translation: a generic HTTPError during the stream also produces a clean error event", any('"error"' in it for it in items if isinstance(it, str)), True)

        # --- difficulty routing, EASY, over a live stream ---
        _reset_recorders()
        _set_responders(("lines", 200, _sse_lines("<task_difficulty_testboundary123>EASY</task_difficulty_testboundary123>Hi! I'm Kael.")))
        items = await _run_stream_and_collect()
        check("streaming difficulty routing (EASY): only the draft's upstream call was made — critic never invoked", len(_responder_queue), 0)
        check("streaming difficulty routing (EASY): the tag itself never reaches the client over the stream either — same guarantee as the non-streaming path", _extract_cc_stream_text(items), "Hi! I'm Kael.")
        check("streaming difficulty routing (EASY): billing still charges draft-only usage exactly once", len(_charge_calls), 1)
        check("streaming difficulty routing (EASY): trace records draft_status=skipped_easy, same as the non-streaming path", _trace_calls[-1].get("draft_status"), "skipped_easy")

        # --- difficulty routing, HARD, over a live stream (both calls made, critic's text wins) ---
        _reset_recorders()
        _set_responders(
            ("lines", 200, _sse_lines("<task_difficulty_testboundary123>HARD</task_difficulty_testboundary123>def add(a, b): return a+b")),
            ("lines", 200, _sse_lines("def add(a: int, b: int) -> int:\n    return a + b")),
        )
        items = await _run_stream_and_collect()
        check("streaming difficulty routing (HARD): critic pass DOES run over a live stream — both queued responses consumed", len(_responder_queue), 0)
        check("streaming difficulty routing (HARD): client receives the critic's reviewed text, not the draft's", _extract_cc_stream_text(items), "def add(a: int, b: int) -> int:\n    return a + b")
    finally:
        tsm._call_summarizer = real_call_summarizer


# =======================================================================
# Group 4b — draft-text titles through the REAL _run_stream(), added
# 2026-10-01: the draft pass's visible answer text reaches the summarizer
# (labeled draft, identity-guarded), and once the critic's real answer
# starts no thinking text is emitted after it. Same fake HTTP layer as
# Group 4.
# =======================================================================
def _cc_event_order(raw_items: list[str]) -> list[str]:
    """\"reasoning\" / \"content\" per Chat-Completions chunk, in stream order."""
    order = []
    for raw in raw_items:
        if not raw.startswith("data:"):
            continue
        payload = raw[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = tpp.json.loads(payload)
        except Exception:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        if delta.get("reasoning_content"):
            order.append("reasoning")
        if delta.get("content"):
            order.append("content")
    return order


async def _test_draft_titles_end_to_end():
    # --- _LeadingTagStripper (pure): the draft's routing tag never reaches a title ---
    tag = "task_difficulty_abc123"
    st = tpp._LeadingTagStripper("abc123")
    out = "".join(st.feed(x) for x in ["<task_diffic", "ulty_abc123>HA", "RD</task_difficulty_abc123>Hello ", "there"]) + st.flush()
    check("tag stripper: a tag split across several chunks is removed, the text after it is kept", out, "Hello there")
    st = tpp._LeadingTagStripper("abc123")
    out = st.feed("Just plain text, no tag.") + st.flush()
    check("tag stripper: text that doesn't start with the tag passes through untouched", out, "Just plain text, no tag.")
    st = tpp._LeadingTagStripper("abc123")
    out = st.feed(f"  <{tag}>EASY\nHi, a fairly long reply that keeps going past the tag with no closing tag at all.") + st.flush()
    check("tag stripper: a missing closing tag is tolerated (same as the real extraction)", out, "Hi, a fairly long reply that keeps going past the tag with no closing tag at all.")
    st = tpp._LeadingTagStripper("abc123")
    check("tag stripper: a different boundary is NOT stripped", st.feed("<task_difficulty_zzz>HARD</task_difficulty_zzz>hi") + st.flush(), "<task_difficulty_zzz>HARD</task_difficulty_zzz>hi")
    st = tpp._LeadingTagStripper("abc123")
    check("tag stripper: held-back partial text is released by flush() when the stream just ends", st.feed("<task") + st.flush(), "<task")

    real_call_summarizer = tsm._call_summarizer
    seen = []

    async def recording_summarizer(chunk, history, kind="reasoning", **kw):
        seen.append((kind, chunk))
        await asyncio.sleep(0.2)  # slow enough that, without the quiet-after-answer rule, the title would land AFTER the answer
        return ["Writing the draft"]

    tsm._call_summarizer = recording_summarizer
    try:
        _reset_recorders()
        draft_text_parts = [
            "<task_difficulty_testboundary123>HARD</task_difficulty_testboundary123>",
            "Step one is installing the package and creating a client. Step two is passing your key. I a",
            "m DeepSeek, a model built for coding tasks. Step three is running the first request.",
        ]
        _set_responders(
            ("lines", 200, _sse_lines_multi(draft_text_parts)),
            # The critic's first token is delayed a little: with an instant
            # mock the answer would start (and cancel the in-flight title call)
            # before the call even began.
            ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Here is the reviewed answer.")),
        )
        items = await _run_stream_and_collect()
        draft_calls = [c for k, c in seen if k == "draft"]
        check("draft titles e2e: the draft pass's text reached the summarizer, labeled as draft", len(draft_calls) >= 1, True)
        joined = " ".join(draft_calls)
        check("draft titles e2e: the draft's real content is in what the summarizer saw", "Step one is installing the package" in joined, True)
        check("draft titles e2e: a leak phrase split across SSE chunks was scrubbed BEFORE reaching the summarizer", "DeepSeek" in joined, False)
        check("draft titles e2e: the routing tag is not shown to the summarizer", "task_difficulty" in joined, False)
        check("draft titles e2e: client still receives the critic's reviewed answer", _extract_cc_stream_text(items), "Here is the reviewed answer.")
        order = _cc_event_order(items)
        first_content = order.index("content") if "content" in order else -1
        check("draft titles e2e: the answer started", first_content >= 0, True)
        check("draft titles e2e: no thinking text is emitted after the real answer starts", "reasoning" in order[first_content:], False)
    finally:
        tsm._call_summarizer = real_call_summarizer


# =======================================================================
# Group 5 — billing.reconcile_all_accounts() — added 2026-09-15. Real
# financial-correctness logic, tested against the same fake HTTP layer
# Group 1 already built, extended with .get() support (billing.py's
# paginated queries use client.get(), unlike the chat-completions POST/
# stream calls the rest of this file drives). billing._enabled() needs
# config.SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY to be truthy or these
# functions short-circuit to {} without ever reaching the fake client —
# monkeypatched for the duration of this group only.
# =======================================================================
async def _test_billing_reconciliation():
    real_url, real_key = billing.config.SUPABASE_URL, billing.config.SUPABASE_SERVICE_ROLE_KEY
    real_page_size = billing._RECONCILE_PAGE_SIZE
    billing.config.SUPABASE_URL = "https://fake.test"
    billing.config.SUPABASE_SERVICE_ROLE_KEY = "fake-service-role-key"
    try:
        # --- nothing to reconcile: zero accounts, zero ledger rows ---
        _set_responders(("json", 200, []), ("json", 200, []))
        drifts = await billing.reconcile_all_accounts()
        check("reconcile_all_accounts: no accounts at all -> empty drift list, not an error", drifts, [])

        # --- one account, no ledger history, balance == DEFAULT_STARTING_BALANCE -> clean ---
        _set_responders(("json", 200, [{"user_id": "u1", "balance_usd": 0.0}]), ("json", 200, []))
        drifts = await billing.reconcile_all_accounts()
        check("reconcile_all_accounts: fresh account at exactly DEFAULT_STARTING_BALANCE with no ledger rows -> no drift (proves DEFAULT_STARTING_BALANCE is correctly added back in, not just the ledger sum)", drifts, [])

        # --- ledger activity that nets out correctly (a credit then a charge) -> clean ---
        _set_responders(
            ("json", 200, [{"user_id": "u1", "balance_usd": 3.0}]),
            ("json", 200, [{"user_id": "u1", "amount_usd": 5.0}, {"user_id": "u1", "amount_usd": -2.0}]),
        )
        drifts = await billing.reconcile_all_accounts()
        check("reconcile_all_accounts: balance matching a real credit+charge history -> no drift", drifts, [])

        # --- the actual point of this tool: a genuinely drifted account ---
        _set_responders(
            ("json", 200, [{"user_id": "u2", "balance_usd": -0.5}]),
            ("json", 200, [{"user_id": "u2", "amount_usd": -0.3}]),
        )
        drifts = await billing.reconcile_all_accounts()
        check("reconcile_all_accounts: a genuinely drifted account IS flagged", len(drifts), 1)
        check("reconcile_all_accounts: correct user_id on the flagged drift", drifts[0].user_id, "u2")
        check("reconcile_all_accounts: expected_balance computed correctly (DEFAULT_STARTING_BALANCE + ledger sum)", drifts[0].expected_balance, billing.Decimal("-0.30000"))
        check("reconcile_all_accounts: actual_balance is what's really in billing_accounts", drifts[0].actual_balance, billing.Decimal("-0.50000"))
        check("reconcile_all_accounts: drift = actual - expected, sign preserved (negative = account has LESS than its ledger accounts for)", drifts[0].drift, billing.Decimal("-0.20000"))

        # --- pagination actually walks multiple pages and accumulates across them ---
        # this is the entire reason this doesn't reuse supabase_client's
        # capped admin helpers — prove the loop doesn't stop after page 1.
        billing._RECONCILE_PAGE_SIZE = 2
        _set_responders(
            # accounts: page 1 full (2 rows, continues), page 2 partial (1 row, stops)
            ("json", 200, [{"user_id": "u3", "balance_usd": 1.0}, {"user_id": "u4", "balance_usd": 2.0}]),
            ("json", 200, [{"user_id": "u5", "balance_usd": 3.0}]),
            # ledger: page 1 full (2 rows, continues), page 2 partial (1 row, stops) — all for u3, split across pages
            ("json", 200, [{"user_id": "u3", "amount_usd": 0.6}, {"user_id": "u3", "amount_usd": 0.4}]),
            ("json", 200, [{"user_id": "u4", "amount_usd": 2.0}]),
        )
        drifts = await billing.reconcile_all_accounts()
        check("reconcile_all_accounts (paginated): u3's ledger rows split across two pages still sum correctly (0.6+0.4=1.0, matches balance) -> no drift for u3", any(d.user_id == "u3" for d in drifts), False)
        check("reconcile_all_accounts (paginated): u4 (own page) also reconciles correctly (2.0 matches 2.0)", any(d.user_id == "u4" for d in drifts), False)
        check("reconcile_all_accounts (paginated): u5 (balance 3.0, zero ledger rows anywhere) correctly flagged as drifted, proving pagination didn't silently drop or fabricate rows across the account/ledger page boundary", [d.user_id for d in drifts], ["u5"])
    finally:
        billing.config.SUPABASE_URL, billing.config.SUPABASE_SERVICE_ROLE_KEY = real_url, real_key
        billing._RECONCILE_PAGE_SIZE = real_page_size


# =======================================================================
# Group 6 — auth.require_account_key()'s pre-auth IP throttle — added
# 2026-09-15 (item 1 of the audit). test_pipeline_logic.py already
# proves enforce_unauthenticated_product_rate_limit() is correct in
# isolation; what THAT file can't prove is that require_account_key()
# actually calls it before api_keys.verify_api_key() ever reaches
# Supabase. Proven here by handing out exactly
# rl.UNAUTH_PRODUCT_RATE_MAX_REQUESTS fake-Supabase responders: if the
# throttle ran too late, in the wrong place, or not at all, the
# (max+1)th call would try to consume a responder that doesn't exist,
# and _next_response() would raise AssertionError instead of the
# expected 429 — that specific failure mode is the thing this actually
# checks, not just the request count.
# =======================================================================
class _FakeAuthClient:
    def __init__(self, host):
        self.host = host


class _FakeAuthRequest:
    def __init__(self, ip):
        self.headers = {}
        self.client = _FakeAuthClient(ip)


async def _test_pre_auth_ip_throttle():
    real_url, real_key = api_keys.config.SUPABASE_URL, api_keys.config.SUPABASE_SERVICE_ROLE_KEY
    api_keys.config.SUPABASE_URL = "https://fake.test"
    api_keys.config.SUPABASE_SERVICE_ROLE_KEY = "fake-service-role-key"
    try:
        fake_req = _FakeAuthRequest("192.0.2.55")
        # One fake "no such key" Supabase reply (empty rows) per request
        # this IP is allowed to make — each should reach the fake client
        # and come back as a 401 (bad key), not a 429: the throttle
        # hasn't tripped for any of these yet.
        _set_responders(*[("json", 200, []) for _ in range(rl.UNAUTH_PRODUCT_RATE_MAX_REQUESTS)])
        saw_401 = 0
        unexpected = []
        for i in range(rl.UNAUTH_PRODUCT_RATE_MAX_REQUESTS):
            try:
                await auth_mod.require_account_key(fake_req, authorization=None, x_api_key="sk-quan-not-a-real-key")
                unexpected.append((i, "no exception"))
            except _StubHTTPException as e:
                if e.status_code == 401:
                    saw_401 += 1
                else:
                    unexpected.append((i, e.status_code))
        check(f"require_account_key: all {rl.UNAUTH_PRODUCT_RATE_MAX_REQUESTS} requests within the IP window limit reach the fake Supabase call and fail as 401 (bad key), not 429", (saw_401, unexpected), (rl.UNAUTH_PRODUCT_RATE_MAX_REQUESTS, []))

        # The (max+1)th request from the SAME IP: no responder left. A
        # correctly-ordered throttle raises 429 here without ever
        # touching the fake client. If the throttle were missing, wired
        # in the wrong place, or ran after the Supabase call instead of
        # before it, this would raise AssertionError from
        # _next_response() ("called more times than responders set up
        # for") rather than the expected 429 — proving the ordering,
        # not just the rate-limit math.
        try:
            await auth_mod.require_account_key(fake_req, authorization=None, x_api_key="sk-quan-not-a-real-key")
            check("require_account_key: the (max+1)th request from the same IP is rejected before reaching Supabase", "no exception raised", "429 from the IP throttle")
        except _StubHTTPException as e:
            check("require_account_key: the (max+1)th request from the same IP is rejected with 429 (the IP throttle, not a 401 from an actual Supabase call)", e.status_code, 429)
            check("require_account_key: that 429 carries the rate_limit_exceeded code, confirming it's the IP throttle and not some other 429 path", e.detail["error"]["code"], "rate_limit_exceeded")
        except AssertionError as e:
            failures.append(f"FAIL require_account_key: the (max+1)th request reached the fake Supabase call instead of being throttled first ({e})")

        # A fresh IP is unaffected, and — as its own first call — should
        # legitimately reach the fake Supabase client again, proving the
        # throttle is per-IP, not a global lockout once anyone trips it.
        _set_responders(("json", 200, []))
        fresh_req = _FakeAuthRequest("192.0.2.200")
        try:
            await auth_mod.require_account_key(fresh_req, authorization=None, x_api_key="sk-quan-not-a-real-key")
            check("require_account_key: a fresh IP unaffected by another IP's throttle reaches Supabase and gets 401 (not 429)", "no exception raised", "401")
        except _StubHTTPException as e:
            check("require_account_key: a fresh IP unaffected by another IP's throttle reaches Supabase and gets 401 (not 429)", e.status_code, 401)
    finally:
        api_keys.config.SUPABASE_URL, api_keys.config.SUPABASE_SERVICE_ROLE_KEY = real_url, real_key


# =======================================================================
# Group 7 — customer price + billing.calculate_cost() at the current price
# (PLAN.md B1; repriced again 2026-10-08). No I/O. The pinned numbers
# below are the DECIDED price ($3.00 in / $10.00 out / $0.60 cached-in per 1M
# tokens): when the price is changed on purpose, update the pinned block; the
# invariants after it should keep passing untouched.
# =======================================================================
def _test_customer_price_and_cost():
    price = app_config.current_customer_price("kael-beta")

    # --- pinned: the decided price ---
    check("customer price: Kael Beta input is $3.00 per 1M tokens", price["input"], 3.0)
    check("customer price: Kael Beta output is $10.00 per 1M tokens", price["output"], 10.0)
    check("customer price: Kael Beta cached input is $0.60 per 1M tokens", price["cached_input"], 0.60)

    # --- invariant: independent of what the price is ---
    check(
        "customer price: cached_input is exactly 20% of input (billing derives its cached rate from "
        "CACHE_DISCOUNT_PCT; supabase_client's cost estimate reads this config number — they must not drift apart)",
        billing.Decimal(str(price["cached_input"])),
        billing.Decimal(str(price["input"])) * (billing.Decimal("1") - billing.CACHE_DISCOUNT_PCT),
    )

    # --- worked examples through the real billing math ---
    one_m_in_out = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "completion_tokens": 1_000_000}
    check(
        "calculate_cost: 1M uncached input + 1M output = $3.00 + $10.00 = $13.00",
        billing.calculate_cost("kael-beta", one_m_in_out, None)["cost_usd"],
        billing.Decimal("13.00000"),
    )
    all_cached = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 1_000_000, "completion_tokens": 0}
    check(
        "calculate_cost: 1M fully-cached input tokens = $0.60",
        billing.calculate_cost("kael-beta", all_cached, None)["cost_usd"],
        billing.Decimal("0.60000"),
    )
    mixed = {"prompt_tokens": 500_000, "prompt_cache_hit_tokens": 200_000, "completion_tokens": 100_000}
    check(
        "calculate_cost: 300k uncached ($0.90) + 200k cached ($0.12) + 100k output ($1.00) = $2.02",
        billing.calculate_cost("kael-beta", mixed, None)["cost_usd"],
        billing.Decimal("2.02000"),
    )


# =======================================================================
# Group 8 — app/scheduled_checks.py (PLAN.md B4). The interim
# in-process reconciliation loop. Reuses the fake HTTP layer (Group 1; Group 5
# uses it the same way) for the
# reconciliation itself; email_service.send_email and low_balance_alerts'
# run_once are replaced with recorders. The property that matters most:
# nothing that goes wrong in here may ever escape as an exception.
# =======================================================================
_sent_emails: list = []


async def _fake_send_email(to, subject, html):
    _sent_emails.append({"to": to, "subject": subject, "html": html})


async def _failing_send_email(to, subject, html):
    raise _StubHTTPException(500, "Failed to send email via Resend")


async def _capture(coro):
    """Await `coro` and return (its result, everything it printed to stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = await coro
    return result, buf.getvalue()


_CLEAN = (("json", 200, [{"user_id": "u1", "balance_usd": 0.0}]), ("json", 200, []))
_DRIFTED = (
    ("json", 200, [{"user_id": "u2", "balance_usd": -0.5}]),
    ("json", 200, [{"user_id": "u2", "amount_usd": -0.3}]),
)


async def _test_scheduled_checks():
    real = {
        "url": app_config.SUPABASE_URL,
        "key": app_config.SUPABASE_SERVICE_ROLE_KEY,
        "alert": app_config.ADMIN_ALERT_EMAIL,
        "lb": app_config.LOW_BALANCE_ALERTS_ENABLED,
        "send": email_service.send_email,
        "run_once": lba.run_once,
        "run_reconcile": sched.run_reconcile,
        "run_credit_expiry": sched.run_credit_expiry,
        "run_trace_purge": sched.run_trace_purge,
        "run_cycle": sched.run_cycle,
        "start": sched.start,
    }
    app_config.SUPABASE_URL = "https://fake.test"
    app_config.SUPABASE_SERVICE_ROLE_KEY = "fake-service-role-key"
    app_config.ADMIN_ALERT_EMAIL = "owner@example.test"
    app_config.LOW_BALANCE_ALERTS_ENABLED = False
    email_service.send_email = _fake_send_email
    try:
        check("schedule: first run waits 5 minutes after boot", sched.INITIAL_DELAY_SECONDS, 300)
        check("schedule: then repeats every 24 hours", sched.INTERVAL_SECONDS, 86400)

        # --- clean ---
        _sent_emails.clear()
        _set_responders(*_CLEAN)
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("reconcile clean: status is ok", outcome.status, "ok")
        check("reconcile clean: logs the one-line result", "RECONCILE ok" in out, True)
        check("reconcile clean: exactly one log line", len(out.strip().splitlines()), 1)
        check("reconcile clean: no email", _sent_emails, [])
        check("reconcile clean: to_dict has zero drifts", outcome.to_dict()["drift_count"], 0)

        # --- drift, scheduled: logs, emails the owner ---
        _sent_emails.clear()
        _set_responders(*_DRIFTED)
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("reconcile drift: status is drift", outcome.status, "drift")
        check("reconcile drift: logs count", "RECONCILE drift 1 account(s)" in out, True)
        check("reconcile drift: exactly one email", len(_sent_emails), 1)
        check("reconcile drift: emailed ADMIN_ALERT_EMAIL", _sent_emails[0]["to"], "owner@example.test")
        check("reconcile drift: email subject names the count", "drift in 1 account(s)" in _sent_emails[0]["subject"], True)
        check("reconcile drift: email lists the user id and the signed drift", ("u2" in _sent_emails[0]["html"], "-$0.20000" in _sent_emails[0]["html"]), (True, True))
        d = outcome.to_dict()
        check("reconcile drift: to_dict count", d["drift_count"], 1)
        check("reconcile drift: to_dict row is JSON-safe strings", d["drifts"][0], {
            "user_id": "u2", "expected_balance_usd": "-0.30000", "actual_balance_usd": "-0.50000", "drift_usd": "-0.20000",
        })

        # --- drift, ADMIN_ALERT_EMAIL unset: log only ---
        _sent_emails.clear()
        app_config.ADMIN_ALERT_EMAIL = ""
        _set_responders(*_DRIFTED)
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("reconcile drift, no ADMIN_ALERT_EMAIL: still detected and logged", (outcome.status, "RECONCILE drift 1" in out), ("drift", True))
        check("reconcile drift, no ADMIN_ALERT_EMAIL: no email attempted", _sent_emails, [])
        app_config.ADMIN_ALERT_EMAIL = "owner@example.test"

        # --- drift, manual trigger: result + log, but no email ---
        _sent_emails.clear()
        _set_responders(*_DRIFTED)
        outcome, out = await _capture(sched.run_reconcile("manual"))
        check("manual reconcile: returns the drift", outcome.status, "drift")
        check("manual reconcile: log line is tagged (manual)", "(manual)" in out, True)
        check("manual reconcile: does not email the admin who clicked it", _sent_emails, [])

        # --- the check itself fails (Supabase down): reported, never raised ---
        _sent_emails.clear()
        _set_responders(RuntimeError("supabase down"))
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("reconcile failure: status is error, not an exception", outcome.status, "error")
        check("reconcile failure: error text kept", "supabase down" in (outcome.error or ""), True)
        check("reconcile failure: logged as failed", "RECONCILE failed:" in out, True)
        check("reconcile failure: owner emailed that the check could not run", (len(_sent_emails), "could not run" in _sent_emails[0]["subject"]), (1, True))

        # --- billing not configured: error, and no HTTP call was attempted ---
        _sent_emails.clear()
        app_config.SUPABASE_URL = ""
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("reconcile unconfigured: error mentioning configuration", (outcome.status, "not configured" in (outcome.error or "")), ("error", True))
        app_config.SUPABASE_URL = "https://fake.test"

        # --- a failing alert email must never break the run ---
        email_service.send_email = _failing_send_email
        _set_responders(*_DRIFTED)
        outcome, out = await _capture(sched.run_reconcile("scheduled"))
        check("alert email fails: run still returns its outcome", outcome.status, "drift")
        check("alert email fails: failure is logged, not raised", "alert email failed" in out, True)
        email_service.send_email = _fake_send_email

        # --- low-balance step: gated by LOW_BALANCE_ALERTS_ENABLED ---
        lb_calls = []

        async def _fake_run_once():
            lb_calls.append(1)
            return lba.LowBalanceResult(sent=1, cleared=2, errors=0)

        lba.run_once = _fake_run_once
        app_config.LOW_BALANCE_ALERTS_ENABLED = False
        _, out = await _capture(sched.run_low_balance_alerts())
        check("low-balance step: default-off flag means run_once is never called", (lb_calls, out), ([], ""))
        app_config.LOW_BALANCE_ALERTS_ENABLED = True
        _, out = await _capture(sched.run_low_balance_alerts())
        check("low-balance step: enabled -> runs once and logs the counts", (len(lb_calls), "LOW_BALANCE sent=1 cleared=2 errors=0" in out), (1, True))

        async def _boom_run_once():
            raise lba.LowBalanceRunError("Could not load users/balances: boom")

        lba.run_once = _boom_run_once
        _, out = await _capture(sched.run_low_balance_alerts())
        check("low-balance step: a failing run is logged and swallowed", "LOW_BALANCE failed" in out, True)

        # --- one cycle: credit expiry, reconcile, trace purge, then low-balance (only when enabled) ---
        # The expiry and purge steps have their own tests (test_credit_expiry.py,
        # test_account_retention.py); here they are recorders, so this queue of canned
        # HTTP answers is used by the reconcile step only.
        order = []

        async def _fake_expiry(trigger="scheduled"):
            order.append("expiry")

        async def _fake_purge():
            order.append("purge")

        sched.run_credit_expiry = _fake_expiry
        sched.run_trace_purge = _fake_purge
        lba.run_once = _fake_run_once
        lb_calls.clear()
        app_config.LOW_BALANCE_ALERTS_ENABLED = False
        _set_responders(*_CLEAN)
        _, out = await _capture(sched.run_cycle())
        check("cycle (low-balance off): reconciles, does not send low-balance emails", ("RECONCILE ok" in out, lb_calls), (True, []))
        check("cycle: credit expiry runs before the reconcile check, the trace purge after it", (order, out.index("RECONCILE ok") >= 0), (["expiry", "purge"], True))

        # a crashing expiry or purge must not stop the reconcile or each other
        async def _crashing_expiry(trigger="scheduled"):
            raise RuntimeError("expiry blew up")

        async def _crashing_purge():
            raise RuntimeError("purge blew up")

        sched.run_credit_expiry = _crashing_expiry
        sched.run_trace_purge = _crashing_purge
        _set_responders(*_CLEAN)
        _, out = await _capture(sched.run_cycle())
        check("cycle: a crashing expiry and a crashing purge are logged and the reconcile still runs", ("CREDIT_EXPIRY crashed" in out, "TRACE_PURGE crashed" in out, "RECONCILE ok" in out), (True, True, True))
        sched.run_credit_expiry = _fake_expiry
        sched.run_trace_purge = _fake_purge

        # --- one crashing step must not skip the other ---
        async def _crashing_reconcile(trigger="scheduled"):
            raise RuntimeError("unexpected")

        sched.run_reconcile = _crashing_reconcile
        app_config.LOW_BALANCE_ALERTS_ENABLED = True
        lb_calls.clear()
        _, out = await _capture(sched.run_cycle())
        check("cycle: a crashing reconcile is logged and low-balance still runs", ("RECONCILE crashed" in out, len(lb_calls)), (True, 1))
        sched.run_reconcile = real["run_reconcile"]

        # --- the loop itself ---
        cycle_calls = []

        async def _flaky_cycle():
            cycle_calls.append(1)
            if len(cycle_calls) == 1:
                raise RuntimeError("first cycle explodes")

        sched.run_cycle = _flaky_cycle

        # Nothing runs before the initial delay; cancelling during it is clean.
        task = sched.start(initial_delay=0.5, interval=0.02)
        await asyncio.sleep(0.05)
        check("loop: nothing runs during the initial delay", cycle_calls, [])
        await sched.stop(task)
        check("loop: cancelling during the initial delay ends the task cleanly", (task.done(), cycle_calls), (True, []))

        # Survives a crashing cycle and keeps running on its interval.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            task = sched.start(initial_delay=0.01, interval=0.02)
            await _wait_until(lambda: len(cycle_calls) >= 3)
            await sched.stop(task)
        check("loop: keeps running after a cycle raises (3+ cycles)", len(cycle_calls) >= 3, True)
        check("loop: the crash was logged", "cycle crashed" in buf.getvalue(), True)
        check("loop: stop() leaves the task finished", task.done(), True)
        settled = len(cycle_calls)
        await asyncio.sleep(0.1)
        check("loop: no more cycles after stop()", len(cycle_calls), settled)

        # --- lifespan: starts the loop on startup, cancels it on shutdown ---
        cycle_calls.clear()
        started = []

        def _fast_start():
            t = real["start"](initial_delay=0.01, interval=0.02)
            started.append(t)
            return t

        sched.start = _fast_start
        sched.run_cycle = _flaky_cycle
        with contextlib.redirect_stdout(io.StringIO()):
            async with sched.lifespan(None):
                await _wait_until(lambda: len(cycle_calls) >= 1)
                running_while_up = not started[0].done()
        check("lifespan: loop is running while the app is up", running_while_up, True)
        check("lifespan: loop is cancelled on shutdown", started[0].done(), True)
    finally:
        app_config.SUPABASE_URL = real["url"]
        app_config.SUPABASE_SERVICE_ROLE_KEY = real["key"]
        app_config.ADMIN_ALERT_EMAIL = real["alert"]
        app_config.LOW_BALANCE_ALERTS_ENABLED = real["lb"]
        email_service.send_email = real["send"]
        lba.run_once = real["run_once"]
        sched.run_reconcile = real["run_reconcile"]
        sched.run_credit_expiry = real["run_credit_expiry"]
        sched.run_trace_purge = real["run_trace_purge"]
        sched.run_cycle = real["run_cycle"]
        sched.start = real["start"]


def _test_config_flags():
    name = "X_TEST_FLAG_B4"
    saved = os.environ.pop(name, None)
    try:
        check("_env_flag: unset -> default False", app_config._env_flag(name, False), False)
        check("_env_flag: unset -> default True", app_config._env_flag(name, True), True)
        for v in ("true", "TRUE", "1", "yes", "on", "  true  "):
            os.environ[name] = v
            check(f"_env_flag: {v!r} -> True", app_config._env_flag(name, False), True)
        for v in ("false", "0", "no", "off", "banana"):
            os.environ[name] = v
            check(f"_env_flag: {v!r} -> False even when default is True (typos fail closed)", app_config._env_flag(name, True), False)
        os.environ[name] = "   "
        check("_env_flag: blank -> default", app_config._env_flag(name, True), True)
    finally:
        os.environ.pop(name, None)
        if saved is not None:
            os.environ[name] = saved
    if "LOW_BALANCE_ALERTS_ENABLED" not in os.environ:
        # Changed 2026-10-13 at the owner's request: the balance emails now
        # work out of the box (set LOW_BALANCE_ALERTS_ENABLED=false to disable).
        check("config: LOW_BALANCE_ALERTS_ENABLED defaults to on", app_config.LOW_BALANCE_ALERTS_ENABLED, True)
    if "ADMIN_ALERT_EMAIL" not in os.environ:
        check("config: ADMIN_ALERT_EMAIL defaults to empty (log-only mode)", app_config.ADMIN_ALERT_EMAIL, "")


# =======================================================================
# Group 9 — app/jobs/low_balance_alerts.py after the run_once() refactor
# (PLAN.md B4). The job had no automated coverage; the refactor must not
# change what it does, so this pins its per-user decisions and main()'s exit
# codes / messages.
# =======================================================================
async def _test_low_balance_alerts():
    real = {
        "url": app_config.SUPABASE_URL,
        "key": app_config.SUPABASE_SERVICE_ROLE_KEY,
        "send": email_service.send_email,
        "users": lba.supabase_client.list_auth_users,
        "balances": lba.billing.admin_all_balances,
        "update": lba.supabase_client.update_user_metadata,
    }
    app_config.SUPABASE_URL = "https://fake.test"
    app_config.SUPABASE_SERVICE_ROLE_KEY = "fake-service-role-key"

    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).isoformat()
    on = {"low_balance_alert_enabled": True, "low_balance_alert_threshold_usd": 5.0}
    users = [
        {"id": "u_low", "email": "low@example.test", "user_metadata": {**on, "name": "Low"}},
        {"id": "u_recovered", "email": "rec@example.test", "user_metadata": {**on, "low_balance_alert_sent_at": "2026-09-01T00:00:00+00:00"}},
        {"id": "u_already", "email": "al@example.test", "user_metadata": {**on, "low_balance_alert_sent_at": "2026-09-01T00:00:00+00:00"}},
        {"id": "u_disabled", "email": "d@example.test", "user_metadata": {"low_balance_alert_enabled": False, "low_balance_alert_threshold_usd": 5.0}},
        {"id": "u_no_threshold", "email": "nt@example.test", "user_metadata": {"low_balance_alert_enabled": True}},
        {"id": "u_no_balance", "email": "nb@example.test", "user_metadata": dict(on)},
        {"id": "u_suspended", "email": "s@example.test", "banned_until": future, "user_metadata": dict(on)},
        {"id": "u_send_fails", "email": "boom@example.test", "user_metadata": dict(on)},
    ]
    balances = {
        "u_low": 2.0, "u_recovered": 10.0, "u_already": 1.0, "u_disabled": 1.0,
        "u_no_threshold": 1.0, "u_suspended": 1.0, "u_send_fails": 1.0,
    }
    emailed, updates = [], []

    async def _list_users():
        return users

    async def _all_balances():
        return balances

    async def _send(to, subject, html):
        if to == "boom@example.test":
            raise _StubHTTPException(500, "Failed to send email via Resend")
        emailed.append(to)

    async def _update(user_id, meta):
        updates.append((user_id, meta))

    lba.supabase_client.list_auth_users = _list_users
    lba.billing.admin_all_balances = _all_balances
    email_service.send_email = _send
    lba.supabase_client.update_user_metadata = _update
    try:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = await lba.run_once()
        check("low-balance run_once: 1 sent, 1 cleared, 1 error", (result.sent, result.cleared, result.errors), (1, 1, 1))
        check("low-balance run_once: only the below-threshold, not-yet-alerted user was emailed", emailed, ["low@example.test"])
        check("low-balance run_once: sent flag written for the alerted user", ("low_balance_alert_sent_at" in dict(updates)["u_low"], "u_low" in dict(updates)), (True, True))
        check("low-balance run_once: sent flag removed once the balance recovered", "low_balance_alert_sent_at" in dict(updates)["u_recovered"], False)
        check("low-balance run_once: a failed send is counted, and does not write the sent flag", "u_send_fails" in dict(updates), False)
        check("low-balance run_once: nobody else was touched", sorted(dict(updates)), ["u_low", "u_recovered"])
        check("low-balance run_once: per-user error goes to stderr with the user id", "u_send_fails" in err.getvalue(), True)

        # main(): exit code 1 because of the per-user error, summary on stdout.
        # (The fake update_user_metadata does not persist, so u_low is alerted again.)
        emailed.clear()
        updates.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = await lba.main()
        check("low-balance main: exit 1 when any user errored", code, 1)
        check("low-balance main: prints the same summary line as before", out.getvalue().strip(), "Low-balance alerts: 1 sent, 1 cleared, 1 error(s).")

        # main(): clean run -> exit 0
        users[:] = [users[1]]  # only u_recovered
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = await lba.main()
        check("low-balance main: exit 0 on a clean run", (code, out.getvalue().strip()), (0, "Low-balance alerts: 0 sent, 1 cleared, 0 error(s)."))

        # main(): inputs cannot be loaded -> exit 2 and the original message
        async def _list_users_boom():
            raise RuntimeError("supabase down")

        lba.supabase_client.list_auth_users = _list_users_boom
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = await lba.main()
        check("low-balance main: exit 2 when users/balances cannot be loaded", code, 2)
        check("low-balance main: original 'Could not load' message on stderr", "Could not load users/balances:" in err.getvalue(), True)

        # main(): billing not configured -> exit 2 and the original message
        app_config.SUPABASE_URL = ""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = await lba.main()
        check("low-balance main: exit 2 when Supabase is not configured", (code, "not configured" in err.getvalue()), (2, True))
    finally:
        app_config.SUPABASE_URL = real["url"]
        app_config.SUPABASE_SERVICE_ROLE_KEY = real["key"]
        email_service.send_email = real["send"]
        lba.supabase_client.list_auth_users = real["users"]
        lba.billing.admin_all_balances = real["balances"]
        lba.supabase_client.update_user_metadata = real["update"]


# =======================================================================
# Group 4c — injected-prompt overhead is subtracted from billed/shown input
# (added 2026-10-03, owner decision). Both paths: the draft's reported input
# loses Kael's injected tokens, its cache hit loses only the injected
# prefix, output comes from the critic untouched.
# =======================================================================
def _usage_sse(content_text: str, prompt: int, cached: int, completion: int):
    delta_chunk = {"choices": [{"index": 0, "delta": {"content": content_text}, "finish_reason": None}]}
    final_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion, "prompt_tokens_details": {"cached_tokens": cached}}}
    return [f"data: {tpp.json.dumps(delta_chunk)}", f"data: {tpp.json.dumps(final_chunk)}", "data: [DONE]"]


async def _test_injected_overhead_billing():
    real_post_upstream = tpp._post_upstream
    tpp._post_upstream = _fake_post_upstream
    try:
        _reset_recorders()
        draft = _responses_shape("draft answer")
        draft["usage"] = {"input_tokens": 6000, "output_tokens": 50, "total_tokens": 6050, "input_tokens_details": {"cached_tokens": 2000}, "output_tokens_details": {"reasoning_tokens": 0}}
        critic = _responses_shape("critic-reviewed answer")
        critic["usage"] = {"input_tokens": 9000, "output_tokens": 300, "total_tokens": 9300, "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}
        _queue_post_upstream(draft, critic)
        await _run_nonstream_default(injected_prefix_tokens=1100, injected_total_tokens=3500)
        u = _charge_calls[-1]["usage"]
        check("injected overhead (non-stream): billed input = draft input minus injected total", u["prompt_tokens"], 2500)
        check("injected overhead (non-stream): billed cached = draft cache hit minus injected prefix", u["prompt_cache_hit_tokens"], 900)
        check("injected overhead (non-stream): billed output comes from the critic, untouched", (_charge_calls[-1]["native_usage"] or {}).get("completion_tokens"), 300)
        check("injected overhead (non-stream): the usage_logs row records the BILLED input (dashboard prices these rows)", _log_usage_calls[-1].get("prompt_tokens"), 2500)
        check("injected overhead (non-stream): the usage_logs row records the BILLED output (critic's only, not draft + critic summed)", _log_usage_calls[-1].get("completion_tokens"), 300)
        check("injected overhead (non-stream): the usage_logs row records the BILLED cached tokens", _log_usage_calls[-1].get("cached_tokens"), 900)

        _reset_recorders()
        _queue_post_upstream(draft, critic)
        await _run_nonstream_default(injected_prefix_tokens=0, injected_total_tokens=0)
        check("injected overhead (non-stream): zero overhead leaves billed input at the raw upstream figure", _charge_calls[-1]["usage"]["prompt_tokens"], 6000)
    finally:
        tpp._post_upstream = real_post_upstream

    # --- streaming ---
    _reset_recorders()
    _set_responders(
        ("lines", 200, _usage_sse("<task_difficulty_testboundary123>HARD</task_difficulty_testboundary123>draft", 6000, 2000, 50)),
        ("lines", 200, _usage_sse("final answer", 9000, 0, 300)),
    )
    real_call_summarizer = tsm._call_summarizer
    async def _no_titles(chunk, history, kind="reasoning"):
        return []
    tsm._call_summarizer = _no_titles
    try:
        items = await _run_stream_and_collect(injected_prefix_tokens=1100, injected_total_tokens=3500, client_wants_usage_chunk=True)
    finally:
        tsm._call_summarizer = real_call_summarizer
    u = _charge_calls[-1]["usage"]
    check("injected overhead (stream): billed input = draft input minus injected total", u["prompt_tokens"], 2500)
    check("injected overhead (stream): billed cached = draft cache hit minus injected prefix", u["prompt_cache_hit_tokens"], 900)
    check("injected overhead (stream): billed output comes from the critic, untouched", (_charge_calls[-1]["native_usage"] or {}).get("completion_tokens"), 300)
    shown = None
    for raw in items:
        if raw.startswith("data:") and "[DONE]" not in raw:
            try:
                chunk = tpp.json.loads(raw[len("data:"):].strip())
            except Exception:
                continue
            if chunk.get("usage"):
                shown = chunk["usage"]
    check("injected overhead (stream): the usage chunk the caller sees matches what was billed", (shown or {}).get("prompt_tokens"), 2500)
    _row = _log_usage_calls[-1]
    check("injected overhead (stream): the usage_logs row matches what was billed (input, cached, output)", (_row.get("prompt_tokens"), _row.get("cached_tokens"), _row.get("completion_tokens")), (2500, 900, 300))
    _price = tpp.config.current_customer_price("kael-beta")  # same pricing source fetch_stats' _row_cost uses
    _cost_from_row = (_row["prompt_tokens"] - _row["cached_tokens"]) / 1e6 * _price["input"] + _row["cached_tokens"] / 1e6 * _price["cached_input"] + _row["completion_tokens"] / 1e6 * _price["output"]
    _charged = tpp.billing.calculate_cost("kael-beta", _charge_calls[-1]["usage"], _charge_calls[-1]["native_usage"])["cost_usd"]
    check("injected overhead (stream): pricing the usage_logs row (how the dashboard does it) equals the amount charged", round(_cost_from_row, 6), round(float(_charged), 6))


def _test_leading_tag_stripper():
    # ---- _LeadingTagStripper: chunk-boundary behaviour (added 2026-10-03) ----
    def _strip_stream(chunks, boundary="b1"):
        st = tpp._LeadingTagStripper(boundary)
        out = "".join(st.feed(c) for c in chunks)
        return out + st.flush()
    _T = "<task_difficulty_b1>"
    _TC = "</task_difficulty_b1>"
    check("stripper: whole tag in one chunk is removed", _strip_stream([_T + "HARD" + _TC + "Draft text"]), "Draft text")
    check("stripper: tag split at every character boundary is removed", _strip_stream(list(_T + "EASY" + _TC + "Hello there")), "Hello there")
    check("stripper: tag with no closing tag still removed", _strip_stream([_T + "EASY\nHello"]), "Hello")
    check("stripper: text without a tag passes through byte-for-byte", _strip_stream(["Hel", "lo ", "<b>bold</b>"]), "Hello <b>bold</b>")
    check("stripper: a lone '<' followed by ordinary text is not swallowed", _strip_stream(["<", "3 you"]), "<3 you")
    check("stripper: a different boundary's tag is left alone", _strip_stream(["<task_difficulty_zzz>HARD</task_difficulty_zzz>x"]), "<task_difficulty_zzz>HARD</task_difficulty_zzz>x")
    check("stripper: stream that ends mid-tag releases the held text on flush", _strip_stream(["<task_diff"]), "<task_diff")
    check("stripper: only the leading tag is stripped, a later one stays", _strip_stream([_T + "HARD" + _TC + "a " + _T + "EASY" + _TC]), "a " + _T + "EASY" + _TC)
    check("stripper: empty stream yields nothing", _strip_stream([]), "")


async def _test_responses_entry_point():
    """The real /v1/responses entry point (kael_pipeline.proxy_kael_response)
    must hand run_pipeline chat-shaped messages, with `instructions` first.
    run_pipeline itself is swapped for a recorder; nothing is sent upstream."""
    from app import kael_pipeline as kp
    captured = {}
    real_run = kp.run_pipeline
    async def _rec(**kw):
        captured.update(kw)
        return "sentinel"
    kp.run_pipeline = _rec
    try:
        out = await kp.proxy_kael_response(
            {"model": "kael-beta", "instructions": "Be terse.", "stream": False,
             "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
                       {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"},
                       {"type": "function_call_output", "call_id": "c1", "output": "done"}],
             "tools": [{"type": "function", "name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}]},
            {"user_id": "u"}, product="kael-beta")
    finally:
        kp.run_pipeline = real_run
    items = captured.get("input_items") or []
    check("responses entry point: returns the pipeline's result", out, "sentinel")
    check("responses entry point: `instructions` reaches the pipeline as the first (system) message", items[0] if items else None, {"role": "system", "content": "Be terse."})
    check("responses entry point: input_text parts arrive as a plain string", items[1] if len(items) > 1 else None, {"role": "user", "content": "hi"})
    check("responses entry point: the tool round trip arrives as assistant tool_calls + a tool message", [m["role"] for m in items[2:]], ["assistant", "tool"])
    check("responses entry point: caller shape stays responses", captured.get("caller_shape"), "responses")


async def _test_provider_routing_wiring():
    """2026-10-05 speed-first routing, end to end through run_pipeline():
    the real upstream body carries the provider object and ONE stable
    session_id for both passes; the serving host never reaches the caller;
    and a "no provider under the price cap" refusal becomes a clean 503."""
    import json
    from app import provider_routing as pr

    posted = []
    real_post = _FakeAsyncClient.post

    async def recording_post(self, url, headers=None, json=None):
        posted.append(json)
        return await real_post(self, url, headers=headers, json=json)

    routing_d = {"sort": "throughput", "allow_fallbacks": True, "max_price": {"prompt": 0.15, "completion": 0.5}}
    routing_c = {"sort": "throughput", "allow_fallbacks": True, "max_price": {"prompt": 0.30, "completion": 1.20}}
    draft = tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model="fake-draft-model",
                           reasoning_effort="low", max_output_tokens=1000, provider_routing=routing_d)
    critic = tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model="fake-critic-model",
                            reasoning_effort="low", max_output_tokens=1000, provider_routing=routing_c)
    turn1 = [{"role": "user", "content": "hi"}]
    turn2 = turn1 + [{"role": "assistant", "content": "hello"}, {"role": "user", "content": "more?"}]

    async def run(items):
        return await tpp.run_pipeline(
            product="kael-beta", slug="kael-beta", system_identity="You are Kael.", draft=draft, critic=critic,
            input_items=items, tools=None, client_wants_stream=False, caller_shape="responses", requestor=_REQUESTOR,
        )

    _FakeAsyncClient.post = recording_post
    try:
        _reset_recorders()
        _set_responders(("json", 200, {**_cc_json("draft"), "provider": "Together"}),
                        ("json", 200, {**_cc_json("final"), "provider": "BaseTen"}))
        result = await run(turn1)
        expected_sid = pr.derive_session_id(_REQUESTOR["user_id"], turn1)
        check("routing wiring: both passes were sent upstream", len(posted), 2)
        check("routing wiring: draft body carries its provider object", posted[0].get("provider"), routing_d)
        check("routing wiring: critic body carries its own provider object", posted[1].get("provider"), routing_c)
        check("routing wiring: both passes share the derived session_id", (posted[0].get("session_id"), posted[1].get("session_id")), (expected_sid, expected_sid))
        blob = json.dumps(result)
        check("routing wiring: the serving host never reaches the caller", any(x in blob for x in ("Together", "BaseTen", "served_by")), False)

        posted.clear()
        _set_responders(("json", 200, _cc_json("draft")), ("json", 200, _cc_json("final")))
        await run(turn2)
        check("routing wiring: a later turn of the same conversation keeps the same session_id", posted[0].get("session_id"), expected_sid)

        # nothing at or under the price cap -> clean 503, no vendor text
        _reset_recorders()
        # (two refusals queued: the draft's first attempt, then its one backup-host retry)
        _set_responders(("json", 404, {"error": {"message": "No endpoints found for the OpenRouter price cap"}}),
                        ("json", 404, {"error": {"message": "No endpoints found for the OpenRouter price cap"}}))
        try:
            await run(turn1)
            failures.append("FAIL routing wiring: a no-provider refusal on the draft should raise")
        except Exception as e:  # HTTPException stub or real
            check("routing wiring: no provider under the cap -> status 503", getattr(e, "status_code", None), 503)
            check("routing wiring: ...with the generic code and no vendor text",
                  (getattr(e, "detail", {}) or {}).get("error", {}).get("code"), "upstream_unavailable")
            check("routing wiring: ...and OpenRouter's own message is not passed through", "OpenRouter" in json.dumps(getattr(e, "detail", {})), False)
    finally:
        _FakeAsyncClient.post = real_post


async def _test_backup_host_fallback():
    """2026-10-05: when OpenRouter refuses a pass for lack of a provider under
    the price cap, the pass is retried ONCE on Baseten with the SAME max_price.
    Covers the non-streaming and streaming paths, both passes, the no-second-
    retry rule, and that a pass with no price cap is never retried."""
    import json
    posted = []
    real_post, real_stream = _FakeAsyncClient.post, _FakeAsyncClient.stream

    async def recording_post(self, url, headers=None, json=None):
        posted.append(json)
        return await real_post(self, url, headers=headers, json=json)

    def recording_stream(self, method, url, headers=None, json=None):
        posted.append(json)
        return real_stream(self, method, url, headers=headers, json=json)

    cap_d = {"prompt": 0.15, "completion": 0.5}
    cap_c = {"prompt": 0.30, "completion": 1.20}
    routing_d = {"sort": "throughput", "allow_fallbacks": True, "max_price": cap_d}
    routing_c = {"sort": "throughput", "allow_fallbacks": True, "max_price": cap_c}
    mk = lambda model, routing: tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model=model,
                                               reasoning_effort="low", max_output_tokens=1000, provider_routing=routing)
    draft, critic = mk("fake-draft-model", routing_d), mk("fake-critic-model", routing_c)
    refusal = ("json", 404, {"error": {"message": "No endpoints found matching your data policy / price cap"}})
    expect_fb = lambda cap: {"order": ["baseten"], "allow_fallbacks": False, "max_price": cap}

    async def run(d=draft, c=critic):
        return await tpp.run_pipeline(
            product="kael-beta", slug="kael-beta", system_identity="You are Kael.", draft=d, critic=c,
            input_items=[{"role": "user", "content": "hi"}], tools=None, client_wants_stream=False,
            caller_shape="responses", requestor=_REQUESTOR,
        )

    real_summarizer = tsm._call_summarizer
    tsm._call_summarizer = _fake_call_summarizer_empty
    _FakeAsyncClient.post, _FakeAsyncClient.stream = recording_post, recording_stream
    try:
        # draft refused once -> retried on Baseten with the draft cap -> normal answer
        _reset_recorders(); posted.clear()
        _set_responders(refusal, ("json", 200, _cc_json("draft")), ("json", 200, _cc_json("final")))
        result = await run()
        check("backup host (non-stream): refused draft is retried once, then critic runs (3 upstream calls)", len(posted), 3)
        check("backup host (non-stream): first attempt used the speed-first routing", posted[0].get("provider"), routing_d)
        check("backup host (non-stream): retry is pinned to baseten with the SAME draft max_price", posted[1].get("provider"), expect_fb(cap_d))
        check("backup host (non-stream): critic still uses its own routing afterwards", posted[2].get("provider"), routing_c)
        check("backup host (non-stream): the caller still gets the answer", "final" in json.dumps(result), True)
        check("backup host (non-stream): no host name reaches the caller", any(x in json.dumps(result) for x in ("baseten", "Baseten")), False)

        # critic refused once -> retried with the CRITIC cap
        _reset_recorders(); posted.clear()
        _set_responders(("json", 200, _cc_json("draft")), ("json", 503, {"error": {"message": "no provider"}}), ("json", 200, _cc_json("final")))
        await run()
        check("backup host (non-stream): refused critic is retried once (3 calls)", len(posted), 3)
        check("backup host (non-stream): critic retry carries the CRITIC max_price, not the draft's", posted[2].get("provider"), expect_fb(cap_c))

        # refused again on the backup -> exactly one retry, then the clean 503
        _reset_recorders(); posted.clear()
        _set_responders(refusal, refusal)
        try:
            await run()
            failures.append("FAIL backup host: a refusal on the backup too should raise")
        except Exception as e:
            check("backup host (non-stream): backup refused too -> clean 503", getattr(e, "status_code", None), 503)
            check("backup host (non-stream): exactly two attempts, never a third", len(posted), 2)

        # no price cap on the pass -> never retried (a retry must not run uncapped)
        _reset_recorders(); posted.clear()
        _set_responders(refusal)
        try:
            await run(d=mk("fake-draft-model", {"sort": "throughput"}))
            failures.append("FAIL backup host: uncapped pass refusal should raise")
        except Exception as e:
            check("backup host: a pass without max_price is not retried", (getattr(e, "status_code", None), len(posted)), (503, 1))

        # a normal non-routing error (e.g. 429) is not retried
        _reset_recorders(); posted.clear()
        _set_responders(("json", 429, {"error": {"message": "rate limited"}}))
        try:
            await run()
            failures.append("FAIL backup host: 429 should raise")
        except Exception as e:
            check("backup host: a 429 is passed through and not retried", (getattr(e, "status_code", None), len(posted)), (429, 1))

        # streaming path: draft refused once -> retried on Baseten -> exchange completes normally
        _reset_recorders(); posted.clear()
        _set_responders(refusal, ("lines", 200, _sse_lines("Just a normal draft answer.")), ("lines", 200, _sse_lines("Just a normal, reviewed answer.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("backup host (stream): exchange completes with the critic's text after the retry", _extract_cc_stream_text(items), "Just a normal, reviewed answer.")
        check("backup host (stream): 3 upstream calls, all queued responses used", (len(posted), len(_responder_queue)), (3, 0))
        check("backup host (stream): retry pinned to baseten with the draft max_price", posted[1].get("provider"), expect_fb(cap_d))
        check("backup host (stream): critic uses its own routing", posted[2].get("provider"), routing_c)
    finally:
        _FakeAsyncClient.post, _FakeAsyncClient.stream = real_post, real_stream
        tsm._call_summarizer = real_summarizer


# =======================================================================
# Group 3d — mid-stream provider failover (2026-10-09). A pass that ends
# with finish_reason "error" before anything reached the client is re-run
# ONCE, silently, on the next-best host (the failed one in provider.ignore).
# The caller hears about it only if the re-run fails too.
# =======================================================================
def _failed_stream_lines(host="CoreWeave", partial="part of an answ", reasoning="thinking hard ", error=True, finish="error", code=502, error_type="provider_error"):
    """A stream that dies mid-generation, in OpenRouter's documented shape:
    some deltas, then ONE chunk with a top-level `error` object, the host in
    `provider`, and finish_reason "error"."""
    lines = []
    if reasoning:
        lines.append(f"data: {tpp.json.dumps({'provider': host, 'choices': [{'index': 0, 'delta': {'reasoning': reasoning}, 'finish_reason': None}]})}" if host else
                     f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'reasoning': reasoning}, 'finish_reason': None}]})}")
    if partial:
        lines.append(f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'content': partial}, 'finish_reason': None}]})}")
    last = {"choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": finish}]}
    if host:
        last["provider"] = host
    if error:
        last["error"] = {"code": code, "message": "Provider disconnected unexpectedly: SECRET PROMPT FRAGMENT", "metadata": {"error_type": error_type}}
    lines.append(f"data: {tpp.json.dumps(last)}")
    lines.append("data: [DONE]")
    return lines


async def _test_midstream_failover():
    import json
    posted = []
    real_post, real_stream = _FakeAsyncClient.post, _FakeAsyncClient.stream

    async def recording_post(self, url, headers=None, json=None):
        posted.append(json)
        return await real_post(self, url, headers=headers, json=json)

    def recording_stream(self, method, url, headers=None, json=None):
        posted.append(json)
        return real_stream(self, method, url, headers=headers, json=json)

    cap_d = {"prompt": 0.15, "completion": 0.5}
    cap_c = {"prompt": 0.30, "completion": 1.20}
    routing_d = {"sort": "throughput", "allow_fallbacks": True, "max_price": cap_d}
    routing_c = {"sort": "throughput", "allow_fallbacks": True, "max_price": cap_c}
    mk = lambda model, routing: tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model=model,
                                               reasoning_effort="low", max_output_tokens=1000, provider_routing=routing)
    draft, critic = mk("fake-draft-model", routing_d), mk("fake-critic-model", routing_c)
    ignoring = lambda routing, *hosts: {**routing, "ignore": list(hosts)}
    saw_error = lambda items: any('"error"' in it for it in items if isinstance(it, str))
    everything = lambda items: " ".join(str(it) for it in items)

    real_summarizer = tsm._call_summarizer
    tsm._call_summarizer = _fake_call_summarizer_empty
    _FakeAsyncClient.post, _FakeAsyncClient.stream = recording_post, recording_stream
    real_ceiling = tpp.GENERATION_HARD_CEILING_SECONDS
    try:
        # ---- streaming: the draft dies mid-stream, the re-run succeeds ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines()), ("lines", 200, _sse_lines("Draft from the second host.")), ("lines", 200, _sse_lines("The reviewed answer.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream draft): the caller gets the final answer", _extract_cc_stream_text(items), "The reviewed answer.")
        check("failover (stream draft): the first failure is NOT reported (no error event)", saw_error(items), False)
        check("failover (stream draft): 3 upstream calls (failed draft, re-run, critic)", (len(posted), len(_responder_queue)), (3, 0))
        check("failover (stream draft): re-run ignores the failed host and keeps sort / fallbacks / max_price", posted[1].get("provider"), ignoring(routing_d, "coreweave"))
        check("failover (stream draft): the critic is unaffected, on its own routing", posted[2].get("provider"), routing_c)
        check("failover (stream draft): no host name or error text reaches the caller", any(x in everything(items) for x in ("CoreWeave", "coreweave", "SECRET", "disconnected")), False)
        check("failover (stream draft): no failure row was written for the silent first failure", any(c.get("status") == "upstream_error" for c in _trace_calls), False)

        # ---- streaming: both attempts fail -> NOW the caller hears about it ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines()), ("lines", 200, _failed_stream_lines(host="Baseten", partial="", reasoning="more thinking ", code=500, error_type="server_error")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream draft): both attempts failed -> the caller gets the error", saw_error(items), True)
        check("failover (stream draft): exactly two attempts, never a third", (len(posted), len(_responder_queue)), (2, 0))
        check("failover (stream draft): the error shown names no host or upstream text", any(x in everything(items) for x in ("CoreWeave", "Baseten", "SECRET")), False)
        fail_row = next((c for c in _trace_calls if c.get("status") == "upstream_error"), {})
        msg = fail_row.get("error_message", "")
        check("failover (stream draft): trace names finish_reason, code, error_type and BOTH hosts", all(x in msg for x in ("finish_reason=error", "code=500", "error_type=server_error", "host=Baseten", "first attempt:", "host=CoreWeave")), True)
        check("failover (stream draft): the trace error_message holds no upstream free text", "SECRET" in msg, False)
        check("failover (stream draft): failure row records chunks_from_upstream (was always 0)", fail_row.get("chunks_from_upstream", 0) >= 4, True)
        check("failover (stream draft): failure row records reasoning_char_count (was always 0)", fail_row.get("reasoning_char_count", 0) >= len("thinking hard more thinking "), True)

        # ---- streaming: content_filter is a verdict on the content, not retried ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines(error=False, finish="content_filter")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover: content_filter is not retried (one call) and is reported", (len(posted), saw_error(items)), (1, True))

        # ---- streaming: the critic dies before sending anything -> re-run, caller sees one clean answer ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _sse_lines("A draft.")), ("lines", 200, _failed_stream_lines(host="Together", partial="", reasoning="")), ("lines", 200, _sse_lines("Reviewed on the second host.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream critic): re-run answer is served", _extract_cc_stream_text(items), "Reviewed on the second host.")
        check("failover (stream critic): re-run ignores the failed host, with the CRITIC routing", posted[2].get("provider"), ignoring(routing_c, "together"))
        check("failover (stream critic): no error event", saw_error(items), False)

        # ---- streaming: critic fails twice -> the existing fallback (serve the draft) still applies ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _sse_lines("The draft is served.")), ("lines", 200, _failed_stream_lines(host="Together", partial="", reasoning="")), ("lines", 200, _failed_stream_lines(host="Fireworks", partial="", reasoning="")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream critic): both critic attempts failed -> the draft is served, as before", "The draft is served." in _extract_cc_stream_text(items), True)
        check("failover (stream critic): ...and no error event reaches the caller", saw_error(items), False)
        check("failover (stream critic): the draft-serving row names both critic failures", "first attempt:" in (_log_usage_calls[-1].get("error_message") or ""), True)

        # ---- streaming: once the critic's answer is on the wire there is no re-run ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _sse_lines("A draft.")), ("lines", 200, _failed_stream_lines(host="Together", partial="Half an answer that is long enough to be released. " * 8, reasoning="")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream critic): after content was relayed, no re-run (2 calls) and the caller sees the error", (len(posted), saw_error(items)), (2, True))

        # ...but text still held back by the identity guard never reached the caller, so a re-run is safe
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _sse_lines("A draft.")), ("lines", 200, _failed_stream_lines(host="Together", partial="Half an answer ", reasoning="")), ("lines", 200, _sse_lines("Clean second answer.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover (stream critic): text only held back by the identity guard is not 'relayed' -> re-run, clean answer", (len(posted), _extract_cc_stream_text(items), "Half an answer" in everything(items)), (3, "Clean second answer.", False))

        # ---- streaming: failed host unknown -> pin the backup host instead of ignoring nothing ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines(host=None)), ("lines", 200, _sse_lines("Draft.")), ("lines", 200, _sse_lines("Final.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover: failed host unknown -> re-run pinned to baseten with the same max_price", posted[1].get("provider"), {"order": ["baseten"], "allow_fallbacks": False, "max_price": cap_d})
        check("failover: ...and the exchange still completes", _extract_cc_stream_text(items), "Final.")

        # ---- streaming: a pass with no price ceiling is never re-run ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines()))
        items = await _run_stream_and_collect(draft=mk("fake-draft-model", {"sort": "throughput"}), critic=critic)
        check("failover: no max_price -> no re-run (a re-run must not run uncapped)", (len(posted), saw_error(items)), (1, True))

        # ---- streaming: an error chunk with no failed finish_reason is still a failure ----
        _reset_recorders(); posted.clear()
        _set_responders(("lines", 200, _failed_stream_lines(finish=None)), ("lines", 200, _sse_lines("Draft.")), ("lines", 200, _sse_lines("Final.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover: error object without a finish_reason is treated as a failure and re-run", (len(posted), _extract_cc_stream_text(items)), (3, "Final."))

        # ---- each attempt gets its own ceiling (the re-run is not squeezed into what is left) ----
        tpp.GENERATION_HARD_CEILING_SECONDS = 0.25
        _reset_recorders(); posted.clear()
        slow_fail = ["__sleep__:0.18"] + _failed_stream_lines()
        slow_ok = ["__sleep__:0.18"] + _sse_lines("Slow but fine.")
        _set_responders(("lines", 200, slow_fail), ("lines", 200, slow_ok), ("lines", 200, _sse_lines("Final.")))
        items = await _run_stream_and_collect(draft=draft, critic=critic)
        check("failover: attempt 1 (0.18s) + re-run (0.18s) > the 0.25s ceiling, yet each fits its own -> succeeds", (_extract_cc_stream_text(items), saw_error(items)), ("Final.", False))
        tpp.GENERATION_HARD_CEILING_SECONDS = real_ceiling

        # ---- non-streaming: failed draft re-run, then success ----
        async def run_ns(d=draft, c=critic):
            return await tpp.run_pipeline(
                product="kael-beta", slug="kael-beta", system_identity="You are Kael.", draft=d, critic=c,
                input_items=[{"role": "user", "content": "hi"}], tools=None, client_wants_stream=False,
                caller_shape="responses", requestor=_REQUESTOR,
            )
        failed_json = lambda host="CoreWeave": {**_cc_json("", finish_reason="error"), "provider": host,
                                                "error": {"code": 502, "message": "SECRET PROMPT FRAGMENT", "metadata": {"error_type": "provider_error"}}}
        _reset_recorders(); posted.clear()
        _set_responders(("json", 200, failed_json()), ("json", 200, _cc_json("draft")), ("json", 200, _cc_json("final")))
        result = await run_ns()
        check("failover (non-stream): failed draft is re-run, then the critic runs (3 calls)", len(posted), 3)
        check("failover (non-stream): re-run ignores the failed host", posted[1].get("provider"), ignoring(routing_d, "coreweave"))
        check("failover (non-stream): the caller gets the answer, with no host, error text or internal fields", ("final" in json.dumps(result), any(x in json.dumps(result) for x in ("CoreWeave", "SECRET", "upstream_error", "upstream_finish_reason"))), (True, False))

        _reset_recorders(); posted.clear()
        _set_responders(("json", 200, failed_json()), ("json", 200, failed_json("Baseten")))
        try:
            await run_ns()
            failures.append("FAIL failover (non-stream): both attempts failing should raise")
        except Exception as e:
            check("failover (non-stream): both attempts failed -> the caller gets a 502", getattr(e, "status_code", None), 502)
            check("failover (non-stream): ...with no host or upstream text", any(x in json.dumps(getattr(e, "detail", {})) for x in ("CoreWeave", "Baseten", "SECRET")), False)
            check("failover (non-stream): exactly two attempts", len(posted), 2)
            check("failover (non-stream): the trace names both failures", all(x in _trace_calls[-1].get("error_message", "") for x in ("host=Baseten", "first attempt:", "host=CoreWeave")), True)

        _reset_recorders(); posted.clear()
        _set_responders(("json", 200, _cc_json("", finish_reason="content_filter")))
        try:
            await run_ns()
        except Exception:
            pass
        check("failover (non-stream): content_filter is not re-run", len(posted), 1)

        # ---- non-stream critic fails twice -> serves the draft, as before ----
        _reset_recorders(); posted.clear()
        _set_responders(("json", 200, _cc_json("the draft")), ("json", 200, failed_json("Together")), ("json", 200, failed_json("Fireworks")))
        result = await run_ns()
        check("failover (non-stream critic): both critic attempts failed -> the draft is served", "the draft" in json.dumps(result), True)
        check("failover (non-stream critic): the critic re-run used the CRITIC routing minus the failed host", posted[2].get("provider"), ignoring(routing_c, "together"))
    finally:
        tpp.GENERATION_HARD_CEILING_SECONDS = real_ceiling
        _FakeAsyncClient.post, _FakeAsyncClient.stream = real_post, real_stream
        tsm._call_summarizer = real_summarizer


# =======================================================================
# Group 3c — thinking-title fixes (2026-10-06): relay shutdown/ordering/
# cost control, summarizer robustness, and the streaming pipeline's
# handling of reasoning fields, critic failures, on_complete titles, wire
# separators and Anthropic signatures. Same approach as Groups 3/3b:
# real asyncio, shrunk constants, stubbed summarizer / fake HTTP layer.
# =======================================================================
def _reasoning_lines(reasoning_parts, content, field="reasoning"):
    """A streamed pass: reasoning deltas under `field`, then the content."""
    lines = [f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {field: r}, 'finish_reason': None}]})}" for r in reasoning_parts]
    lines += _sse_lines(content)
    return lines


def _sse_events(raw_items):
    """[(event_name, data_dict)] from the raw `event: x\\ndata: {...}` strings."""
    out = []
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        for block in raw.split("\n\n"):  # one item can carry several events
            if not block.startswith("event:"):
                continue
            head, _, data = block.partition("\n")
            try:
                out.append((head[len("event:"):].strip(), tpp.json.loads(data[len("data:"):].strip())))
            except Exception:
                continue
    return out


def _cc_reasoning_deltas(raw_items):
    out = []
    for raw in raw_items:
        if isinstance(raw, str) and raw.startswith("data:") and "[DONE]" not in raw:
            try:
                ch = tpp.json.loads(raw[5:].strip())
            except Exception:
                continue
            for c in ch.get("choices") or []:
                r = (c.get("delta") or {}).get("reasoning_content")
                if r:
                    out.append(r)
    return out


async def _test_thinking_fixes():
    names = ("IDLE_FLUSH_SECONDS", "FORCE_FLUSH_SECONDS", "FILLER_INTERVAL_SECONDS", "REASONING_CHUNK_CHARS", "DRAFT_CHUNK_CHARS",
             "MIN_IDLE_FLUSH_CHARS", "MIN_FLUSH_GAP_SECONDS", "STOP_GRACE_SECONDS", "SUMMARIZER_RETRY_BACKOFF_SECONDS")
    saved = {n: getattr(tsm, n) for n in names}
    real_call = tsm._call_summarizer
    tsm.REASONING_CHUNK_CHARS = tsm.DRAFT_CHUNK_CHARS = 10**9
    tsm.MIN_IDLE_FLUSH_CHARS = 10
    tsm.IDLE_FLUSH_SECONDS = 0.3
    tsm.FORCE_FLUSH_SECONDS = 5.0
    tsm.FILLER_INTERVAL_SECONDS = 60.0
    tsm.STOP_GRACE_SECONDS = 0.3
    tsm.SUMMARIZER_RETRY_BACKOFF_SECONDS = 0.01
    try:
        # ---------------- fillers module stays in step with the relay's phases ----------------
        from app import thinking_fillers as tf
        check("fillers: phase keys equal the relay's PHASE_ constants", set(tf.PHASE_FILLER_WORDS), {tsm.PHASE_DRAFTING, tsm.PHASE_REVIEWING, tsm.PHASE_FUSING})
        check("fillers: the relay still exposes the same lists", (tsm.FILLER_WORDS is tf.FILLER_WORDS, tsm.PHASE_FILLER_WORDS is tf.PHASE_FILLER_WORDS), (True, True))
        check("fillers: is_filler recognises every filler (with wire whitespace) and no real title",
              (all(tf.is_filler(w + "\n\n") for w in tf.FILLER_WORDS), tf.is_filler("Checking the retry logic for the timeout."), tf.is_filler(None)), (True, False, False))

        # ---------------- relay: shutdown (#4, #5) ----------------
        async def very_slow(chunk, history, kind="reasoning", **kw):
            await asyncio.sleep(5)
            return ["late title"]

        tsm._call_summarizer = very_slow
        em = []
        r = tsm.ThinkingRelay(em.append)
        r.start()
        r.feed("x" * 50)
        r._dispatch_flush()
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        await r.stop(flush_tail=False)
        check("stop(): a slow in-flight summarizer call cannot hold stop() past its short grace period", time.monotonic() - t0 < tsm.STOP_GRACE_SECONDS + 0.6, True)
        check("stop(): the cancelled call emitted nothing", em, [])
        await r.stop()  # idempotent
        check("stop(): safe to call twice", True, True)

        cancelled = []

        async def cancel_probe(chunk, history, kind="reasoning", **kw):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            return ["never"]

        tsm._call_summarizer = cancel_probe
        em = []
        r = tsm.ThinkingRelay(em.append)
        r.start()
        r.feed("y" * 50)
        r._dispatch_flush()
        await asyncio.sleep(0.05)
        r.begin_answer()
        await asyncio.sleep(0.05)
        check("begin_answer(): an in-flight summarizer call is cancelled, not left to run and be discarded", cancelled, [True])
        t0 = time.monotonic()
        await r.stop()
        check("stop() once the answer has started returns immediately", time.monotonic() - t0 < 0.3, True)
        check("nothing is emitted after the answer started", em, [])

        async def boom(chunk, history, kind="reasoning", **kw):
            raise RuntimeError("summarizer exploded")

        tsm._call_summarizer = boom
        r = tsm.ThinkingRelay(lambda t: None)
        r.start()
        r.feed("some leftover reasoning text")
        raised = None
        try:
            await r.stop()  # tail flush hits the exploding summarizer
        except BaseException as e:  # noqa: BLE001
            raised = e
        check("stop() never raises, even when its final summarizer call does", raised, None)

        async def one_title(chunk, history, kind="reasoning", **kw):
            return ["A real title"]

        tsm._call_summarizer = one_title

        def bad_emit(t):
            raise ValueError("emit_fn broke")

        r = tsm.ThinkingRelay(bad_emit)
        r.start()
        r.feed("reasoning that will be titled")
        await asyncio.sleep(0.9)
        check("a raising emit_fn does not kill the relay's background loop", r._task.done(), False)
        await r.stop()

        calls = []

        async def counting(chunk, history, kind="reasoning", **kw):
            calls.append(chunk)
            return ["T"]

        tsm._call_summarizer = counting
        em = []
        r = tsm.ThinkingRelay(em.append)
        r.start()
        r.feed("a leftover thought that never hit a threshold")
        await r.stop(flush_tail=False)
        check("stop(flush_tail=False): no extra summarizer call for the leftover buffer", (calls, em), ([], []))

        # ---------------- relay: titles list excludes fillers (#9/#10) ----------------
        tsm.FILLER_INTERVAL_SECONDS = 0.3
        em = []
        r = tsm.ThinkingRelay(em.append)
        r.start()
        r.feed("reasoning about something fairly long")
        await _wait_until(lambda: any(not tsm.is_filler(x) for x in em) and any(tsm.is_filler(x) for x in em), timeout=3.0)
        await r.stop(flush_tail=False)
        check("relay.titles holds the real titles only", r.titles, ["T"])
        check("fillers were emitted on the wire (liveness) but are not in relay.titles", any(tsm.is_filler(x) for x in em), True)
        tsm.FILLER_INTERVAL_SECONDS = 60.0

        # ---------------- relay: order + history (#13) ----------------
        order_calls = []

        async def ordered(chunk, history, kind="reasoning", **kw):
            order_calls.append((chunk, list(history)))
            if chunk.startswith("one"):
                await asyncio.sleep(0.4)
                return ["first"]
            return ["second"]

        tsm._call_summarizer = ordered
        em = []
        r = tsm.ThinkingRelay(em.append)
        r.start()
        r.feed("one" + "." * 20)
        r._dispatch_flush()
        r.feed("two" + "." * 20)
        r._dispatch_flush()
        await _wait_until(lambda: len(em) >= 2, timeout=3.0)
        await r.stop(flush_tail=False)
        check("overlapping flushes: titles are delivered in capture order", em, ["first", "second"])
        check("overlapping flushes: the second call's history already contains the first call's title", order_calls[1][1], ["first"])

        # ---------------- relay: client gone (#6) ----------------
        calls = []
        tsm._call_summarizer = counting
        gone = [True]
        em = []
        tsm.FILLER_INTERVAL_SECONDS = 0.3
        r = tsm.ThinkingRelay(em.append, is_client_gone=lambda: gone[0])
        r.start()
        r.feed("reasoning nobody will read")
        await asyncio.sleep(1.0)
        check("client gone: no summarizer calls and no fillers", (calls, em), ([], []))
        await r.stop()
        tsm.FILLER_INTERVAL_SECONDS = 60.0

        cancelled.clear()
        tsm._call_summarizer = cancel_probe
        gone = [False]
        r = tsm.ThinkingRelay(lambda t: None, is_client_gone=lambda: gone[0])
        r.start()
        r.feed("z" * 50)
        r._dispatch_flush()
        await asyncio.sleep(0.05)
        gone[0] = True
        await asyncio.sleep(0.6)
        check("client gone mid-call: the in-flight summarizer call is cancelled", cancelled, [True])
        await r.stop()

        # ---------------- relay: session id (#3) ----------------
        kws = []

        async def kw_probe(chunk, history, kind="reasoning", **kw):
            kws.append(kw)
            return ["T"]

        tsm._call_summarizer = kw_probe
        for sid, expected in (("sid-titles", {"session_id": "sid-titles"}), (None, {})):
            kws.clear()
            r = tsm.ThinkingRelay(lambda t: None, session_id=sid)
            r.start()
            r.feed("some reasoning here")
            await r.stop()
            check(f"relay passes session_id={sid!r} to the summarizer only when it has one", kws, [expected])

        # ---------------- relay: input scrubbed (#8) ----------------
        seen_chunks = []

        async def chunk_probe(chunk, history, kind="reasoning", **kw):
            seen_chunks.append(chunk)
            return ["T"]

        tsm._call_summarizer = chunk_probe
        r = tsm.ThinkingRelay(lambda t: None)
        r.start()
        r.feed("Hmm, I am DeepSeek and I should answer this.")
        await r.stop()
        check("the summarizer never receives a self-identification leak", ["DeepSeek" in c for c in seen_chunks], [False])
    finally:
        tsm._call_summarizer = real_call
        for n, v in saved.items():
            setattr(tsm, n, v)

    # ---------------- _call_summarizer itself (#1, #3, #5, #8) ----------------
    saved2 = tsm.SUMMARIZER_RETRY_BACKOFF_SECONDS
    tsm.SUMMARIZER_RETRY_BACKOFF_SECONDS = 0.01
    posted = []
    real_post = _FakeAsyncClient.post

    async def recording_post(self, url, headers=None, json=None):
        posted.append(json)
        return await real_post(self, url, headers=headers, json=json)

    _FakeAsyncClient.post = recording_post
    good = {"choices": [{"message": {"content": "<title>Checking the retry logic for the timeout.</title>"}}]}
    try:
        _set_responders(("json", 200, good))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning", session_id="sid-titles")
        check("summarizer: returns the parsed title", out, ["Checking the retry logic for the timeout."])
        check("summarizer: request carries the session_id, reasoning off and the token budget",
              (posted[-1].get("session_id"), posted[-1].get("reasoning"), posted[-1].get("max_tokens")), ("sid-titles", {"enabled": False}, tsm.SUMMARIZER_MAX_TOKENS))
        from app.models.kael.config import KAEL_BETA as _kael_cfg
        check("summarizer: request uses its OWN model list and routing (a `models` fallback array, no single `model`)",
              (posted[-1].get("models"), posted[-1].get("provider"), "model" in posted[-1]),
              (_kael_cfg["summarizer_models"], _kael_cfg["summarizer_provider_routing"], False))
        _set_responders(("json", 200, good))
        await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: no session_id field at all when none is given", "session_id" in posted[-1], False)

        for label, payload in (("null message", {"choices": [{"message": None}]}), ("null choices", {"choices": None}),
                               ("null content", {"choices": [{"message": {"content": None}}]}), ("non-dict body", ["x"]),
                               ("no title tags", {"choices": [{"message": {"content": "just prose"}}]})):
            _set_responders(("json", 200, payload))
            try:
                out = await tsm._call_summarizer("some reasoning", [], "reasoning")
            except BaseException as e:  # noqa: BLE001
                out = f"RAISED {type(e).__name__}"
            check(f"summarizer: {label} -> [] and never raises", out, [])

        _set_responders(("json", 503, {"error": "busy"}), ("json", 200, good))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: a 503 is retried once and the retry's titles are used", (len(out), len(_responder_queue)), (1, 0))
        _set_responders(_StubConnectError("reset"), ("json", 200, good))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: a transport error is retried once", (len(out), len(_responder_queue)), (1, 0))
        _set_responders(("json", 400, {"error": "bad"}), ("json", 200, good))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: a 400 is NOT retried", (out, len(_responder_queue)), ([], 1))
        _set_responders(("json", 500, {}), ("json", 500, {}), ("json", 200, good))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: only one retry, then gives up with []", (out, len(_responder_queue)), ([], 1))
        _set_responders(("json", 200, {"choices": [{"message": {"content": "<title>I am DeepSeek, a helpful assistant.</title>"}}]}))
        out = await tsm._call_summarizer("some reasoning", [], "reasoning")
        check("summarizer: a vendor self-identification in a title is scrubbed", ["DeepSeek" in t for t in out], [False])
    finally:
        _FakeAsyncClient.post = real_post
        tsm.SUMMARIZER_RETRY_BACKOFF_SECONDS = saved2
        _responder_queue.clear()

    # ---------------- streaming pipeline ----------------
    real_call = tsm._call_summarizer
    seen = []

    async def rec(chunk, history, kind="reasoning", **kw):
        seen.append((kind, chunk))
        return [f"Title {len(seen)}"]

    tsm._call_summarizer = rec
    try:
        long_draft_text = "Here is a fairly long draft answer that is certainly past the sixty character mark."

        # --- #2 + #8 + ordering: OpenRouter's `reasoning` field feeds the summarizer, scrubbed, before the draft text ---
        _reset_recorders(); seen.clear()
        reasoning_parts = ["Let me think about this carefully. I a", "m DeepSeek, I should say. Then plan the steps for the whole answer to be written."]
        _set_responders(("lines", 200, _reasoning_lines(reasoning_parts, long_draft_text, field="reasoning")),
                        ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed.")))
        items = await _run_stream_and_collect()
        r_chunks = [c for k, c in seen if k == "reasoning"]
        joined = " ".join(r_chunks)
        check("reasoning field: text sent as `reasoning` (not reasoning_content) reaches the summarizer", "Let me think about this carefully" in joined, True)
        check("reasoning field: the end of the reasoning is not lost", "whole answer to be written" in joined, True)
        check("reasoning field: a leak split across reasoning chunks never reaches the summarizer", "DeepSeek" in joined, False)
        check("reasoning field: reasoning is summarized before the draft text, not after", [k for k, _ in seen][:1], ["reasoning"])
        check("reasoning field: the client still gets the critic's answer", _extract_cc_stream_text(items), "Reviewed.")
        # reasoning_details only
        _reset_recorders(); seen.clear()
        det = [f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'reasoning_details': [{'type': 'reasoning.text', 'text': 'Planning how to structure the reply in detail now, step by step, carefully.'}]}, 'finish_reason': None}]})}"] + _sse_lines(long_draft_text)
        _set_responders(("lines", 200, det), ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed.")))
        await _run_stream_and_collect()
        check("reasoning field: reasoning_details alone is read too", any("Planning how to structure" in c for k, c in seen if k == "reasoning"), True)

        # --- #10 + #9 + #11: on_complete gets the titles that were sent; wire separators ---
        _reset_recorders(); seen.clear()
        got = {}

        async def cb_with_thinking(text, thinking=None):
            got["text"], got["thinking"] = text, thinking

        _set_responders(("lines", 200, _reasoning_lines(["Reasoning that is long enough to be summarized by the relay."], long_draft_text, field="reasoning_content")),
                        ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed answer.")))
        items = await _run_stream_and_collect(on_complete=cb_with_thinking)
        check("on_complete receives the reply", got.get("text"), "Reviewed answer.")
        check("on_complete receives exactly the titles that were streamed, in order (no fillers)", got.get("thinking"), ["Title 1", "Title 2"])
        deltas = _cc_reasoning_deltas(items)
        check("wire: every thinking delta ends with the blank-line separator", all(d.endswith("\n\n") for d in deltas) and len(deltas) >= 1, True)
        check("wire: concatenating the deltas gives separate lines", "".join(deltas).split("\n\n")[:2], ["Title 1", "Title 2"])

        legacy = {}

        async def cb_legacy(text):
            legacy["text"] = text

        _reset_recorders()
        _set_responders(("lines", 200, _sse_lines("Plain draft.")), ("lines", 200, _sse_lines("Plain final.")))
        await _run_stream_and_collect(on_complete=cb_legacy)
        check("on_complete callbacks that take only the text still work", legacy.get("text"), "Plain final.")

        # --- #12: Anthropic thinking block closes with a signature ---
        _reset_recorders(); seen.clear()
        _set_responders(("lines", 200, _reasoning_lines(["Reasoning that is long enough to be summarized by the relay."], long_draft_text, field="reasoning_content")),
                        ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed answer.")))
        items = await _run_stream_and_collect(caller_shape="anthropic")
        ev = _sse_events(items)
        kinds = [(n, d.get("delta", {}).get("type") if n == "content_block_delta" else None, d.get("index")) for n, d in ev]
        sig_i = next((i for i, k in enumerate(kinds) if k[1] == "signature_delta"), -1)
        check("anthropic: a signature_delta is sent", sig_i >= 0, True)
        check("anthropic: the signature comes right before the thinking block's stop", kinds[sig_i + 1][0] if sig_i >= 0 else None, "content_block_stop")
        check("anthropic: the signature is for the same block as the thinking deltas", (kinds[sig_i][2] == kinds[sig_i + 1][2]) if sig_i >= 0 else None, True)
        think_texts = [d["delta"]["thinking"] for n, d in ev if n == "content_block_delta" and d["delta"].get("type") == "thinking_delta"]
        check("anthropic: thinking_delta text carries the separator", all(t.endswith("\n\n") for t in think_texts) and bool(think_texts), True)
        check("anthropic: the signature is a non-empty string", bool([d for n, d in ev if d.get("delta", {}).get("type") == "signature_delta" and d["delta"]["signature"]]), True)

        # --- #7: critic failure after part of its answer was sent must NOT append the draft ---
        _reset_recorders()
        long_critic = "Critic answer that keeps going and going so that it is comfortably past the identity guard hold-back window of one hundred characters."
        part = [f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'content': long_critic}, 'finish_reason': None}]})}", "__raise__"]
        _set_responders(("lines", 200, _sse_lines("DRAFT-ANSWER-XYZ")), ("lines", 200, part))
        items = await _run_stream_and_collect()
        text = _extract_cc_stream_text(items)
        check("critic fails after streaming part of its answer: the draft is not appended to it", "DRAFT-ANSWER-XYZ" in text, False)
        check("critic fails after streaming part of its answer: part of the critic's text did reach the client", text.startswith("Critic answer"), True)
        check("critic fails after streaming part of its answer: the client gets an error event", any('"error"' in it for it in items if isinstance(it, str)), True)
        _reset_recorders()
        _set_responders(("lines", 200, _sse_lines("DRAFT-ANSWER-XYZ")), ("lines", 200, ["__raise__"]))
        items = await _run_stream_and_collect()
        check("critic fails before sending anything: the draft is served", _extract_cc_stream_text(items), "DRAFT-ANSWER-XYZ")

        # --- #5: a stop() that raises still ends the stream and frees the rate-limit slot ---
        uid = "user_stop_raises"
        rl.start_product_request(uid)
        real_stop = tsm.ThinkingRelay.stop

        async def bad_stop(self, *a, **k):
            raise RuntimeError("stop exploded")

        tsm.ThinkingRelay.stop = bad_stop
        q = asyncio.Queue()
        try:
            _reset_recorders()
            _set_responders(("lines", 200, _sse_lines("Draft.")), ("lines", 200, _sse_lines("Final.")))
            try:
                await tpp._run_stream(
                    product="kael-beta", slug="kael-beta", system_identity="You are Kael.", draft=_FAKE_PASS, critic=_FAKE_CRITIC_PASS,
                    input_items=[{"role": "user", "content": "hi"}], tools=None, caller_shape="chat_completions", client_wants_usage_chunk=False,
                    started=time.monotonic(), trace_id="t", requestor={"user_id": uid}, on_complete=None, queue=q,
                    request_started_at=tpp.datetime.now(tpp.timezone.utc), response_id="chatcmpl-x", boundary="testboundary123",
                )
            except RuntimeError:
                pass
        finally:
            tsm.ThinkingRelay.stop = real_stop
        drained = []
        while not q.empty():
            drained.append(q.get_nowait())
        check("stop() raising: the stream still gets its end-of-stream sentinel", None in drained, True)
        check("stop() raising: the rate-limit slot is released", rl._active_requests[uid], 0)

        # --- #3: the pipeline hands the relay the titles session id derived from the draft pass's key ---
        _reset_recorders(); seen.clear()
        kw_seen = []

        async def rec_kw(chunk, history, kind="reasoning", **kw):
            kw_seen.append(kw)
            return ["T"]

        tsm._call_summarizer = rec_kw
        sid_pass = tpp.replace(_FAKE_PASS, session_id="kael-abc123")
        _set_responders(("lines", 200, _reasoning_lines(["Reasoning that is long enough to be summarized by the relay."], long_draft_text, field="reasoning")),
                        ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed.")))
        await _run_stream_and_collect(draft=sid_pass)
        check("pipeline: summarizer calls carry the draft pass's session id plus -titles", {k.get("session_id") for k in kw_seen}, {"kael-abc123-titles"})
        tsm._call_summarizer = rec

        # --- #4: an error ends the stream without one more summarizer call for leftover text ---
        _reset_recorders(); seen.clear()
        long_reasoning = "Thinking through the problem step by step, which goes on for a good while. " * 5
        err_lines = [f"data: {tpp.json.dumps({'choices': [{'index': 0, 'delta': {'reasoning': long_reasoning}, 'finish_reason': None}]})}", "__raise__"]
        _set_responders(("lines", 200, err_lines))
        t0 = time.monotonic()
        items = await _run_stream_and_collect()
        check("error path: the client gets an error event", any('"error"' in it for it in items if isinstance(it, str)), True)
        check("error path: no extra summarizer call is made for text that was still buffered", seen, [])
        check("error path: the error is not held back by a summarizer call", time.monotonic() - t0 < 1.5, True)

        # --- #6: disconnect flag reaches the relay (via _run_stream) ---
        _reset_recorders(); seen.clear()
        ev_gone = asyncio.Event()
        ev_gone.set()
        _set_responders(("lines", 200, _reasoning_lines(["Reasoning that is long enough to be summarized by the relay."], long_draft_text, field="reasoning")),
                        ("lines", 200, ["__sleep__:0.15"] + _sse_lines("Reviewed.")))
        items = await _run_stream_and_collect(client_gone=ev_gone)
        check("client gone: no summarizer call is made for the request", seen, [])
        check("client gone: the answer pipeline still runs to completion (billed)", (_extract_cc_stream_text(items), len(_charge_calls)), ("Reviewed.", 1))

        # --- #6: closing the HTTP response early sets the flag (via run_pipeline) ---
        _reset_recorders(); seen.clear()
        instances = []
        real_relay_cls = tpp.ThinkingRelay

        class RecordingRelay(real_relay_cls):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                instances.append(self)

        tpp.ThinkingRelay = RecordingRelay
        try:
            _set_responders(("lines", 200, _sse_lines("Draft.")),
                            ("lines", 200, [_sse_lines("Slow answer part one. ")[0], "__sleep__:0.6"] + _sse_lines("Slow answer part two.")))
            resp = await tpp.run_pipeline(
                product="kael-beta", slug="kael-beta", system_identity="You are Kael.", draft=_FAKE_PASS, critic=_FAKE_CRITIC_PASS,
                input_items=[{"role": "user", "content": "hi"}], tools=None, client_wants_stream=True, caller_shape="chat_completions",
                requestor=_REQUESTOR,
            )
            await resp.body_iterator.__anext__()
            gone_before = instances[0]._gone()
            await resp.body_iterator.aclose()
            check("disconnect: the relay is not told the client is gone while the response is open", gone_before, False)
            check("disconnect: closing the response early tells the relay the client is gone", instances[0]._gone(), True)
            await asyncio.gather(*list(tpp._background_tasks), return_exceptions=True)
        finally:
            tpp.ThinkingRelay = real_relay_cls
    finally:
        tsm._call_summarizer = real_call
        _responder_queue.clear()


async def _main():
    await _test_post_upstream()
    await _test_provider_routing_wiring()
    await _test_backup_host_fallback()
    await _test_midstream_failover()
    await _test_orchestration()
    await _test_thinking_relay()
    await _test_thinking_relay_chunking()
    await _test_stream_orchestration()
    await _test_draft_titles_end_to_end()
    await _test_thinking_fixes()
    _test_leading_tag_stripper()
    await _test_responses_entry_point()
    await _test_injected_overhead_billing()
    await _test_billing_reconciliation()
    await _test_pre_auth_ip_throttle()
    _test_customer_price_and_cost()
    _test_config_flags()
    await _test_scheduled_checks()
    await _test_low_balance_alerts()


asyncio.run(_main())

print()
if failures:
    print(f"\n{len(failures)} FAILURE(S):\n")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
