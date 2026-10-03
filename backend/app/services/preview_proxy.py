"""
§23.7 — the Live Preview proxy. The person's iframe never talks to a Sprite's own
URL; it talks to `https://<subdomain>.<PREVIEW_BASE_DOMAIN>`, which lands on this
backend, which authenticates the request and relays it to the Sprite (attaching
the Sprites token the person never sees). "No shareable links": without a valid
session cookie a preview host answers 401 and nothing else.

Shape: a raw ASGI middleware (not a FastAPI router) because (a) the preview must
be served from the ROOT of its own origin, so it can't live under a path prefix,
and (b) WebSockets need to pass through and Starlette's BaseHTTPMiddleware can't
carry them. Every host under the preview domain is owned by this module: a request
for `anything.<PREVIEW_BASE_DOMAIN>` is handled here or refused here — it never
falls through to the API's own routes (preview_rules.classify_host's tri-state).

All I/O is injected (`GatewayDeps`) so the whole flow — auth, cold-start retry,
header rewriting, stream cut-offs — runs under test with fakes. The real adapters
(httpx, websockets) at the bottom are thin on purpose.

WHAT KEEPS A SPRITE BILLED, AND WHAT THIS DOES ABOUT IT (§23.7: "the one thing to
get right"). Per the Sprites docs, an open TCP connection keeps a Sprite awake.
So nothing here may hold one longer than a person is plausibly looking:
  - The HTTP client keeps NO idle connections (max_keepalive_connections=0): each
    proxied request opens and closes its own, so a pooled keep-alive socket can't
    sit open against the Sprite between requests.
  - A single proxied response (SSE, long poll) is cut off at
    preview_response_max_seconds.
  - A WebSocket is closed after preview_ws_idle_seconds of silence and at
    preview_ws_max_seconds regardless. (The frontend also unloads the iframe when
    the tab is hidden — the other half of the same guarantee.)
  - Nothing polls the Sprite's URL: status uses the Sprites metadata API.

COLD START. A request that arrives while the Sprite is hibernated wakes it, and the
platform answers 502 until the service is back up. For GET/HEAD, and only when no
request has succeeded recently (so a *running* app's own 502/503 isn't delayed),
the proxy retries with backoff for up to preview_cold_start_wait_seconds; after
that the person sees a "still starting" page that refreshes itself.
"""
import asyncio
import logging
import time
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncContextManager, AsyncIterator, Awaitable, Callable, Protocol

from app.services import preview_rules as rules
from app.services import preview_tokens

logger = logging.getLogger(__name__)

# A success newer than this means the Sprite is awake, so a 5xx from it is the
# app's own and is passed through immediately instead of being retried.
_WARM_SECONDS = 20.0
_PROJECT_CACHE_TTL = 60.0
_NEGATIVE_CACHE_TTL = 10.0


class UpstreamError(Exception):
    """A transport-level failure talking to the Sprite (connect/read/TLS)."""


class UpstreamClosed(Exception):
    """The upstream WebSocket closed."""


class UpstreamResponse(Protocol):
    status_code: int
    headers: list[tuple[str, str]]

    def iter_bytes(self) -> AsyncIterator[bytes]: ...


class UpstreamSocket(Protocol):
    subprotocol: str | None

    async def send(self, data: str | bytes) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self, code: int = 1000) -> None: ...


@dataclass
class ProjectRef:
    project_id: str
    user_id: str | None = None


@dataclass
class GatewayDeps:
    settings: Callable[[], Any]
    lookup_project: Callable[[str], Awaitable[ProjectRef | None]]
    get_upstream: Callable[[str], Awaitable[str]]  # raises preview_runtime.PreviewUnavailable
    auth_headers: Callable[[], dict[str, str]]
    open_stream: Callable[..., AsyncContextManager[UpstreamResponse]]  # (method, url, headers, body) -> response
    connect_ws: Callable[..., Awaitable[UpstreamSocket]]  # (url, headers, subprotocols) -> socket
    unavailable_exc: type[Exception] = Exception
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    now: Callable[[], float] = time.monotonic


# ---------------------------------------------------------------------------
# Small ASGI helpers
# ---------------------------------------------------------------------------


def _header_map(scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in scope.get("headers", []):
        out.setdefault(name.decode("latin-1").lower(), value.decode("latin-1"))
    return out


def _header_list(scope) -> list[tuple[str, str]]:
    return [(n.decode("latin-1"), v.decode("latin-1")) for n, v in scope.get("headers", [])]


async def _respond(send, status: int, body: str | bytes, headers: list[tuple[str, str]] | None = None) -> None:
    payload = body.encode("utf-8") if isinstance(body, str) else body
    all_headers = [("content-type", "text/html; charset=utf-8"), ("cache-control", "no-store"), ("content-length", str(len(payload)))]
    all_headers += headers or []
    await send({"type": "http.response.start", "status": status, "headers": [(k.lower().encode("latin-1"), v.encode("latin-1", "replace")) for k, v in all_headers]})
    await send({"type": "http.response.body", "body": payload})


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class PreviewGateway:
    def __init__(self, deps: GatewayDeps):
        self.deps = deps
        self._project_cache: dict[str, tuple[float, ProjectRef | None]] = {}
        self._last_ok: dict[str, float] = {}

    # -- shared -------------------------------------------------------------

    def _settings(self):
        return self.deps.settings()

    def _frame_ancestors(self) -> list[str]:
        s = self._settings()
        return rules.frame_ancestor_sources([s.frontend_url, *s.cors_origins_list])

    def _guard_headers(self) -> list[tuple[str, str]]:
        sources = " ".join(self._frame_ancestors()) or "'none'"
        return [("content-security-policy", f"frame-ancestors {sources}"), ("x-robots-tag", "noindex, nofollow")]

    async def _page(self, send, status: int, title: str, message: str, refresh: int | None = None, extra=None) -> None:
        headers = self._guard_headers() + (extra or [])
        if refresh:
            headers.append(("retry-after", str(refresh)))
        await _respond(send, status, rules.error_page_html(title, message, refresh), headers)

    async def _lookup(self, subdomain: str) -> ProjectRef | None:
        now = self.deps.now()
        hit = self._project_cache.get(subdomain)
        if hit is not None and hit[0] > now:
            return hit[1]
        ref = await self.deps.lookup_project(subdomain)
        self._project_cache[subdomain] = (now + (_PROJECT_CACHE_TTL if ref else _NEGATIVE_CACHE_TTL), ref)
        return ref

    def _authenticate(self, scope, subdomain: str) -> dict | None:
        secret = self._settings().preview_signing_secret
        cookie = rules.read_cookie(_header_map(scope).get("cookie"))
        if not cookie:
            return None
        try:
            return preview_tokens.verify_session_token(secret, cookie, subdomain)
        except preview_tokens.PreviewTokenError:
            return None

    # -- entry points ---------------------------------------------------------

    async def reject(self, scope, receive, send, status: int = 404) -> None:
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        await self._page(send, status, "Not found", "There is no preview at this address.")

    async def handle_http(self, scope, receive, send, subdomain: str) -> None:
        if not self._settings().preview_enabled:
            return await self._page(send, 503, "Preview isn't set up", "Live Preview isn't configured on this server.")

        path = scope.get("path", "/")
        if path == rules.ENTER_PATH:
            return await self._handle_enter(scope, send, subdomain)
        if path.startswith(rules.RESERVED_PREFIX):
            return await self._page(send, 404, "Not found", "There is no such page.")

        claims = self._authenticate(scope, subdomain)
        if claims is None:
            return await self._page(
                send, 401, "Open this preview from Quan Harness",
                "This preview can only be opened from inside your Quan Harness project. If you were just using it, the session may have expired — reopen it there.",
            )
        ref = await self._lookup(subdomain)
        if ref is None or ref.project_id != claims.get("pid"):
            return await self._page(send, 404, "Not found", "There is no preview at this address.")

        try:
            origin = await self.deps.get_upstream(ref.project_id)
        except self.deps.unavailable_exc as exc:
            return await self._page(send, 503, "Preview unavailable", str(exc), refresh=None)

        await self._proxy_http(scope, receive, send, subdomain, ref, origin)

    # -- enter ----------------------------------------------------------------

    async def _handle_enter(self, scope, send, subdomain: str) -> None:
        s = self._settings()
        if scope.get("method", "GET").upper() != "GET":
            return await self._page(send, 405, "Not allowed", "That request isn't supported.")
        query = urllib.parse.parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = (query.get("t") or [""])[0]
        try:
            claims = preview_tokens.redeem_enter_token(s.preview_signing_secret, token, subdomain)
        except preview_tokens.PreviewTokenError:
            return await self._page(
                send, 401, "This link has expired",
                "Preview links are single-use and short-lived. Reopen the preview from your Quan Harness project.",
            )
        ref = await self._lookup(subdomain)
        if ref is None or ref.project_id != claims["pid"]:
            return await self._page(send, 404, "Not found", "There is no preview at this address.")
        session = preview_tokens.mint_session_token(
            s.preview_signing_secret, ref.project_id, subdomain, s.preview_session_ttl_seconds, user_id=claims.get("uid")
        )
        cookie = rules.build_session_cookie(session, s.preview_session_ttl_seconds, secure=s.preview_scheme == "https")
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": [
                (b"location", b"/"),
                (b"set-cookie", cookie.encode("latin-1")),
                (b"cache-control", b"no-store"),
                (b"referrer-policy", b"no-referrer"),  # the token was in this URL; never let it ride out in a Referer
                (b"content-length", b"0"),
            ],
        })
        await send({"type": "http.response.body", "body": b""})

    # -- HTTP proxy -----------------------------------------------------------

    async def _proxy_http(self, scope, receive, send, subdomain: str, ref: ProjectRef, origin: str) -> None:
        s = self._settings()
        method = scope.get("method", "GET").upper()
        raw_path = scope.get("raw_path") or urllib.parse.quote(scope.get("path", "/")).encode("latin-1")
        if not raw_path.startswith(b"/"):
            # origin + path is plain string concatenation, so a request target that
            # doesn't start with "/" (e.g. "@evil.example/") would change the URL's
            # *host* — and this request carries the Sprites API token. Refuse it.
            await self._page(send, 400, "Bad request", "This request could not be forwarded to the preview.")
            return
        query = scope.get("query_string", b"")
        url = origin + raw_path.decode("latin-1") + (("?" + query.decode("latin-1")) if query else "")

        public_host = f"{subdomain}.{s.preview_base_domain.strip().strip('.').lower()}"
        public_origin = rules.public_origin(subdomain, s.preview_base_domain, s.preview_scheme)
        headers = rules.filter_request_headers(_header_list(scope))
        headers += rules.forwarded_headers(public_host, s.preview_scheme)
        headers += list(self.deps.auth_headers().items())

        body = None if method in ("GET", "HEAD") else _body_iter(receive)

        now = self.deps.now()
        warm = ref.project_id in self._last_ok and now - self._last_ok[ref.project_id] < _WARM_SECONDS
        # `cold` = the Sprite may be mid-wake, so a gateway error is worth waiting out.
        # A recently-successful project is awake: its 5xx is the app's own, passed through.
        delays = [] if warm else rules.backoff_delays(s.preview_cold_start_wait_seconds)
        cold = bool(delays)
        safe_to_retry = rules.is_retryable(method, 502) and body is None  # GET/HEAD with no body to replay
        starting_page = ("The preview is still starting", "The app is waking up. This page will retry on its own.")

        attempt = 0
        while True:
            try:
                async with self.deps.open_stream(method, url, headers, body) as resp:
                    waking = safe_to_retry and rules.is_retryable(method, resp.status_code)
                    if not (waking and cold):
                        if resp.status_code not in rules.RETRYABLE_STATUSES:
                            self._last_ok[ref.project_id] = self.deps.now()
                        return await self._relay(send, resp, method, urllib.parse.urlsplit(origin).hostname or "", public_origin)
                    if attempt >= len(delays):
                        return await self._page(send, 503, *starting_page, refresh=3)
                    # else: fall out of the `async with` (closing this response) and retry
            except UpstreamError as exc:
                logger.info("Preview upstream error for %s: %s", ref.project_id, exc)
                if not (safe_to_retry and cold):
                    return await self._page(send, 502, "The preview couldn't be reached", "The app didn't respond. Try reloading in a moment.")
                if attempt >= len(delays):
                    return await self._page(send, 503, *starting_page, refresh=3)
            await self.deps.sleep(delays[attempt])
            attempt += 1

    async def _relay(self, send, resp: UpstreamResponse, method: str, upstream_host: str, public_origin: str) -> None:
        s = self._settings()
        headers = rules.sanitize_response_headers(
            resp.headers,
            upstream_hostname=upstream_host,
            public_origin_value=public_origin,
            frame_ancestors=self._frame_ancestors(),
        )
        await send({
            "type": "http.response.start",
            "status": resp.status_code,
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1", "replace")) for k, v in headers],
        })
        if method == "HEAD":
            await send({"type": "http.response.body", "body": b""})
            return

        deadline = self.deps.now() + s.preview_response_max_seconds
        iterator = resp.iter_bytes().__aiter__()
        try:
            while True:
                remaining = deadline - self.deps.now()
                if remaining <= 0:
                    break  # a held-open response must not keep the Sprite billed forever
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except (StopAsyncIteration, asyncio.TimeoutError):
                    break
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        except UpstreamError:
            pass  # truncated by the upstream; the status line is already sent, so close cleanly
        except Exception as exc:  # noqa: BLE001 — the client went away mid-stream
            logger.debug("Preview relay stopped: %s", exc)
            return
        try:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception:  # noqa: BLE001
            pass

    # -- WebSocket ------------------------------------------------------------

    async def handle_ws(self, scope, receive, send, subdomain: str) -> None:
        s = self._settings()
        if not s.preview_enabled:
            return await self.reject(scope, receive, send)
        claims = self._authenticate(scope, subdomain)
        ref = await self._lookup(subdomain) if claims else None
        if claims is None or ref is None or ref.project_id != claims.get("pid"):
            return await self.reject(scope, receive, send)
        try:
            origin = await self.deps.get_upstream(ref.project_id)
        except self.deps.unavailable_exc:
            return await self.reject(scope, receive, send)

        await receive()  # websocket.connect
        url = rules.websocket_upstream_url(origin, scope.get("path", "/"), scope.get("query_string", b"").decode("latin-1"))
        headers = [(n, v) for n, v in rules.filter_request_headers(_header_list(scope))
                   if not n.lower().startswith("sec-websocket-") and n.lower() not in ("accept", "accept-encoding", "accept-language", "cache-control", "pragma")]
        headers += list(self.deps.auth_headers().items())
        try:
            upstream = await self.deps.connect_ws(url, headers, scope.get("subprotocols") or [])
        except Exception as exc:  # noqa: BLE001
            logger.info("Preview websocket upstream connect failed for %s: %s", ref.project_id, exc)
            await send({"type": "websocket.close", "code": 1011})
            return
        await send({"type": "websocket.accept", "subprotocol": getattr(upstream, "subprotocol", None)})
        self._last_ok[ref.project_id] = self.deps.now()
        await relay_websocket(
            receive, send, upstream,
            idle_seconds=s.preview_ws_idle_seconds, max_seconds=s.preview_ws_max_seconds, now=self.deps.now,
        )


async def _body_iter(receive) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        chunk = message.get("body", b"")
        if chunk:
            yield chunk
        if not message.get("more_body", False):
            return


async def relay_websocket(receive, send, upstream: UpstreamSocket, *, idle_seconds: float, max_seconds: float, now=time.monotonic) -> str:
    """Pumps frames both ways until: either side closes, the connection has been
    silent for `idle_seconds`, or it has lived `max_seconds`. Returns why it ended
    ("client" | "upstream" | "idle" | "max_lifetime" | "error"). The idle and
    lifetime limits are the billing guard: an open socket keeps a Sprite awake, and
    a forgotten tab must not be able to hold one open forever."""
    started = now()
    state = {"last": started}

    async def client_to_upstream() -> str:
        while True:
            message = await receive()
            if message["type"] == "websocket.disconnect":
                return "client"
            state["last"] = now()
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def upstream_to_client() -> str:
        while True:
            try:
                data = await upstream.recv()
            except UpstreamClosed:
                return "upstream"
            state["last"] = now()
            await send({"type": "websocket.send", **({"text": data} if isinstance(data, str) else {"bytes": data})})

    async def watchdog() -> str:
        tick = min(1.0, max(0.005, idle_seconds / 4))
        while True:
            await asyncio.sleep(tick)
            t = now()
            if t - started >= max_seconds:
                return "max_lifetime"
            if t - state["last"] >= idle_seconds:
                return "idle"

    tasks = [asyncio.ensure_future(c()) for c in (client_to_upstream, upstream_to_client, watchdog)]
    reason = "error"
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        first = next(iter(done))
        if first.exception() is None:
            reason = first.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            await upstream.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await send({"type": "websocket.close", "code": 1000 if reason in ("client", "upstream") else 1001})
        except Exception:  # noqa: BLE001 — the client may already be gone
            pass
    return reason


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------


_gateway_singleton: PreviewGateway | None = None


def get_gateway() -> PreviewGateway:
    """One gateway (and so one upstream HTTP client, one project cache, one
    "recently succeeded" map) for the whole process, shared by however many times
    Starlette instantiates the middleware."""
    global _gateway_singleton
    if _gateway_singleton is None:
        _gateway_singleton = PreviewGateway(default_deps())
    return _gateway_singleton


async def shutdown() -> None:
    """Closes the upstream HTTP client, if one was ever opened. Called from main.py's lifespan."""
    global _gateway_singleton
    if _gateway_singleton is not None:
        closer = getattr(_gateway_singleton.deps.open_stream, "aclose", None)
        if closer:
            await closer()
        _gateway_singleton = None


class PreviewHostMiddleware:
    """Outermost middleware: claims every request whose Host is under the preview
    domain. Everything else passes straight through, untouched."""

    def __init__(self, app, gateway: PreviewGateway | None = None):
        self.app = app
        self._gateway = gateway  # injectable for tests; production uses the shared singleton

    @property
    def gateway(self) -> PreviewGateway:
        return self._gateway if self._gateway is not None else get_gateway()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        from app.config import get_settings  # local: keeps the gateway itself importable with no settings

        base = get_settings().preview_base_domain
        if not base.strip():
            return await self.app(scope, receive, send)
        kind, subdomain = rules.classify_host(_header_map(scope).get("host"), base)
        if kind == "other":
            return await self.app(scope, receive, send)
        if kind == "preview_invalid":
            return await self.gateway.reject(scope, receive, send, 404)
        if scope["type"] == "http":
            return await self.gateway.handle_http(scope, receive, send, subdomain)
        return await self.gateway.handle_ws(scope, receive, send, subdomain)


# ---------------------------------------------------------------------------
# Real adapters (thin; the interesting logic above is what's tested)
# ---------------------------------------------------------------------------


class _HttpxResponse:
    def __init__(self, resp):
        self._resp = resp
        self.status_code = resp.status_code
        self.headers = list(resp.headers.multi_items())

    async def iter_bytes(self):
        import httpx

        try:
            # aiter_raw: bytes exactly as the app sent them, so content-encoding and
            # content-length stay truthful without us decoding and re-encoding.
            async for chunk in self._resp.aiter_raw():
                yield chunk
        except httpx.HTTPError as exc:
            raise UpstreamError(str(exc)) from exc


class HttpxUpstream:
    """No keep-alive pool: see the module docstring's billing section."""

    def __init__(self):
        self._client = None

    def _get(self):
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=0, max_connections=100),
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0),
            )
        return self._client

    @asynccontextmanager
    async def __call__(self, method, url, headers, body):
        import httpx

        client = self._get()
        try:
            request = client.build_request(method, url, headers=headers, content=body)
            resp = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise UpstreamError(str(exc)) from exc
        try:
            yield _HttpxResponse(resp)
        finally:
            await resp.aclose()

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class _WebsocketsSocket:
    def __init__(self, conn):
        self._conn = conn
        self.subprotocol = getattr(conn, "subprotocol", None)

    async def send(self, data):
        await self._conn.send(data)

    async def recv(self):
        try:
            return await self._conn.recv()
        except Exception as exc:  # noqa: BLE001 — websockets.ConnectionClosed and friends
            if "closed" in type(exc).__name__.lower() or "connectionclosed" in type(exc).__name__.lower():
                raise UpstreamClosed(str(exc)) from exc
            raise

    async def close(self, code: int = 1000):
        await self._conn.close(code)


async def _connect_websocket(url: str, headers: list[tuple[str, str]], subprotocols: list[str]) -> UpstreamSocket:
    import websockets

    common = {"subprotocols": subprotocols or None, "open_timeout": 15, "max_size": 16 * 1024 * 1024}
    try:
        conn = await websockets.connect(url, additional_headers=headers, **common)  # websockets >= 14
    except TypeError:
        conn = await websockets.connect(url, extra_headers=headers, **common)  # websockets <= 13
    return _WebsocketsSocket(conn)


def default_deps() -> GatewayDeps:
    from app.config import get_settings
    from app.repositories import projects as projects_repo
    from app.services import preview_runtime

    async def lookup(subdomain: str) -> ProjectRef | None:
        row = await projects_repo.get_by_preview_subdomain(subdomain)
        return ProjectRef(project_id=row["id"], user_id=row.get("user_id")) if row else None

    return GatewayDeps(
        settings=get_settings,
        lookup_project=lookup,
        get_upstream=preview_runtime.get_upstream_origin,
        auth_headers=preview_runtime.sprites_auth_headers,
        open_stream=HttpxUpstream(),
        connect_ws=_connect_websocket,
        unavailable_exc=preview_runtime.PreviewUnavailable,
    )
