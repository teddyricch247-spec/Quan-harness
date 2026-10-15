"""
§23.7: the pure rules behind the Live Preview proxy — every decision the proxy
makes about *what* to forward, rewrite, strip or refuse, with no I/O, no
app.config, no httpx/starlette import (same isolation rule as guard_rules.py and
deploy_detection.py, so all of it is unit-testable directly). The I/O shell that
applies these is app/services/preview_proxy.py.

The proxy sits between the person's iframe and a Sprite's own HTTPS URL, and the
thing behind that URL is *the user's own app code* — untrusted from the
harness's point of view. Most of what's here exists because of that:

  * Host classification is tri-state. `*.preview.<domain>` DNS points at the same
    backend that serves the API, so a host under the preview domain must be
    handled by the proxy and ONLY the proxy. A boolean "is this a preview host"
    would let a malformed preview hostname fall through to the API's own routes.
  * The client's `Authorization` header is never forwarded: it is replaced with
    the Sprites token the proxy itself holds (a Sprite URL in its default
    `sprite` auth mode is bearer-gated). A side effect, stated plainly rather
    than hidden: a same-origin request from the previewed app that itself relies
    on an Authorization header can't work through this proxy. See
    preview_limitations.py's guidance entry for it.
  * `Set-Cookie: Domain=` from the app is stripped so an app can't plant a
    cookie for the whole `preview.<domain>` parent (cookie tossing onto sibling
    projects' previews).
  * The harness's own cookie name is stripped from what the app receives, and
    from what the app tries to set.
  * `X-Frame-Options` and any `frame-ancestors` from the app are removed and
    replaced with the harness's own — the preview may be embedded by the
    harness frontend and by nothing else (§23.1: no shareable links).
  * `Location` headers pointing at the Sprite's internal hostname are rewritten
    to the public preview origin, so the internal URL (never to be exposed —
    §23.7) doesn't leak through an ordinary redirect.
"""
import re
import urllib.parse
from typing import Iterable

COOKIE_NAME = "qh_preview"
RESERVED_PREFIX = "/__qh/"
ENTER_PATH = "/__qh/enter"

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,40}[a-z0-9])?$")

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Headers a client could send to make the app believe something false about
# where a request came from (or that carry credentials that are not the app's).
_DROP_FROM_REQUEST = frozenset(
    {
        "host",
        "authorization",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-for",
        "x-forwarded-port",
        "forwarded",
        "x-real-ip",
    }
)

RETRYABLE_STATUSES = frozenset({502, 503, 504})


# ---------------------------------------------------------------------------
# Subdomains and hosts
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug


def new_subdomain(project_name: str, random_hex: str) -> str:
    """A DNS-label-safe, human-recognisable, collision-resistant subdomain.
    `random_hex` is passed in (not generated here) so this stays pure and
    deterministic under test. Result is always <= 33 chars, and always matches
    the projects_preview_subdomain_format CHECK in 0011_preview.sql."""
    slug = slugify(project_name)[:24].strip("-")
    suffix = re.sub(r"[^a-f0-9]", "", random_hex.lower())
    if slug:
        return f"{slug}-{suffix[:8]}"
    return f"p-{suffix[:12]}"


def is_valid_subdomain(value: str | None) -> bool:
    return bool(value) and bool(_SUBDOMAIN_RE.match(value))


def classify_host(host_header: str | None, base_domain: str) -> tuple[str, str | None]:
    """Returns one of:
        ("other", None)            — not under the preview domain; normal app handling.
        ("preview", "<label>")     — a well-formed `<label>.<base_domain>`.
        ("preview_invalid", None)  — under the preview domain but not a valid single
                                      label (`a.b.<base>`, `-x.<base>`, the bare base, ...).
                                      The proxy answers 404 itself; this must never be
                                      handed to the API's routes.
    """
    base = (base_domain or "").strip().strip(".").lower()
    if not base or not host_header:
        return ("other", None)
    host = host_header.strip().lower()
    if host.startswith("["):  # bracketed IPv6 literal — never a preview host
        return ("other", None)
    host = host.split(":", 1)[0].rstrip(".")
    if host == base:
        return ("preview_invalid", None)
    if not host.endswith("." + base):
        return ("other", None)
    label = host[: -(len(base) + 1)]
    if _SUBDOMAIN_RE.match(label):
        return ("preview", label)
    return ("preview_invalid", None)


def public_origin(subdomain: str, base_domain: str, scheme: str = "https") -> str:
    return f"{scheme}://{subdomain}.{base_domain.strip().strip('.').lower()}"


def normalize_origin(value: str) -> str | None:
    """scheme://host[:port] or None. Used to turn the API's CORS allow-list into
    CSP `frame-ancestors` sources — anything that isn't a plain origin (a
    wildcard, a path, garbage) is dropped rather than passed through."""
    try:
        parts = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "*" in value:
        return None
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{netloc}"


def frame_ancestor_sources(origins: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for origin in origins:
        norm = normalize_origin(origin)
        if norm and norm not in seen:
            seen.append(norm)
    return seen


# ---------------------------------------------------------------------------
# Upstream (the Sprite's own URL)
# ---------------------------------------------------------------------------


def validate_upstream_origin(url: str, host_suffix: str) -> str:
    """The proxy attaches the org-wide Sprites API token to every upstream
    request. That token must only ever be sent to a Sprite's own host, so the
    upstream is validated, not trusted just because it came out of an API
    response: https only, no userinfo, no non-default port, hostname must end
    with the configured suffix (".sprites.app"). Returns `https://<host>`."""
    parts = urllib.parse.urlsplit(url)
    suffix = host_suffix if host_suffix.startswith(".") else "." + host_suffix
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise ValueError("Upstream URL must be https.")
    if parts.username or parts.password:
        raise ValueError("Upstream URL must not carry credentials.")
    if parts.port not in (None, 443):
        raise ValueError("Upstream URL must use the default HTTPS port.")
    if not host.endswith(suffix) or host == suffix.lstrip("."):
        raise ValueError(f"Upstream host {host!r} is not under {suffix}.")
    return f"https://{host}"


def upstream_host(origin: str) -> str:
    return urllib.parse.urlsplit(origin).hostname or ""


def websocket_upstream_url(origin: str, path: str, query: str) -> str:
    host = upstream_host(origin)
    url = f"wss://{host}{path or '/'}"
    return f"{url}?{query}" if query else url


# ---------------------------------------------------------------------------
# Request headers
# ---------------------------------------------------------------------------


def _connection_tokens(headers: Iterable[tuple[str, str]]) -> set[str]:
    tokens: set[str] = set()
    for name, value in headers:
        if name.lower() == "connection":
            tokens.update(t.strip().lower() for t in value.split(",") if t.strip())
    return tokens


def strip_cookie_named(cookie_header: str, cookie_name: str = COOKIE_NAME) -> str:
    kept = []
    for pair in cookie_header.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if pair.split("=", 1)[0].strip() == cookie_name:
            continue
        kept.append(pair)
    return "; ".join(kept)


def read_cookie(cookie_header: str | None, cookie_name: str = COOKIE_NAME) -> str | None:
    if not cookie_header:
        return None
    for pair in cookie_header.split(";"):
        name, _, value = pair.strip().partition("=")
        if name.strip() == cookie_name and value:
            return value.strip()
    return None


def filter_request_headers(headers: Iterable[tuple[str, str]], cookie_name: str = COOKIE_NAME) -> list[tuple[str, str]]:
    headers = list(headers)
    connection_listed = _connection_tokens(headers)
    out: list[tuple[str, str]] = []
    for name, value in headers:
        lname = name.lower()
        if lname in HOP_BY_HOP or lname in connection_listed or lname in _DROP_FROM_REQUEST:
            continue
        if lname == "cookie":
            value = strip_cookie_named(value, cookie_name)
            if not value:
                continue
        out.append((name, value))
    return out


def forwarded_headers(public_host: str, scheme: str = "https") -> list[tuple[str, str]]:
    """What the app is told about how it's being reached. Without X-Forwarded-Host
    an app (Next.js server actions, Django's ALLOWED_HOSTS/CSRF, anything building
    absolute URLs) sees the Sprite's internal hostname and either rejects the
    request or emits links to the internal URL."""
    return [("X-Forwarded-Host", public_host), ("X-Forwarded-Proto", scheme)]


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


def strip_frame_ancestors(csp_value: str) -> str:
    directives = [d.strip() for d in csp_value.split(";") if d.strip()]
    kept = [d for d in directives if d.split(None, 1)[0].lower() != "frame-ancestors"]
    return "; ".join(kept)


def sanitize_set_cookie(value: str, cookie_name: str = COOKIE_NAME, embedded_https: bool = True) -> str | None:
    """None = drop this Set-Cookie entirely.

    - the harness's own cookie name is never accepted from the app;
    - `Domain=` is removed (host-only cookie, so no tossing onto the parent);
    - when the preview is served over https, the cookie is rewritten to
      `Secure; SameSite=None; Partitioned`: the preview always lives inside an
      iframe on a *different site* from the harness frontend, where a default
      (Lax) or Strict cookie would be set and then never sent back, silently
      breaking every cookie-session app. Partitioned (CHIPS) keeps it scoped to
      this embedding rather than a cross-site third-party cookie.
    """
    parts = [p.strip() for p in value.split(";")]
    if not parts or not parts[0]:
        return None
    if parts[0].split("=", 1)[0].strip() == cookie_name:
        return None
    attrs = parts[1:]
    drop = ("domain=",) if not embedded_https else ("domain=", "samesite=", "secure", "partitioned")
    kept = []
    for attr in attrs:
        if not attr:
            continue
        low = attr.lower()
        if any(low == d or low.startswith(d) for d in drop):
            continue
        kept.append(attr)
    if embedded_https:
        kept += ["Secure", "SameSite=None", "Partitioned"]
    return "; ".join([parts[0], *kept])


def rewrite_location(value: str, upstream_hostname: str, public_origin_value: str) -> str:
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    if parts.netloc and (parts.hostname or "").lower() == upstream_hostname.lower():
        pub = urllib.parse.urlsplit(public_origin_value)
        return urllib.parse.urlunsplit((pub.scheme, pub.netloc, parts.path, parts.query, parts.fragment))
    return value


def sanitize_response_headers(
    headers: Iterable[tuple[str, str]],
    *,
    upstream_hostname: str,
    public_origin_value: str,
    frame_ancestors: list[str],
    cookie_name: str = COOKIE_NAME,
) -> list[tuple[str, str]]:
    headers = list(headers)
    connection_listed = _connection_tokens(headers)
    embedded_https = public_origin_value.startswith("https://")
    out: list[tuple[str, str]] = []
    for name, value in headers:
        lname = name.lower()
        if lname in HOP_BY_HOP or lname in connection_listed:
            continue
        if lname == "x-frame-options":
            continue
        if lname == "content-security-policy":
            value = strip_frame_ancestors(value)
            if not value:
                continue
        elif lname in ("location", "content-location"):
            value = rewrite_location(value, upstream_hostname, public_origin_value)
        elif lname == "set-cookie":
            cleaned = sanitize_set_cookie(value, cookie_name, embedded_https)
            if cleaned is None:
                continue
            value = cleaned
        out.append((name, value))
    sources = " ".join(frame_ancestors) if frame_ancestors else "'none'"
    out.append(("Content-Security-Policy", f"frame-ancestors {sources}"))
    out.append(("X-Robots-Tag", "noindex, nofollow"))
    return out


def build_session_cookie(value: str, max_age: int, secure: bool) -> str:
    """The harness's own preview-session cookie. Host-only, HttpOnly, Path=/.
    Over https it is Secure; SameSite=None; Partitioned for the same iframe
    reason as sanitize_set_cookie's rewrite; over plain http (local dev) it falls
    back to Lax, which is the best that scheme allows."""
    base = f"{COOKIE_NAME}={value}; Path=/; HttpOnly; Max-Age={int(max_age)}"
    if secure:
        return f"{base}; Secure; SameSite=None; Partitioned"
    return f"{base}; SameSite=Lax"


# ---------------------------------------------------------------------------
# Cold start / retry
# ---------------------------------------------------------------------------


def is_retryable(method: str, status: int | None, *, connect_error: bool = False) -> bool:
    """A Sprite that was asleep answers a request while its service is still
    coming back up with a gateway error (the docs' own example: "Bad gateway,
    because nothing is listening"). That's worth a short wait-and-retry — but
    only for methods that are safe to repeat, and never a request that carried a
    body we've already streamed away."""
    if method.upper() not in ("GET", "HEAD"):
        return False
    return connect_error or (status in RETRYABLE_STATUSES)


def backoff_delays(total_seconds: float, first: float = 0.5, factor: float = 2.0, cap: float = 6.0) -> list[float]:
    delays: list[float] = []
    spent = 0.0
    delay = first
    while spent < total_seconds:
        step = min(delay, cap, total_seconds - spent)
        if step <= 0:
            break
        delays.append(step)
        spent += step
        delay *= factor
    return delays


# ---------------------------------------------------------------------------
# Pages the proxy itself answers with
# ---------------------------------------------------------------------------

_PAGE = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "{refresh}<title>{title}</title>"
    "<style>body{{font:15px/1.5 system-ui,sans-serif;color:#222;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px}}"
    "main{{max-width:420px}}h1{{font-size:17px;margin:0 0 8px}}p{{margin:0 0 8px;color:#555}}</style></head>"
    "<body><main><h1>{title}</h1>{body}</main></body></html>"
)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def error_page_html(title: str, message: str, refresh_seconds: int | None = None) -> str:
    refresh = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">' if refresh_seconds else ""
    return _PAGE.format(refresh=refresh, title=_esc(title), body=f"<p>{_esc(message)}</p>")
