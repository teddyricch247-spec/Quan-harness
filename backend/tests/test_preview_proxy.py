"""§23.7 — the Live Preview gateway, end to end, against fakes.

Same approach as test_deploy_pipeline.py / test_agent_loop_audit.py: every
collaborator the gateway can reach (project lookup, the Sprite's URL, the upstream
HTTP/WebSocket client, the clock, sleep) is replaced with an in-memory double, and
the assertions are on the ASGI messages the gateway sends and the requests it
makes. Nothing here opens a socket.

What this does NOT cover: the real httpx/websockets adapters at the bottom of
preview_proxy.py, or a real Sprite's wake behaviour — see
docs/PHASE5_3_5_4_NOTES.md for the live checks that remain.
"""
import asyncio
import types
from contextlib import asynccontextmanager
from unittest import mock

from app.services import preview_proxy as pp
from app.services import preview_tokens
from app.services.preview_proxy import GatewayDeps, PreviewGateway, ProjectRef, UpstreamError

SECRET = "proxy-test-signing-secret-0123456789abcdef"
SUB = "my-app-1a2b3c4d"
BASE = "preview.example.com"
HOST = f"{SUB}.{BASE}"
ORIGIN = "https://qh-abc-org1.sprites.app"


def _settings(**over):
    base = dict(
        preview_enabled=True, preview_base_domain=BASE, preview_signing_secret=SECRET, preview_scheme="https",
        preview_session_ttl_seconds=3600, preview_enter_token_ttl_seconds=60, preview_cold_start_wait_seconds=30,
        preview_response_max_seconds=300, preview_ws_idle_seconds=90, preview_ws_max_seconds=900,
        frontend_url="https://app.example.com", cors_origins_list=["https://app.example.com", "http://localhost:3000"],
    )
    base.update(over)
    return types.SimpleNamespace(**base)


class FakeResp:
    def __init__(self, status=200, headers=None, chunks=(b"hello",), hang=False):
        self.status_code = status
        self.headers = headers or [("Content-Type", "text/html")]
        self._chunks, self._hang = chunks, hang

    async def iter_bytes(self):
        for c in self._chunks:
            yield c
        if self._hang:
            await asyncio.sleep(3600)


class FakeUpstream:
    """open_stream double: pops a scripted outcome per call (a FakeResp or an exception)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        outcome = self.script.pop(0) if self.script else FakeResp()

        @asynccontextmanager
        async def cm():
            if isinstance(outcome, Exception):
                raise outcome
            yield outcome

        return cm()


class Unavailable(Exception):
    pass


def _gateway(script=(), settings=None, project=ProjectRef("proj-1", "u1"), upstream=None, clock=None):
    up = FakeUpstream(script)
    slept = []
    now = clock or [1000.0]

    async def lookup(sub):
        return project if sub == SUB else None

    async def get_upstream(pid):
        if upstream == "unavailable":
            raise Unavailable("This project's workspace hasn't been created yet — deploy it first.")
        return ORIGIN

    async def fake_sleep(d):
        slept.append(d)
        now[0] += d

    deps = GatewayDeps(
        settings=lambda: settings or _settings(), lookup_project=lookup, get_upstream=get_upstream,
        auth_headers=lambda: {"Authorization": "Bearer SPRITES_TOKEN"}, open_stream=up,
        connect_ws=None, unavailable_exc=Unavailable, sleep=fake_sleep, now=lambda: now[0],
    )
    gw = PreviewGateway(deps)
    return gw, up, slept, now


def _scope(path="/", method="GET", host=HOST, headers=None, query=b""):
    hdrs = [(b"host", host.encode())] + [(k.lower().encode(), v.encode()) for k, v in (headers or [])]
    return {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": query, "headers": hdrs}


async def _drive(gw, scope, body_chunks=()):
    sent = []
    inbox = [{"type": "http.request", "body": c, "more_body": i < len(body_chunks) - 1} for i, c in enumerate(body_chunks)] or [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(m):
        sent.append(m)

    await gw.handle_http(scope, receive, send, SUB)
    return sent


def _status(sent):
    return sent[0]["status"]


def _hdr(sent, name):
    return [v.decode() for k, v in sent[0]["headers"] if k.decode() == name.lower()]


def _body(sent):
    return b"".join(m.get("body", b"") for m in sent[1:])


def _session_cookie(sub=SUB, pid="proj-1"):
    return "qh_preview=" + preview_tokens.mint_session_token(SECRET, pid, sub, 3600)


def _authed(path="/", method="GET", extra=None, **kw):
    return _scope(path, method, headers=[("Cookie", _session_cookie()), *(extra or [])], **kw)


def _run(coro):
    return asyncio.run(coro)


def setup_function(_):
    preview_tokens._reset_for_tests()


# ---- auth gate ----------------------------------------------------------------

def test_request_without_a_session_cookie_gets_401_and_never_reaches_the_sprite():
    gw, up, _, _ = _gateway()
    sent = _run(_drive(gw, _scope("/")))
    assert _status(sent) == 401 and up.calls == []
    assert b"Quan Harness" in _body(sent)


def test_forged_or_foreign_cookie_is_rejected():
    gw, up, _, _ = _gateway()
    other = _scope("/", headers=[("Cookie", _session_cookie(sub="someone-else-aaaa"))])
    assert _status(_run(_drive(gw, other))) == 401
    forged = _scope("/", headers=[("Cookie", "qh_preview=not.a.jwt")])
    assert _status(_run(_drive(gw, forged))) == 401
    assert up.calls == []


def test_cookie_for_a_different_project_on_this_subdomain_is_404():
    gw, up, _, _ = _gateway()
    scope = _scope("/", headers=[("Cookie", _session_cookie(pid="some-other-project"))])
    assert _status(_run(_drive(gw, scope))) == 404 and up.calls == []


def test_unknown_subdomain_is_404():
    gw, up, _, _ = _gateway(project=None)
    assert _status(_run(_drive(gw, _authed()))) == 404 and up.calls == []


def test_preview_not_configured_answers_503_not_a_broken_page():
    gw, up, _, _ = _gateway(settings=_settings(preview_enabled=False))
    assert _status(_run(_drive(gw, _authed()))) == 503 and up.calls == []


def test_error_pages_can_only_be_framed_by_the_harness_frontend():
    gw, _, _, _ = _gateway()
    sent = _run(_drive(gw, _scope("/")))
    assert _hdr(sent, "content-security-policy") == ["frame-ancestors https://app.example.com http://localhost:3000"]


# ---- enter token ----------------------------------------------------------------

def _enter_scope(token):
    return _scope(pp.rules.ENTER_PATH, query=f"t={token}".encode())


def test_enter_token_sets_a_host_only_httponly_cookie_and_redirects_home():
    gw, _, _, _ = _gateway()
    token = preview_tokens.mint_enter_token(SECRET, "proj-1", SUB, user_id="u1")
    sent = _run(_drive(gw, _enter_scope(token)))
    assert _status(sent) == 302 and _hdr(sent, "location") == ["/"]
    cookie = _hdr(sent, "set-cookie")[0]
    assert cookie.startswith("qh_preview=") and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=None" in cookie and "Domain" not in cookie
    assert _hdr(sent, "referrer-policy") == ["no-referrer"]


def test_enter_token_cannot_be_used_twice():
    gw, _, _, _ = _gateway()
    token = preview_tokens.mint_enter_token(SECRET, "proj-1", SUB)
    assert _status(_run(_drive(gw, _enter_scope(token)))) == 302
    assert _status(_run(_drive(gw, _enter_scope(token)))) == 401


def test_enter_with_bad_token_or_wrong_preview_is_refused():
    gw, _, _, _ = _gateway()
    assert _status(_run(_drive(gw, _enter_scope("garbage")))) == 401
    wrong = preview_tokens.mint_enter_token(SECRET, "proj-1", "another-sub-1111")
    assert _status(_run(_drive(gw, _enter_scope(wrong)))) == 401


def test_enter_does_not_accept_a_post():
    gw, _, _, _ = _gateway()
    token = preview_tokens.mint_enter_token(SECRET, "proj-1", SUB)
    scope = _scope(pp.rules.ENTER_PATH, method="POST", query=f"t={token}".encode())
    assert _status(_run(_drive(gw, scope))) == 405


def test_other_reserved_paths_are_never_forwarded_to_the_app():
    gw, up, _, _ = _gateway()
    assert _status(_run(_drive(gw, _authed("/__qh/anything")))) == 404 and up.calls == []


# ---- proxying -------------------------------------------------------------------

def test_authenticated_request_is_forwarded_with_the_sprites_token_not_the_users_credentials():
    gw, up, _, _ = _gateway([FakeResp(200, chunks=(b"<html>", b"ok"))])
    scope = _authed("/dash", extra=[("Authorization", "Bearer USER_JWT"), ("Cookie", "x"), ("Accept", "text/html"),
                                    ("X-Forwarded-Host", "evil.com")], query=b"a=1")
    # _authed already set a Cookie; rebuild so we control cookie header exactly
    scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"cookie"] + [(b"cookie", f"{_session_cookie()}; sid=abc".encode())]
    sent = _run(_drive(gw, scope))
    assert _status(sent) == 200 and _body(sent) == b"<html>ok"
    call = up.calls[0]
    assert call["url"] == f"{ORIGIN}/dash?a=1"
    headers = {k.lower(): v for k, v in call["headers"]}
    assert headers["authorization"] == "Bearer SPRITES_TOKEN"            # the user's own Authorization never goes upstream
    assert headers["cookie"] == "sid=abc"                                # the harness cookie is stripped, the app's own kept
    assert headers["x-forwarded-host"] == HOST and headers["x-forwarded-proto"] == "https"
    assert "host" not in headers
    assert headers["accept"] == "text/html"


def test_a_request_target_that_is_not_an_absolute_path_is_refused_before_it_can_change_the_upstream_host():
    # origin + path is string concatenation: "@evil.example/" would otherwise turn
    # `https://sprite.example` into `https://sprite.example@evil.example/` — a request
    # to another host carrying the Sprites API token.
    for bad in ("@evil.example/", "evil.example/x", "*"):
        gw, up, _, _ = _gateway([FakeResp(200, chunks=(b"ok",))])
        sent = _run(_drive(gw, _authed(bad)))
        assert _status(sent) == 400, bad
        assert up.calls == [], bad


def test_response_is_sanitised_for_framing_cookies_and_internal_redirects():
    gw, _, _, _ = _gateway([FakeResp(302, headers=[
        ("Location", f"{ORIGIN}/next"), ("X-Frame-Options", "DENY"),
        ("Content-Security-Policy", "frame-ancestors 'none'; img-src *"),
        ("Set-Cookie", "sid=1; Domain=.preview.example.com; SameSite=Lax"),
        ("Set-Cookie", "qh_preview=forged"), ("Transfer-Encoding", "chunked")])])
    sent = _run(_drive(gw, _authed()))
    assert _hdr(sent, "location") == [f"https://{HOST}/next"]            # internal Sprite hostname never leaks
    assert _hdr(sent, "x-frame-options") == []
    csp = _hdr(sent, "content-security-policy")
    assert csp[0] == "img-src *" and csp[-1] == "frame-ancestors https://app.example.com http://localhost:3000"
    cookies = _hdr(sent, "set-cookie")
    assert len(cookies) == 1 and "domain" not in cookies[0].lower() and "SameSite=None" in cookies[0]
    assert _hdr(sent, "transfer-encoding") == [] and _hdr(sent, "x-robots-tag") == ["noindex, nofollow"]


def test_post_body_is_streamed_through_and_a_gateway_error_is_not_retried():
    gw, up, slept, _ = _gateway([FakeResp(502, chunks=(b"bad gateway",))])
    sent = _run(_drive(gw, _authed(method="POST"), body_chunks=(b"abc", b"def")))
    assert len(up.calls) == 1 and slept == []                            # a POST is never replayed
    assert _status(sent) == 502


def test_head_request_sends_headers_and_no_body():
    gw, _, _, _ = _gateway([FakeResp(200, chunks=(b"should-not-appear",))])
    sent = _run(_drive(gw, _authed(method="HEAD")))
    assert _status(sent) == 200 and _body(sent) == b""


# ---- cold start -------------------------------------------------------------------

def test_cold_start_502s_are_waited_out_and_the_eventual_page_is_served():
    gw, up, slept, _ = _gateway([FakeResp(502), FakeResp(502), FakeResp(200, chunks=(b"up",))])
    sent = _run(_drive(gw, _authed()))
    assert _status(sent) == 200 and _body(sent) == b"up"
    assert len(up.calls) == 3 and slept == [0.5, 1.0]


def test_connection_errors_during_wake_are_retried_too():
    gw, up, _, _ = _gateway([UpstreamError("connect refused"), FakeResp(200, chunks=(b"up",))])
    sent = _run(_drive(gw, _authed()))
    assert _status(sent) == 200 and len(up.calls) == 2


def test_if_the_app_never_comes_up_the_person_gets_a_self_refreshing_still_starting_page():
    gw, up, slept, _ = _gateway([FakeResp(502)] * 40)
    sent = _run(_drive(gw, _authed()))
    assert _status(sent) == 503 and b"still starting" in _body(sent)
    assert 'http-equiv="refresh"' in _body(sent).decode() and _hdr(sent, "retry-after") == ["3"]
    assert abs(sum(slept) - 30) < 1e-6                                   # bounded by the configured cold-start wait


def test_a_running_apps_own_502_is_passed_through_immediately_not_delayed_30_seconds():
    # One success marks the project warm; its 502 afterwards is the app's, not a waking Sprite's.
    gw, up, slept, _ = _gateway([FakeResp(200), FakeResp(502, chunks=(b"app says 502",))])
    _run(_drive(gw, _authed()))
    sent = _run(_drive(gw, _authed("/api")))
    assert _status(sent) == 502 and _body(sent) == b"app says 502" and slept == []


def test_warmth_expires_so_a_sprite_that_slept_again_gets_the_cold_start_treatment():
    gw, up, slept, now = _gateway([FakeResp(200), FakeResp(502), FakeResp(200, chunks=(b"awake",))])
    _run(_drive(gw, _authed()))
    now[0] += 120                                                        # idle long enough for the Sprite to hibernate
    sent = _run(_drive(gw, _authed()))
    assert _status(sent) == 200 and _body(sent) == b"awake" and len(slept) == 1


def test_connection_error_when_warm_is_a_plain_502_not_a_retry_loop():
    gw, up, slept, _ = _gateway([FakeResp(200), UpstreamError("reset")])
    _run(_drive(gw, _authed()))
    sent = _run(_drive(gw, _authed("/x")))
    assert _status(sent) == 502 and slept == []


# ---- billing guards -----------------------------------------------------------------

def test_a_response_that_never_ends_is_cut_off_at_the_configured_ceiling():
    # A held-open response (SSE, long poll) keeps a Sprite billed — it must be bounded.
    gw, _, _, _ = _gateway([FakeResp(200, chunks=(b"data: 1\n\n",), hang=True)], settings=_settings(preview_response_max_seconds=0.05))
    gw.deps.now = lambda: __import__("time").monotonic()
    sent = asyncio.run(asyncio.wait_for(_drive(gw, _authed("/events")), timeout=5))
    assert _status(sent) == 200 and sent[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


def test_sprite_unavailable_is_shown_as_a_clear_503_message():
    gw, up, _, _ = _gateway(upstream="unavailable")
    sent = _run(_drive(gw, _authed()))
    assert _status(sent) == 503 and b"deploy it first" in _body(sent) and up.calls == []


# ---- middleware routing ---------------------------------------------------------------

class _Inner:
    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"api"})


def _mw_run(host, settings=None, gw=None, scope_type="http", path="/"):
    inner = _Inner()
    gw = gw or _gateway()[0]
    mw = pp.PreviewHostMiddleware(inner, gateway=gw)
    scope = _scope(path, host=host)
    scope["type"] = scope_type
    sent = []

    async def receive():
        return {"type": "websocket.connect"} if scope_type == "websocket" else {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    with mock.patch("app.config.get_settings", return_value=settings or _settings()):
        _run(mw(scope, receive, send))
    return inner, sent


def test_normal_hosts_pass_straight_through_to_the_api():
    inner, sent = _mw_run("quan-harness.onrender.com")
    assert inner.calls == 1 and sent[0]["status"] == 200


def test_malformed_hosts_under_the_preview_domain_are_answered_by_the_proxy_never_the_api():
    for host in (f"a.b.{BASE}", BASE, f"-x.{BASE}"):
        inner, sent = _mw_run(host)
        assert inner.calls == 0 and sent[0]["status"] == 404, host


def test_with_no_preview_domain_configured_everything_passes_through():
    inner, _ = _mw_run(HOST, settings=_settings(preview_base_domain=""))
    assert inner.calls == 1


def test_lifespan_and_other_scope_types_are_untouched():
    inner = _Inner()
    mw = pp.PreviewHostMiddleware(inner, gateway=_gateway()[0])
    async def noop(_message):
        pass

    _run(mw({"type": "lifespan"}, None, noop))
    assert inner.calls == 1


def test_unauthenticated_websocket_is_refused_before_it_is_accepted():
    inner, sent = _mw_run(HOST, scope_type="websocket")
    assert inner.calls == 0 and sent == [{"type": "websocket.close", "code": 1008}]


# ---- WebSocket relay (the billing guard) --------------------------------------------------

class FakeSocket:
    subprotocol = None

    def __init__(self, incoming=(), hang=True):
        self.incoming, self.sent, self.closed, self.hang = list(incoming), [], False, hang

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self.incoming:
            return self.incoming.pop(0)
        if self.hang:
            await asyncio.sleep(3600)
        raise pp.UpstreamClosed("done")

    async def close(self, code=1000):
        self.closed = True


async def _ws_run(upstream, client_messages=(), idle=0.05, max_seconds=5.0, client_hangs=True):
    sent = []
    inbox = list(client_messages)

    async def receive():
        if inbox:
            return inbox.pop(0)
        if client_hangs:
            await asyncio.sleep(3600)
        return {"type": "websocket.disconnect"}

    async def send(m):
        sent.append(m)

    reason = await asyncio.wait_for(pp.relay_websocket(receive, send, upstream, idle_seconds=idle, max_seconds=max_seconds), timeout=5)
    return reason, sent


def test_frames_flow_both_ways_then_a_silent_socket_is_closed_for_idleness():
    up = FakeSocket(incoming=["from-app"])
    reason, sent = _run(_ws_run(up, client_messages=[{"type": "websocket.receive", "text": "from-browser"}]))
    assert reason == "idle" and up.closed
    assert up.sent == ["from-browser"] and {"type": "websocket.send", "text": "from-app"} in sent
    assert sent[-1]["type"] == "websocket.close" and sent[-1]["code"] == 1001


def test_a_chatty_socket_is_still_closed_at_the_max_lifetime():
    class Chatty(FakeSocket):
        async def recv(self):
            await asyncio.sleep(0.005)
            return "tick"

    reason, _ = _run(_ws_run(Chatty(), idle=10, max_seconds=0.08))
    assert reason == "max_lifetime"


def test_client_disconnect_closes_the_upstream_socket():
    up = FakeSocket()
    reason, _ = _run(_ws_run(up, client_messages=[{"type": "websocket.disconnect"}], idle=10))
    assert reason == "client" and up.closed


def test_upstream_closing_ends_the_session_with_a_normal_close():
    up = FakeSocket(incoming=["bye"], hang=False)
    reason, sent = _run(_ws_run(up, idle=10))
    assert reason == "upstream" and sent[-1] == {"type": "websocket.close", "code": 1000}


def test_binary_frames_are_relayed_as_bytes():
    up = FakeSocket(incoming=[b"\x00\x01"])
    _, sent = _run(_ws_run(up, client_messages=[{"type": "websocket.receive", "bytes": b"\x09"}]))
    assert {"type": "websocket.send", "bytes": b"\x00\x01"} in sent and up.sent == [b"\x09"]
