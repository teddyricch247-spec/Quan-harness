"""
§14.9 (Phase 5.8) — the PURE half of the agent's browser: who may use it, what it may be pointed at, and what the
model is shown. No I/O, no Playwright, no settings access — `visual_qa.py` gathers the facts and acts; this decides.
Kept pure so the decisions that matter for safety are unit-tested without a browser.

Why the allow-list lives here and is checked in more than one place
-------------------------------------------------------------------
The previewed app is code the agent (or a person) wrote, and it runs in the agent's browser on the backend host. Anything
that code can make the browser request, it can use. So the browser may reach only the project's own preview (and a short
list of font/script CDNs, plus whatever the operator adds). Request filtering in the page (Playwright route handlers) is
NOT enough on its own: route handlers are not called for the hops of a redirect, so one `302` from the previewed app to
any host would sail through. The wall that actually holds is at the network layer — Chromium is given a dead proxy and a
bypass list naming only the allowed hosts, so everything else fails to connect, redirects included
(`chromium_proxy_bypass`). The functions below build that list and are also used by the route handler as a second layer.
"""
from __future__ import annotations

import ipaddress
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# Availability: may the browser tools be offered / used right now?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrowserAvailability:
    available: bool
    code: str  # ok | server_off | runtime_missing | no_vision | vision_rejected
    reason: str  # for the PERSON: what is wrong and how to fix it. "" when available.
    model_notice: str  # for the MODEL: what it can't do this session. "" when available.
    surface_error: bool  # show `reason` to the person as a visible notice (not for a deliberately-off server)


_OK = BrowserAvailability(True, "ok", "", "", False)


def decide_browser_availability(
    *, server_enabled: bool, runtime_available: bool, vision_confirmed: bool, model_label: str
) -> BrowserAvailability:
    """Order matters: the operator's switch first (a server that has the browser off is not an error to anyone), then
    whether Chromium can run at all, then whether the project's model is CONFIRMED to read images (§14.9: 'confirms the
    session's active LLM credential supports vision input before offering these tools, and surfaces a clear error if a
    BYOK model doesn't')."""
    if not server_enabled:
        return BrowserAvailability(
            False,
            "server_off",
            "The agent's browser is switched off on this server.",
            "You have no browser tools this session (the operator has not enabled them). You cannot look at the running "
            "app, so do not claim you checked it visually; say you could not.",
            False,
        )
    if not runtime_available:
        return BrowserAvailability(
            False,
            "runtime_missing",
            "The agent's browser can't start on this server (Chromium isn't installed or couldn't launch), so it can't "
            "check its work visually. See docs/YOUR_SETUP_CHECKLIST.md, section 3c.",
            "You have no browser tools this session (the browser could not start on the server). You cannot look at the "
            "running app, so do not claim you checked it visually; say you could not.",
            True,
        )
    if not vision_confirmed:
        return BrowserAvailability(
            False,
            "no_vision",
            f"The agent can't check its work visually: this project's model ({model_label}) isn't confirmed to read "
            "images. Switch to a model that accepts images, or ask the server's operator to list this one in "
            "AGENT_VISION_MODELS if it does.",
            f"You have no browser tools this session: the project's model ({model_label}) is not confirmed to read images, "
            "and screenshots are the point of them. You cannot look at the running app, so do not claim you checked it "
            "visually; say you could not.",
            True,
        )
    return _OK


def vision_rejected_availability(model_label: str) -> BrowserAvailability:
    """The provider refused a request that carried an image (a model that looked image-capable but isn't, on this
    endpoint). Browser tools stay off for the rest of the session so the rejected content is never sent again."""
    return BrowserAvailability(
        False,
        "vision_rejected",
        f"The model provider rejected an image sent to {model_label}, so the agent's browser is off for the rest of this "
        "session. Pick a model that reads images, or ask the operator to correct AGENT_VISION_MODELS.",
        f"You have no browser tools for the rest of this session: the provider rejected an image sent to {model_label}. "
        "You cannot look at the running app, so do not claim you checked it visually; say you could not.",
        True,
    )


def format_visual_qa_notice(availability: BrowserAvailability) -> str | None:
    """The VISUAL_QA dynamic prompt section: nothing when the browser works (the static VISUAL_VERIFICATION block already
    says what to do); when it doesn't, a plain statement that overrides that block, so the model never promises a check it
    can't make."""
    if availability.available:
        return None
    return availability.model_notice


# ---------------------------------------------------------------------------
# What a tool parameter may be
# ---------------------------------------------------------------------------

MAX_PATH_CHARS = 2000
MAX_SELECTOR_CHARS = 500
MAX_TYPED_TEXT_CHARS = 2000

_CONTROL = re.compile(r"[\x00-\x1f\x7f\\]")


def normalize_path(path: object) -> str:
    """`browser_navigate`'s only parameter is a PATH on the project's own preview — never a URL (a tool parameter that
    can be a URL is a way to point the browser at anything). Accepts "/", "/about", "/search?q=x#top". Raises ValueError
    with a sentence meant for the model."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path is required, e.g. \"/\" or \"/dashboard\".")
    path = path.strip()
    if len(path) > MAX_PATH_CHARS:
        raise ValueError(f"path is too long (max {MAX_PATH_CHARS} characters).")
    if _CONTROL.search(path):
        raise ValueError("path may not contain control characters or backslashes.")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError(
            "path must be a path on this project's own preview, starting with a single \"/\" (e.g. \"/dashboard\"). "
            "Full URLs and other sites are not reachable."
        )
    parts = urlsplit(path)
    if parts.scheme or parts.netloc:
        raise ValueError("path must be a path, not a URL.")
    return path


def clean_selector(selector: object) -> str:
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("selector is required (a CSS selector, or a text=… / role=… selector).")
    selector = selector.strip()
    if len(selector) > MAX_SELECTOR_CHARS:
        raise ValueError(f"selector is too long (max {MAX_SELECTOR_CHARS} characters).")
    return selector


def clean_typed_text(text: object) -> str:
    if not isinstance(text, str):
        raise ValueError("text is required.")
    if len(text) > MAX_TYPED_TEXT_CHARS:
        raise ValueError(f"text is too long (max {MAX_TYPED_TEXT_CHARS} characters).")
    return text


# ---------------------------------------------------------------------------
# The allow-list
# ---------------------------------------------------------------------------

# Fonts / script CDNs that ordinary front-end code loads from. A page that can't load them renders wrongly, which is the
# opposite of what the browser is for; none of them serves API data the agent's code could be tricked into sending
# anything to that it could not send to any other website.
DEFAULT_ALLOWED_CDN_HOSTS: tuple[str, ...] = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "code.jquery.com",
)

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
        return True
    except ValueError:
        return False


def parse_allowed_hosts_setting(raw: str, forbidden_suffixes: Iterable[str] = ()) -> tuple[list[str], list[tuple[str, str]]]:
    """The operator's AGENT_BROWSER_ALLOWED_HOSTS: comma-separated exact hosts (`api.example.com`) or one-level-down
    wildcards (`*.supabase.co`). Returns (accepted, [(entry, why it was rejected)]). Rejected, never silently widened:
    IP addresses and `localhost` (the backend's own network), single-label names, bare wildcards and wildcards over a
    one-label base (`*.com`), ports/paths/schemes, and anything at or under a forbidden suffix (the Sprite domain, the
    preview domain, this deployment's own hosts) — the browser must never be pointed at the things it is wall-protected
    from."""
    forbidden = [s.strip().lower().lstrip(".") for s in forbidden_suffixes if s and s.strip()]
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []
    for entry in (raw or "").split(","):
        item = entry.strip().lower()
        if not item:
            continue
        host = item[2:] if item.startswith("*.") else item
        why = None
        if "*" in host or "/" in item or ":" in item.replace("*.", "", 1) or "@" in item or " " in item:
            why = "must be a bare hostname or *.domain — no scheme, port, path or other wildcard"
        elif _is_ip(host) or host == "localhost" or host.endswith(".localhost"):
            why = "IP addresses and localhost are never allowed"
        elif "." not in host:
            why = "a single-label name is too broad / internal"
        elif item.startswith("*.") and host.count(".") < 1:
            why = "wildcard base is too broad"
        elif not all(_LABEL.match(label) for label in host.split(".")):
            why = "not a valid hostname"
        else:
            for suffix in forbidden:
                if host == suffix or host.endswith("." + suffix) or (item.startswith("*.") and suffix.endswith("." + host)):
                    why = "that is one of this deployment's own domains"
                    break
        if why:
            rejected.append((entry.strip(), why))
        elif item not in accepted:
            accepted.append(item)
    return accepted, rejected


def host_matches(host: str, patterns: Iterable[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    for pattern in patterns:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def chromium_proxy_bypass(hosts: Iterable[str]) -> str:
    """The `bypass` string for the browser context's proxy. The proxy itself is a dead address, so a request goes out
    only if its host is in this list; `<-loopback>` removes Chromium's built-in exemption that would otherwise let the
    page reach 127.0.0.1 / localhost (this server's own network) directly. Applies to every hop of a redirect."""
    entries = []
    for host in hosts:
        host = host.strip().lower()
        if host and host not in entries:
            entries.append(host)
    entries.append("<-loopback>")
    return ",".join(entries)


def origin_parts(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) for an http(s) URL, else None."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return parts.scheme, parts.hostname.lower(), port
    except ValueError:
        return None


def same_origin(url: str, origin: str) -> bool:
    a, b = origin_parts(url), origin_parts(origin)
    return a is not None and a == b


def request_allowed(url: str, preview_origin: str, allowed_hosts: Iterable[str]) -> bool:
    """Second layer (the route handler's): the project's own preview origin, or an allowed host over http(s); the page's
    own `data:` / `blob:` / `about:blank` documents. Everything else — `file:`, `ftp:`, other hosts — is refused."""
    if url.startswith(("data:", "blob:", "about:blank")):
        return True
    parts = origin_parts(url)
    if parts is None:
        return False
    if same_origin(url, preview_origin):
        return True
    return host_matches(parts[1], allowed_hosts)


# ---------------------------------------------------------------------------
# What the model is shown
# ---------------------------------------------------------------------------

MAX_CONSOLE_ENTRIES = 60
MAX_CONSOLE_CHARS = 6000
MAX_CONSOLE_LINE_CHARS = 500


def format_console(entries: list[dict]) -> str:
    """`entries`: [{"type": "error"|"warning"|"log"|"pageerror"|"blocked"|…, "text": str}] since the last navigation.
    Bounded; newest last; the oldest are dropped first, and the model is told how many."""
    if not entries:
        return "No console output since the last navigation."
    shown = entries[-MAX_CONSOLE_ENTRIES:]
    lines = []
    for e in shown:
        text = " ".join(str(e.get("text", "")).split())
        if len(text) > MAX_CONSOLE_LINE_CHARS:
            text = text[: MAX_CONSOLE_LINE_CHARS - 1] + "…"
        lines.append(f"[{e.get('type', 'log')}] {text}")
    out = "\n".join(lines)
    if len(out) > MAX_CONSOLE_CHARS:
        out = out[-MAX_CONSOLE_CHARS:]
        out = "…(earlier lines cut)\n" + out[out.find("\n") + 1 :]
    dropped = len(entries) - len(shown)
    if dropped > 0:
        out = f"({dropped} earlier entries omitted)\n" + out
    return out


# ---------------------------------------------------------------------------
# Screenshot memory
# ---------------------------------------------------------------------------

MAX_SCREENSHOTS_IN_CONTEXT = 3  # the few most recent per session are shown to the model; older ones become a note
MAX_SESSIONS_HELD = 32  # bound on memory: least-recently-used sessions' pictures are dropped first
MAX_SCREENSHOT_BYTES = 1_000_000


class ScreenshotStore:
    """Pixels live here, in memory, keyed by session then by the browser_screenshot tool_call event id — never in
    session_events (a row per image would bloat the transcript and be re-sent to every client). Gone after a restart; the
    transcript still says what was captured."""

    def __init__(self) -> None:
        self._by_session: "OrderedDict[str, OrderedDict[int, str]]" = OrderedDict()

    def put(self, session_id: str, event_id: int, data_uri: str) -> None:
        shots = self._by_session.setdefault(session_id, OrderedDict())
        shots[event_id] = data_uri
        shots.move_to_end(event_id)
        while len(shots) > MAX_SCREENSHOTS_IN_CONTEXT:
            shots.popitem(last=False)
        self._by_session.move_to_end(session_id)
        while len(self._by_session) > MAX_SESSIONS_HELD:
            self._by_session.popitem(last=False)

    def for_session(self, session_id: str) -> dict[int, str]:
        return dict(self._by_session.get(session_id, {}))

    def drop_session(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)
