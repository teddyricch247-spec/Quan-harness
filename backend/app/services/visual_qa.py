"""
§14.9 (Phase 5.8) — the agent's view of its own work. The impure half; the decisions live in visual_qa_rules.py.

Three things here:

  1. "Does this credential's model read images?" (`credential_supports_vision`) — one answer, used by the browser's
     screenshots AND by Phase 6's picture attachments. Fails closed.
  2. `preview_status` / `preview_rebuild` — whether the live preview is up and matches the files, and a request for the
     same deterministic pipeline the Deploy button runs (deploy_pipeline.start_deploy). No credentials of its own, no push.
  3. The browser itself: Playwright's headless Chromium, in this backend process, pointed at the project's own Sprite
     URL (preview_runtime.get_upstream_origin) — NEVER at the public preview proxy built for people.

Text-only models
----------------
A model that isn't confirmed to read images still gets the browser. Navigate, click, type and console logs never needed
vision; only the screenshot did. For such a model `browser_screenshot` returns a TEXT outline of the page instead of a
picture (visual_qa_text.py): the visible text plus every clickable/typeable element with a selector. The vision check
therefore no longer switches the browser off (see `availability_for`); it only decides what `browser_screenshot` returns.

Security shape of the browser — read before changing anything
-------------------------------------------------------------
The previewed app is code the agent wrote, running in a browser on the backend host, and the browser sends the Sprites
token to the Sprite it is looking at. So:

  * The NETWORK is the wall, not the page. Each context gets a proxy that points at a dead address plus a bypass list that
    names only the allowed hosts (visual_qa_rules.chromium_proxy_bypass) and `<-loopback>`. Anything not on that list fails
    to connect — including every hop of a redirect, which Playwright route handlers are never called for. Do not
    "simplify" this back to request filtering: a single 302 from the previewed app would reach any host.
  * The Sprites token is attached only by the route handler, only to requests whose origin is EXACTLY the project's Sprite
    origin — never as a context-wide extra header. Chromium strips Authorization on a cross-origin redirect, and the network
    wall stops the hop anyway; two layers, neither of which should be the only one.
  * A tool parameter is never a URL or a credential: `browser_navigate` takes a path (normalize_path).
  * Service workers are blocked, downloads are refused, no permissions are granted, certificate errors are not ignored.
  * The text outline is read-only DOM inspection of the same page the screenshot would have shown; it opens no new network
    path and is bounded and cleaned before the model sees it.

Nothing here has run against a real Sprite or a real Chromium: this environment has neither. docs/PHASE5_6_5_7_5_8_NOTES.md
lists what that leaves unverified; the one question that matters most — whether a Sprite's edge forwards `Authorization`
to the app inside it — can only be answered by deploying a page that echoes its request headers
(docs/BROWSER_SETUP.md has the steps).
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import logging
import time
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit

from app.config import get_settings
from app.repositories import deploy_runs as deploy_runs_repo
from app.services import deploy_pipeline, llm_client, preview_runtime, visual_qa_text, workspace_fingerprint
from app.services import visual_qa_rules as rules

logger = logging.getLogger(__name__)


@dataclass
class QaResult:
    ok: bool
    content: str = ""
    error: str = ""
    image: dict | None = None  # {"data_uri", "width", "height", "bytes", "path"} — pixels go to agent_loop's ScreenshotStore


# ---------------------------------------------------------------------------
# 1. Vision capability (shared with Phase 6's picture attachments)
# ---------------------------------------------------------------------------


def model_string(credential: llm_client.ResolvedCredential) -> str:
    """The litellm model string ("openrouter/vendor/model") — what litellm is asked about, what AGENT_VISION_MODELS entries
    are written in, and what person-facing messages name."""
    return llm_client._litellm_model_string(credential)  # noqa: SLF001 — one definition of the string


def _configured_vision_models() -> set[str]:
    return {m.strip().lower() for m in get_settings().agent_vision_models.split(",") if m.strip()}


def credential_supports_vision(credential: llm_client.ResolvedCredential) -> bool:
    """CONFIRMED to accept images: litellm's capability table says so, or the operator listed the model's litellm string in
    AGENT_VISION_MODELS. Unknown is "no": a provider that rejects one image rejects every later call that still carries it,
    so the cost of a false "no" (a note instead of a picture, and a message saying how to fix it) is far below the cost of a
    false "yes" (a broken session)."""
    model = model_string(credential)
    if model.lower() in _configured_vision_models():
        return True
    try:
        import litellm

        return bool(litellm.supports_vision(model=model))
    except Exception:  # noqa: BLE001 — unknown model / litellm absent / lookup raised: not confirmed
        return False


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

_RUNTIME_BACKOFF_SECONDS = 300.0
_runtime_blocked_until = 0.0
_runtime_last_error = ""


def _playwright_installed() -> bool:
    try:
        return importlib.util.find_spec("playwright.async_api") is not None
    except (ImportError, ValueError):
        return False


def runtime_available() -> bool:
    """Playwright importable, and Chromium hasn't failed to start in the last few minutes (the feature switches itself off
    for a while rather than failing every tool call and every turn)."""
    if time.monotonic() < _runtime_blocked_until:
        return False
    return _playwright_installed()


def _mark_runtime_failure(exc: Exception) -> None:
    global _runtime_blocked_until, _runtime_last_error
    _runtime_blocked_until = time.monotonic() + _RUNTIME_BACKOFF_SECONDS
    _runtime_last_error = " ".join(str(exc).split())[:300]
    logger.error("The agent's browser could not start; off for %ss: %s", int(_RUNTIME_BACKOFF_SECONDS), _runtime_last_error)


def availability_for(credential: llm_client.ResolvedCredential) -> rules.BrowserAvailability:
    """May the browser tools be offered for this credential right now?

    The vision check is deliberately NOT passed to the decision (`vision_confirmed=True`): a model that can't read images
    still gets navigate/click/type/console, and its `browser_screenshot` returns a text outline instead (see the module
    docstring). `credential_supports_vision` is consulted later, per screenshot, in `_run_browser_tool`.

    Playwright simply not being installed (a dev machine, a lean deploy) is not an alarm: the model is told it has no
    browser, but the person isn't shown an error on every session. A Chromium that is installed but failed to start is
    still shown."""
    result = rules.decide_browser_availability(
        server_enabled=get_settings().agent_browser_enabled,
        runtime_available=runtime_available(),
        vision_confirmed=True,
        model_label=model_string(credential),
    )
    if result.code == "runtime_missing" and not _playwright_installed():
        result = replace(result, surface_error=False)
    return result


async def _model_reads_images(project: dict) -> bool:
    """Whether the project's CURRENT credential is confirmed to read images (decides screenshot vs text outline)."""
    try:
        credential = await llm_client.resolve_credential(project)
    except Exception:  # noqa: BLE001 — no credential / vault hiccup: the safe answer is "no pictures"
        return False
    return credential_supports_vision(credential)


# ---------------------------------------------------------------------------
# 2. preview_status / preview_rebuild
# ---------------------------------------------------------------------------

REBUILD_WAIT_SECONDS = 360
_REBUILD_POLL_SECONDS = 3


async def run_preview_status(project: dict) -> QaResult:
    project_id = project["id"]
    latest = await deploy_runs_repo.get_latest_for_project(project_id)
    if latest is None:
        return QaResult(True, "Nothing has been deployed for this project yet, so there is no preview. Call preview_rebuild to build and start it.")
    if deploy_pipeline.is_running(project_id) or latest.get("status") == "running":
        return QaResult(True, "A build/deploy is in progress right now. Wait a bit and call preview_status again.")
    if latest.get("status") != "success":
        phase = latest.get("phase") or "unknown"
        diagnosis = (latest.get("diagnosis_text") or "").strip()
        detail = f"\nDiagnosis: {diagnosis[:600]}" if diagnosis else ""
        return QaResult(True, f"The most recent deploy FAILED (at: {phase}), so there is no working preview.{detail}\nFix the cause, then call preview_rebuild.")

    recorded = latest.get("workspace_fingerprint")
    current = await workspace_fingerprint.compute(project_id)
    if recorded and current:
        if recorded == current:
            verdict = "UP TO DATE: the preview was built from exactly the files that are in the workspace now."
        else:
            verdict = "STALE: the files in the workspace have changed since the preview was built. Call preview_rebuild before looking at it."
    elif not current:
        verdict = "UNKNOWN whether it matches the workspace (the workspace's content couldn't be hashed just now)."
    else:
        verdict = "UNKNOWN whether it matches the workspace (this deploy didn't record what it was built from). Call preview_rebuild if you've changed anything since."
    return QaResult(True, f"The last deploy succeeded. {verdict}")


async def run_preview_rebuild(project: dict, user_id: str) -> QaResult:
    project_id = project["id"]
    try:
        started = await deploy_pipeline.start_deploy(project_id, user_id)
    except deploy_pipeline.DeployNeedsConfirmation:
        return QaResult(False, error="This imported project's build targets haven't been confirmed yet. Ask the person to open Deploy and confirm them; you can't do that for them.")
    except Exception as exc:  # noqa: BLE001 — a tool result, never a crash of the turn
        logger.exception("preview_rebuild could not start a deploy for project %s", project_id)
        return QaResult(False, error=f"The rebuild could not be started: {' '.join(str(exc).split())[:300]}")
    # `started` False means a deploy is already running — the same wait applies.
    deadline = time.monotonic() + REBUILD_WAIT_SECONDS
    while deploy_pipeline.is_running(project_id) and time.monotonic() < deadline:
        await asyncio.sleep(_REBUILD_POLL_SECONDS)
    if deploy_pipeline.is_running(project_id):
        return QaResult(False, error="The rebuild is still running after several minutes. Call preview_status later instead of waiting on it.")
    latest = await deploy_runs_repo.get_latest_for_project(project_id)
    if latest and latest.get("status") == "success":
        note = "" if started else " (a deploy that was already in progress finished; it may not include your latest edits — call preview_status)"
        return QaResult(True, f"The preview was rebuilt and is running.{note}")
    phase = (latest or {}).get("phase") or "unknown"
    diagnosis = ((latest or {}).get("diagnosis_text") or "").strip()
    return QaResult(False, error=f"The rebuild FAILED (at: {phase}). {diagnosis[:600] if diagnosis else 'See the deploy output.'}")


# ---------------------------------------------------------------------------
# 3. The browser
# ---------------------------------------------------------------------------

VIEWPORT = {"width": 1280, "height": 800}
MAX_LIVE_PAGES = 3  # the old fixed ceiling, kept for anything that imports it; the live one is AGENT_BROWSER_MAX_PAGES
IDLE_CLOSE_SECONDS = 600.0
TOOL_TIMEOUT_SECONDS = 45.0
NAVIGATION_TIMEOUT_MS = 20_000
ACTION_TIMEOUT_MS = 5_000
CONSOLE_BUFFER_MAX = 200

_playwright = None
_browser = None
_start_lock = asyncio.Lock()


def _max_live_pages() -> int:
    """How many pages stay open at once (AGENT_BROWSER_MAX_PAGES); the least recently used is closed to make room. Each
    live page costs Chromium memory, so a small instance should keep this at 1 or 2."""
    return max(1, int(get_settings().agent_browser_max_pages))


@dataclass
class _LivePage:
    context: object
    page: object
    origin: str
    console: list[dict] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_pages: dict[str, _LivePage] = {}
_warned_rejected_hosts = False


def allowed_host_patterns() -> list[str]:
    """The default font/script CDNs plus the operator's AGENT_BROWSER_ALLOWED_HOSTS — validated. The project's own Sprite
    host is added per page."""
    global _warned_rejected_hosts
    s = get_settings()
    forbidden = [s.sprites_url_host_suffix, s.preview_base_domain]
    for url in (s.backend_public_url, s.frontend_url):
        host = urlsplit(url).hostname
        if host:
            forbidden.append(host)
    accepted, rejected = rules.parse_allowed_hosts_setting(s.agent_browser_allowed_hosts, forbidden)
    if rejected and not _warned_rejected_hosts:
        _warned_rejected_hosts = True
        for entry, why in rejected:
            logger.warning("AGENT_BROWSER_ALLOWED_HOSTS: ignoring %r — %s", entry, why)
    return list(rules.DEFAULT_ALLOWED_CDN_HOSTS) + [h for h in accepted if h not in rules.DEFAULT_ALLOWED_CDN_HOSTS]


async def _get_browser():
    global _playwright, _browser
    async with _start_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        from playwright.async_api import async_playwright  # lazy: the package is optional

        try:
            if _playwright is None:
                _playwright = await async_playwright().start()
            # "per-context": Chromium only honours a per-context proxy if the browser itself was started with this
            # placeholder. Each context supplies the real (dead) proxy and the bypass list.
            _browser = await _playwright.chromium.launch(
                headless=True, proxy={"server": "per-context"}, args=["--disable-dev-shm-usage", "--disable-gpu"]
            )
        except Exception as exc:  # noqa: BLE001 — Chromium missing / missing system libraries / out of memory
            _mark_runtime_failure(exc)
            raise _RuntimeUnavailable(str(exc)) from exc
        return _browser


class _RuntimeUnavailable(Exception):
    pass


async def _close_live(session_id: str) -> None:
    live = _pages.pop(session_id, None)
    if live is None:
        return
    try:
        await live.context.close()
    except Exception:  # noqa: BLE001
        logger.debug("closing a browser context failed", exc_info=True)


async def close_session(session_id: str) -> None:
    await _close_live(session_id)


async def _reap(keep: str) -> None:
    now = time.monotonic()
    for sid, live in list(_pages.items()):
        if sid != keep and now - live.last_used > IDLE_CLOSE_SECONDS:
            await _close_live(sid)
    while len(_pages) >= _max_live_pages():
        oldest = min((sid for sid in _pages if sid != keep), key=lambda sid: _pages[sid].last_used, default=None)
        if oldest is None:
            break
        await _close_live(oldest)


def _blocked_label(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or '?'}{parts.path[:80]}"


async def _open_page(session_id: str, project_id: str) -> _LivePage:
    try:
        origin = await preview_runtime.get_upstream_origin(project_id)
    except preview_runtime.PreviewUnavailable as exc:
        raise _NoPreview(str(exc)) from exc
    live = _pages.get(session_id)
    if live is not None and live.origin == origin:
        return live
    await _close_live(session_id)  # the Sprite's origin changed (or first use): start clean
    await _reap(session_id)

    browser = await _get_browser()
    patterns = [urlsplit(origin).hostname or ""] + allowed_host_patterns()
    context = await browser.new_context(
        viewport=VIEWPORT,
        proxy={"server": "http://127.0.0.1:1", "bypass": rules.chromium_proxy_bypass(patterns)},
        service_workers="block",
        accept_downloads=False,
        ignore_https_errors=False,
        permissions=[],
        locale="en-US",
    )
    page = await context.new_page()
    console: list[dict] = []

    def add(kind: str, text: str) -> None:
        console.append({"type": kind, "text": text})
        if len(console) > CONSOLE_BUFFER_MAX:
            del console[: len(console) - CONSOLE_BUFFER_MAX]

    page.on("console", lambda msg: add(msg.type, msg.text))
    page.on("pageerror", lambda exc: add("pageerror", str(exc)))
    page.on("requestfailed", lambda req: add("failed", f"{req.method} {_blocked_label(req.url)} — {req.failure or 'failed'}"))

    async def handler(route, request) -> None:
        url = request.url
        if not rules.request_allowed(url, origin, patterns):
            add("blocked", f"{_blocked_label(url)} — not allowed from the agent's browser")
            await route.abort("blockedbyclient")
            return
        if rules.same_origin(url, origin):
            # The ONE place the Sprites token is attached, and only to this project's own Sprite origin.
            await route.continue_(headers={**request.headers, **preview_runtime.sprites_auth_headers()})
        else:
            await route.continue_()

    await context.route("**/*", handler)
    live = _LivePage(context=context, page=page, origin=origin, console=console)
    live.console = console
    _pages[session_id] = live
    return live


class _NoPreview(Exception):
    pass


def _path_of(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _short_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300] or type(exc).__name__


async def run_browser_tool(session_id: str, project: dict, name: str, arguments: dict) -> QaResult:
    """Never raises: every failure is a tool result the model can read. Serialised per session (one page, one sequence)."""
    try:
        return await asyncio.wait_for(_run_browser_tool(session_id, project, name, arguments), TOOL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return QaResult(False, error=f"{name} took longer than {int(TOOL_TIMEOUT_SECONDS)}s and was abandoned. The page may be hung; try browser_navigate again.")
    except _RuntimeUnavailable:
        return QaResult(False, error="The browser could not start on this server, so it can't be used for the next few minutes.")
    except _NoPreview as exc:
        return QaResult(False, error=f"{exc} Call preview_status, and preview_rebuild if nothing is deployed.")
    except ValueError as exc:  # a bad parameter (rules.normalize_path / clean_selector / clean_typed_text)
        return QaResult(False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("browser tool %s failed for session %s", name, session_id)
        return QaResult(False, error=f"{name} failed: {_short_error(exc)}")


async def _text_outline(page) -> QaResult:
    """`browser_screenshot` for a model that can't read images: the page as text (visible text + clickable elements)."""
    data = await page.evaluate(visual_qa_text.OUTLINE_JS)
    if not isinstance(data, dict):
        data = {}
    title = " ".join((await page.title()).split())[:200]
    return QaResult(
        True,
        visual_qa_text.format_text_outline(_path_of(page.url), title, data.get("text"), data.get("elements")),
    )


async def _run_browser_tool(session_id: str, project: dict, name: str, arguments: dict) -> QaResult:
    # Validate parameters BEFORE touching the browser: a bad call costs nothing and never starts Chromium.
    if name == "browser_navigate":
        path = rules.normalize_path(arguments.get("path"))
    elif name == "browser_click":
        selector = rules.clean_selector(arguments.get("selector"))
    elif name == "browser_type":
        selector = rules.clean_selector(arguments.get("selector"))
        text = rules.clean_typed_text(arguments.get("text"))
    elif name not in ("browser_screenshot", "browser_get_console_logs"):
        return QaResult(False, error=f"Unknown browser tool: {name}")

    if name == "browser_navigate":
        latest = await deploy_runs_repo.get_latest_for_project(project["id"])
        if latest is None or latest.get("status") != "success":
            return QaResult(False, error="Nothing is successfully deployed for this project, so there is nothing to look at. Call preview_status, then preview_rebuild.")

    live = await _open_page(session_id, project["id"])
    async with live.lock:
        live.last_used = time.monotonic()
        page = live.page

        if name == "browser_navigate":
            live.console.clear()  # "since the last navigation"
            response = await page.goto(live.origin + path, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:  # noqa: BLE001 — a page that never goes idle (polling, websockets) is normal
                pass
            if not rules.request_allowed(page.url, live.origin, allowed_host_patterns()):
                await page.goto("about:blank")
                return QaResult(False, error="The page redirected somewhere the agent's browser may not go, so it was stopped. Only this project's own preview can be viewed.")
            status = response.status if response is not None else None
            title = " ".join((await page.title()).split())[:200]
            hint = " The preview may be down or still starting — call preview_status." if status in (502, 503, 504) else ""
            errors = sum(1 for e in live.console if e["type"] in ("error", "pageerror"))
            return QaResult(
                True,
                f"Navigated to {path}. Now at {_path_of(page.url)} — HTTP {status}. Title: {title or '(none)'}. "
                f"{errors} console error(s) so far.{hint}",
            )

        if name == "browser_click":
            await page.click(selector, timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(300)
            return QaResult(True, f"Clicked {selector!r}. Now at {_path_of(page.url)}.")

        if name == "browser_type":
            await page.type(selector, text, timeout=ACTION_TIMEOUT_MS)
            return QaResult(True, f"Typed {len(text)} character(s) into {selector!r}.")

        if name == "browser_get_console_logs":
            return QaResult(True, rules.format_console(list(live.console)))

        # browser_screenshot
        if page.url in ("", "about:blank"):
            return QaResult(False, error="The browser hasn't opened a page yet. Call browser_navigate first.")
        if not await _model_reads_images(project):
            return await _text_outline(page)  # no picture for a model that can't read one: the page as text instead
        png = await page.screenshot(type="png", full_page=False, timeout=10_000)
        mime, raw = "image/png", png
        if len(raw) > rules.MAX_SCREENSHOT_BYTES:
            raw = await page.screenshot(type="jpeg", quality=70, full_page=False, timeout=10_000)
            mime = "image/jpeg"
        if len(raw) > rules.MAX_SCREENSHOT_BYTES:
            return QaResult(False, error="The screenshot is too large to send. Try a simpler page state or a different path.")
        path_now = _path_of(page.url)
        return QaResult(
            True,
            f"Screenshot captured of {path_now} ({VIEWPORT['width']}x{VIEWPORT['height']}). The image is attached to the next message.",
            image={
                "data_uri": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                "width": VIEWPORT["width"],
                "height": VIEWPORT["height"],
                "bytes": len(raw),
                "path": path_now,
            },
        )
