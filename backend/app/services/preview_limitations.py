"""
§23.8 — known preview limitations, and §23.9 point 4's "environment, not code"
routing. Pure and dependency-free (same rule as guard_rules.py /
deploy_detection.py): classification, guidance text and notification content live
here, I/O (the notifications table, the deploy pipeline) lives in
app/services/preview_notifications.py and deploy_pipeline.py.

The contract §23.8 sets, which every function here is shaped by:

  * "Must be surfaced, not silently broken." Each of the four known limits has a
    notification and a standing guidance card, so a broken preview is explained
    rather than mysterious.
  * "Fix/mitigation is always notify-only and opt-in — never forced or
    auto-applied." Nothing in this module (or anything that calls it) changes
    the person's backend, CORS config, OAuth provider, database, or secrets. The
    `action` hints on guidance options are labels for buttons the PERSON clicks
    (open the Secrets panel, copy the preview origin) — they are never executed
    on the person's behalf.
  * "Where it truly can't be fixed, say so clearly rather than leaving a
    mysteriously broken button." OAuth redirect URIs and "needs Docker" are
    marked can_fix="no" / "partly" and the copy says so in plain words.
"""
import re
from dataclasses import dataclass, field

KINDS = ("cors", "secrets", "oauth", "database", "nested_container", "other")

# Names the harness itself sets for a deployed app (deploy_pipeline.py's
# `env_prefix`); never worth asking the person to supply them.
HARNESS_MANAGED_ENV = frozenset({"PORT", "BACKEND_URL"})
# Ordinary process-environment names that show up in .env.example files but are
# not "things to configure".
_IGNORED_ENV_NAMES = frozenset({"PORT", "HOST", "HOSTNAME", "NODE_ENV", "BACKEND_URL", "CI", "TZ", "LANG", "PATH", "HOME"})

_MAX_CLASSIFY_CHARS = 20_000
_MAX_ENV_NAMES = 200


# ---------------------------------------------------------------------------
# Classification — "is this failure an environment issue, and which one?"
# ---------------------------------------------------------------------------

# Checked in this order; the first kind with a match wins. Order matters: the
# nested-container signatures are the most specific, CORS/OAuth strings are
# unambiguous, database errors are next, and "a variable isn't set" is the
# broadest, so it goes last.
_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (
        "nested_container",
        [
            re.compile(r"cannot connect to the docker daemon", re.I),
            re.compile(r"is the docker daemon running", re.I),
            re.compile(r"docker(-compose)?:\s*(command )?not found", re.I),
            re.compile(r"/var/run/docker\.sock", re.I),
            re.compile(r"could not find a valid docker environment", re.I),
            re.compile(r"permission denied while trying to connect to the docker", re.I),
        ],
    ),
    (
        "oauth",
        [
            re.compile(r"redirect_uri_mismatch", re.I),
            re.compile(r"invalid[_ ]redirect[_ ]uri", re.I),
            re.compile(r"redirect uri .{0,80}(is not|isn't|not) (registered|allowed|whitelisted|valid)", re.I),
            re.compile(r"AADSTS50011", re.I),
            re.compile(r"callback url mismatch", re.I),
            re.compile(r"redirect[_ ]url .{0,60}not (allowed|registered)", re.I),
        ],
    ),
    (
        "cors",
        [
            re.compile(r"blocked by cors policy", re.I),
            re.compile(r"no 'access-control-allow-origin' header", re.I),
            re.compile(r"access-control-allow-origin", re.I),
            re.compile(r"\bcors\b.{0,80}(error|policy|blocked|not allowed|rejected|origin)", re.I | re.S),
            re.compile(r"(error|blocked|rejected|origin).{0,80}\bcors\b", re.I | re.S),
        ],
    ),
    (
        "database",
        [
            re.compile(r"can'?t reach database server", re.I),
            re.compile(r"\bP1001\b"),
            re.compile(r"could not connect to server", re.I),
            re.compile(r"connection to server at .{0,80} failed", re.I),
            re.compile(r"no pg_hba\.conf entry", re.I),
            re.compile(r"ECONNREFUSED\S*\s*\S*:(5432|3306|27017|6379|1433)\b"),
            re.compile(r"ETIMEDOUT\S*\s*\S*:(5432|3306|27017|6379|1433)\b"),
            re.compile(r"getaddrinfo (ENOTFOUND|EAI_AGAIN) \S*(db|database|postgres|mysql|mongo|redis|rds|supabase)\S*", re.I),
            re.compile(r"(OperationalError|MongoServerSelectionError|MongoNetworkError).{0,120}(connect|timed out|refused)", re.I | re.S),
            re.compile(r"database .{0,40}(is )?(unreachable|not reachable)", re.I),
        ],
    ),
    (
        "secrets",
        [
            re.compile(r"missing required environment variable", re.I),
            re.compile(r"environment variable[s]? .{0,80}(is |are )?(not set|required|missing|undefined|not defined)", re.I),
            re.compile(r"invalid environment variables", re.I),
            re.compile(r"process\.env\.[A-Z0-9_]+ (is )?(undefined|not defined)", re.I),
            # Name part is case-SENSITIVE (environment variable names are upper-case) so
            # ordinary words ending in "key"/"token" ("monkey", "turkey") never match;
            # only the trailing phrase is case-insensitive.
            re.compile(r"\b[A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL|DSN)\b.{0,60}(?i:is |are )?(?i:required|not set|missing|undefined|not defined|not configured)"),
            re.compile(r"(missing|no|invalid|undefined) (api[_ ]?key|secret|access token|auth token|credentials)", re.I),
            re.compile(r"KeyError: ['\"][A-Z][A-Z0-9_]+['\"]"),
        ],
    ),
]

_DOCKER_CMD_RE = re.compile(r"(^|[\s;&|(`$])docker(-compose)?(\s|$)|(^|[\s;&|(`$])podman(\s|$)")


def classify_environment_issue(text: str | None) -> str | None:
    """A kind from KINDS (minus 'other'), or None when nothing recognisable is
    in `text`. Heuristic by design — it's the deterministic backstop for when no
    LLM diagnosis is available, and the fast path for the nested-container case
    where a model call adds nothing."""
    if not text:
        return None
    haystack = text[-_MAX_CLASSIFY_CHARS:]
    for kind, patterns in _PATTERNS:
        if any(p.search(haystack) for p in patterns):
            return kind
    return None


def mentions_docker(command: str | None) -> bool:
    """§23.6: the repo's own build/run logic tries to use Docker. A Dockerfile
    merely *existing* in the repository is not this — see deploy_detection.py."""
    return bool(command) and bool(_DOCKER_CMD_RE.search(command))


# ---------------------------------------------------------------------------
# .env.example parsing — names only, never values
# ---------------------------------------------------------------------------

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_example_names(text: str | None) -> list[str]:
    """Variable NAMES from a .env.example-style file, in first-seen order. Values
    are discarded here on purpose: these files occasionally have a real value
    pasted into them by accident, and nothing downstream needs one."""
    if not text:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= _MAX_ENV_NAMES:
            break
    return names


def missing_secret_names(example_names: list[str], configured_names: list[str]) -> list[str]:
    configured = set(configured_names) | _IGNORED_ENV_NAMES
    return [n for n in example_names if n not in configured]


# ---------------------------------------------------------------------------
# Preview secret validation
# ---------------------------------------------------------------------------

_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# Names the harness (or the OS environment the app depends on) owns. A secret with
# one of these names would be overridden anyway (preview_runtime.build_target_env
# lets harness-managed values win) — rejecting up front tells the person why instead
# of silently ignoring their value.
RESERVED_SECRET_NAMES = frozenset(
    {"PORT", "BACKEND_URL", "PATH", "HOME", "USER", "SHELL", "PWD", "LD_PRELOAD", "LD_LIBRARY_PATH"}
)
RESERVED_SECRET_PREFIXES = ("QH_", "SPRITE_")


def validate_secret_name(name: str) -> str | None:
    """An error message fit to show the person, or None if the name is fine."""
    if not _SECRET_NAME_RE.match(name or ""):
        return "Use letters, numbers and underscores only, starting with a letter or underscore (like STRIPE_SECRET_KEY)."
    if name.upper() in RESERVED_SECRET_NAMES:
        return f"{name} is set by the harness itself and can't be overridden."
    if name.upper().startswith(RESERVED_SECRET_PREFIXES):
        return "Names starting with QH_ or SPRITE_ are reserved for the harness."
    return None


def normalize_secret_value(value: str) -> str:
    """A single-line secret pasted from a terminal or dashboard very often carries a
    trailing newline that silently breaks authentication. Strip trailing CR/LF from
    single-line values only — a multi-line value (a PEM key) is left exactly as given."""
    trimmed = value.rstrip("\r\n")
    return trimmed if "\n" not in trimmed else value


# ---------------------------------------------------------------------------
# Guidance + notification content
# ---------------------------------------------------------------------------


@dataclass
class GuidanceContext:
    origin: str | None = None  # the stable preview origin, e.g. https://my-app-1a2b3c4d.preview.example.com
    egress_ips: list[str] = field(default_factory=list)
    missing_names: list[str] = field(default_factory=list)


def _origin_text(ctx: GuidanceContext) -> str:
    return ctx.origin or "the preview address (shown once the preview is set up)"


def guidance_for(kind: str, ctx: GuidanceContext) -> dict:
    """The standing explanation for one limitation. `options[].action` is a UI
    label for a button the person chooses to click — never something the harness
    runs by itself."""
    origin = _origin_text(ctx)

    if kind == "cors":
        return {
            "kind": "cors",
            "title": "Your backend may block requests from the preview",
            "can_fix": "yes",
            "why": (
                "Your app's backend probably only accepts requests from its production website. "
                f"The preview is served from a different address ({origin}), so the browser blocks "
                "those calls before they reach the backend."
            ),
            "options": [
                {
                    "label": "Allow the preview address once",
                    "detail": (
                        f"Add {origin} to the backend's allowed origins (its CORS allow-list). This address "
                        "is permanent for this project, so it's a one-time change on your side."
                    ),
                    "action": "copy_origin",
                },
                {
                    "label": "Avoid the browser check",
                    "detail": (
                        "Have the app call the API from its own server (a Next.js rewrite or API route, for "
                        "example) so the browser never makes a cross-origin request."
                    ),
                    "action": None,
                },
            ],
        }

    if kind == "secrets":
        names = ctx.missing_names
        listed = f" Not set yet: {', '.join(names[:12])}{'…' if len(names) > 12 else ''}." if names else ""
        return {
            "kind": "secrets",
            "title": "The preview is missing API keys or other secrets",
            "can_fix": "yes",
            "why": (
                "API keys and tokens usually live in files that are never committed (like .env), so they "
                "aren't in the code that was cloned. Anything that needs them fails until they're provided." + listed
            ),
            "options": [
                {
                    "label": "Add them in Preview secrets",
                    "detail": (
                        "They're given only to the running preview. The coding agent can't see or use them, "
                        "and they're never part of the conversation."
                    ),
                    "action": "open_secrets",
                }
            ],
        }

    if kind == "oauth":
        return {
            "kind": "oauth",
            "title": "Sign-in redirects can't work until the preview address is registered",
            "can_fix": "partly",
            "why": (
                "Sign-in with Google, GitHub and similar providers only sends people back to addresses "
                f"registered in the provider's dashboard. {origin} isn't one of them, so the provider refuses "
                "the redirect."
            ),
            "options": [
                {
                    "label": "Register the preview address yourself",
                    "detail": (
                        f"This often can't be fixed from here. It only works if you add {origin} (plus your "
                        "callback path) to the provider's allowed redirect URIs. The address never changes for "
                        "this project, so you'd do it once."
                    ),
                    "action": "copy_origin",
                },
                {
                    "label": "Skip sign-in in the preview",
                    "detail": "If you'd rather not change the provider's settings, sign-in simply won't work in the preview.",
                    "action": None,
                },
            ],
        }

    if kind == "database":
        if ctx.egress_ips:
            ip_detail = (
                "Ask whoever manages the database to allow connections from: " + ", ".join(ctx.egress_ips) + "."
            )
            ip_action: str | None = "copy_ips"
        else:
            ip_detail = (
                "Ask whoever manages the database to allow connections from the harness's servers. The list of "
                "addresses hasn't been configured for this deployment yet, so there's nothing to copy here."
            )
            ip_action = None
        return {
            "kind": "database",
            "title": "The preview can't reach your database",
            "can_fix": "partly",
            "why": (
                "Many databases only accept connections from approved IP addresses or from inside a private "
                "network. The preview runs from the harness's servers, which aren't on that list."
            ),
            "options": [
                {"label": "Allow the harness's addresses", "detail": ip_detail, "action": ip_action},
                {
                    "label": "Use a staging database",
                    "detail": (
                        "Point the app's database variable (DATABASE_URL, for example) at a staging database "
                        "that is reachable, in Preview secrets."
                    ),
                    "action": "open_secrets",
                },
            ],
        }

    if kind == "nested_container":
        return {
            "kind": "nested_container",
            "title": "This project needs Docker, which isn't available in the preview",
            "can_fix": "no",
            "why": (
                "The preview runs inside a sandbox that can't start containers. If the project's own start-up "
                "needs Docker (docker compose, docker run, a container-based database) it can't run here. "
                "A Dockerfile that merely exists in the repository is not the problem — this is about the "
                "project trying to use Docker while it starts."
            ),
            "options": [
                {
                    "label": "Run it without Docker",
                    "detail": "If the project can run as a plain process against a hosted service, change its start command to do that.",
                    "action": None,
                },
                {
                    "label": "Preview it somewhere that supports containers",
                    "detail": "That isn't something this preview can do, so there's no fix available from here.",
                    "action": None,
                },
            ],
        }

    return {
        "kind": "other",
        "title": "The preview hit an environment problem",
        "can_fix": "no",
        "why": "The failure doesn't look like a bug in the app's code, but it doesn't match a known preview limitation either.",
        "options": [],
    }


def extra_notes(ctx: GuidanceContext) -> list[dict]:
    """Standing facts about how the preview behaves that aren't deploy failures
    but would otherwise show up as mysterious breakage."""
    return [
        {
            "kind": "authorization_header",
            "title": "Same-origin requests that send an Authorization header won't work",
            "can_fix": "no",
            "why": (
                "The preview is reached through a gate that uses the Authorization header itself, so the app's own "
                "Authorization header on requests back to the preview address can't be passed along. Cookie-based "
                "sessions and calls to other origins are not affected."
            ),
            "options": [],
        },
        {
            "kind": "websocket_limits",
            "title": "Live connections are closed when idle",
            "can_fix": "no",
            "why": (
                "WebSockets work through the preview, but they're closed after about a minute and a half of silence "
                "and after fifteen minutes in total, so an open tab can't keep the preview running (and billing) "
                "indefinitely. Reloading the preview reconnects."
            ),
            "options": [],
        },
    ]


def all_guidance(ctx: GuidanceContext) -> list[dict]:
    kinds = ("cors", "secrets", "oauth", "database", "nested_container")
    return [guidance_for(k, ctx) for k in kinds] + extra_notes(ctx)


def build_notification(kind: str, ctx: GuidanceContext, diagnosis_text: str | None = None) -> dict:
    """Content for a project_notifications row. `detail_key` is what decides
    whether a *dismissed* notification re-opens — see 0011_preview.sql."""
    g = guidance_for(kind, ctx)
    body = g["why"]
    if diagnosis_text and kind in ("other", "database", "cors", "oauth", "secrets"):
        body = f"{diagnosis_text.strip()}\n\n{g['why']}" if kind != "other" else diagnosis_text.strip()
    if kind == "secrets" and ctx.missing_names:
        detail_key = "secrets:" + ",".join(sorted(ctx.missing_names))
    else:
        detail_key = kind
    return {"kind": kind, "title": g["title"], "body": body, "detail_key": detail_key, "can_fix": g["can_fix"]}
