"""OpenRouter provider-routing helpers for Kael Beta (added 2026-10-05).

Three small, pure pieces — no I/O, no state — kept out of
two_pass_pipeline.py so they can be unit-tested on their own
(test_provider_routing.py):

1. derive_session_id(): the `session_id` sent with every upstream call.
2. is_no_provider_error() / NO_PROVIDER_CLIENT_PAYLOAD: what to do when
   OpenRouter cannot find ANY provider at or under a pass's max_price.
3. describe_served_by(): the one-line log text that shows which upstream
   host actually served a pass and how much of the prompt hit its cache,
   so the speed-first routing can be checked against real traffic.

WHY session_id (and not a timer of our own)
-------------------------------------------
Kael's routing is speed-first (models/kael/config.py: sort "throughput",
a price ceiling, a latency preference). OpenRouter's prompt-cache
"sticky routing" keeps follow-up requests on the provider that already
holds the cache. Its documentation says sticky routing is NOT used when
`provider.order` is set; it does not say what `provider.sort`,
`allow_fallbacks` or `max_price` do to it. So the safe assumption is that
the old `order: ["relace"]` pin switched stickiness off, and that a
sort-based setup might too.

OpenRouter's documented way to get stickiness explicitly is `session_id`:
when one is sent it is used directly as the sticky routing key, and
stickiness starts on the FIRST successful request instead of only after a
cache hit has already been observed. We therefore send one on every
upstream call and let OpenRouter do the pinning (it keeps the pin for
several minutes of inactivity and resets it on every success, and it
re-routes by itself if the pinned provider errors). A pin kept in this
process would duplicate that, would be lost on every deploy/restart, would
not work with more than one backend instance, and would need
`provider.order` to enforce — the one setting documented to disable
OpenRouter's own stickiness.

The session key is a hash, never raw text: OpenRouter shows session ids in
its dashboard, and nothing about a caller's conversation should be
readable there.
"""
import re
import hashlib

# Prefix is only for readability in OpenRouter's Sessions view; the part
# that matters is the hash after it. Max length allowed upstream is 256.
_SESSION_PREFIX = "kael-"
_SESSION_HASH_CHARS = 32


def _text_of(content) -> str:
    """Plain text of a message `content` that is either a string or a list
    of content parts ({"type": "text"|"input_text", "text": ...})."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts)
    return ""


def first_user_text(input_items: list[dict]) -> str:
    """Text of the FIRST user turn in the caller's own (raw) input. It is
    the one part of a conversation that stays identical on every later
    turn, which is what makes it a stable anchor for a session key. Same
    idea OpenRouter's own automatic fingerprint uses, but scoped to the
    account holder below so two people sending "hi" never share a key."""
    for item in input_items or []:
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content")
            text = _text_of(content)
            # A first turn that is only pictures has no text to anchor on; use
            # the first picture instead (hashed, so no part of it is kept), so
            # one person's picture-only conversations do not all share a key.
            return text if text.strip() else _first_image_anchor(content)
    return ""


def _first_image_anchor(content) -> str:
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if isinstance(url, str) and url:
                return "image:" + hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return ""


def derive_session_id(user_id, input_items: list[dict]) -> str:
    """Stable per-conversation session id: same account + same opening
    user message -> same id, on every turn and for both passes.

    Call this with the caller's RAW input items (before
    response_api.prepare_input_items() adds the per-request random tags),
    otherwise the id would change on every request and stickiness would
    never engage.

    Different accounts never collide (user_id is part of the hash), and an
    empty/unknown user or an empty conversation still gets a valid id."""
    anchor = f"{user_id or 'anon'}\x1f{first_user_text(input_items)}"
    digest = hashlib.sha256(anchor.encode("utf-8", errors="ignore")).hexdigest()
    return _SESSION_PREFIX + digest[:_SESSION_HASH_CHARS]


_TITLES_SUFFIX = "-titles"


def titles_session_id(session_id: str | None) -> str | None:
    """Sticky-routing key for the thinking-title summarizer calls of one
    conversation, or None when the pass has no session id.

    A DIFFERENT key from the draft/critic one on purpose: stickiness (and
    the prompt cache it protects) is per key, and the summarizer's prompt
    prefix (its own system prompt + recent titles) shares nothing with the
    draft or critic prompt. With its own key the summarizer calls of one
    conversation keep landing on the host that already holds THEIR cache,
    instead of being scattered by throughput sorting. Derived from the
    pass's key, so it is as stable and as unreadable as that one."""
    if not session_id:
        return None
    return f"{session_id}{_TITLES_SUFFIX}"


# ---------------------------------------------------------------------
# "No provider at or under the price cap"
# ---------------------------------------------------------------------
# max_price is a hard ceiling: when no provider for the model is at or
# under it, OpenRouter refuses the request instead of overspending.
# Which status code that comes back as is not pinned down in OpenRouter's
# docs (404 and 503 have both been reported), so both are treated as "no
# provider available" — they never mean inference happened or was billed.
_NO_PROVIDER_STATUSES = {404, 503}

NO_PROVIDER_CLIENT_PAYLOAD = {
    "error": {
        "message": "Kael is temporarily unavailable. Please retry in a moment.",
        "type": "server_error",
        "code": "upstream_unavailable",
    }
}


def is_no_provider_error(http_status: int) -> bool:
    return http_status in _NO_PROVIDER_STATUSES


# ---------------------------------------------------------------------
# What a CALLER sees when the upstream host answers with an error
# (added 2026-10-06). Upstream error bodies carry host names, model ids
# and account links ("Provider returned error ... provider_name",
# "<model> is not a valid model ID", "Insufficient credits ... add more
# at <host>"), and the upstream status code describes OUR account, not the
# caller's (a 401/402 from upstream would look to a customer like a bad
# key or an empty balance of their own). So the body is never passed
# through: every upstream failure becomes one of the fixed envelopes below.
# ---------------------------------------------------------------------
_CREDENTIAL_OR_CREDIT_STATUSES = {401, 402, 403}


def _envelope(message: str, err_type: str, code: str) -> dict:
    return {"error": {"message": message, "type": err_type, "code": code}}


def is_credential_or_credit_error(http_status: int) -> bool:
    """True when the upstream host rejected OUR key or says OUR account is
    out of credit. The operator must act on this; the customer cannot."""
    return http_status in _CREDENTIAL_OR_CREDIT_STATUSES


def client_error_for_upstream_status(http_status: int) -> tuple[int, dict]:
    """(status, body) to hand a caller for a non-2xx upstream response.
    Never contains anything from the upstream body."""
    if http_status in (400, 422):
        return 400, _envelope("The request was rejected as invalid. Check your messages, tools and parameters.", "invalid_request_error", "invalid_request")
    if http_status == 413:
        return 413, _envelope("The request is too large.", "invalid_request_error", "request_too_large")
    if http_status == 429:
        return 429, _envelope("Kael is receiving too many requests right now. Please retry in a moment.", "rate_limit_error", "rate_limit_exceeded")
    if http_status in (408, 504):
        return 504, _envelope("The request timed out.", "server_error", "upstream_timeout")
    if http_status in _CREDENTIAL_OR_CREDIT_STATUSES:
        # Same WORDING as "no provider" (from the caller's side Kael is simply
        # unavailable for a moment) but a separate object on purpose:
        # two_pass_pipeline._fallback_body() retries on the backup host when
        # `err.client_payload is NO_PROVIDER_CLIENT_PAYLOAD`. A rejected key or
        # empty credit balance would fail identically on the backup (same
        # account), so it must NOT match that identity check.
        shared = NO_PROVIDER_CLIENT_PAYLOAD["error"]
        return 503, _envelope(shared["message"], shared["type"], shared["code"])
    return 502, _envelope("Could not complete the request \u2014 please retry.", "server_error", "upstream_error")


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\- ]{1,40}$")


def safe_upstream_summary(http_status: int, payload) -> str:
    """A content-free one-line description of an upstream error, for logs and
    for usage_logs / chat_debug_traces `error_message`.

    Why not the upstream text (changed 2026-10-06): upstream error bodies can
    QUOTE THE CALLER'S INPUT (moderation errors carry a `flagged_input`
    snippet, validation errors echo the bad fragment, provider errors put the
    provider's raw reply in `metadata.raw`). API prompts must never be stored,
    so none of that free text is kept. Only short, pattern-checked fields that
    cannot hold prose are: the HTTP status, error `code` and `type`, and the
    serving host's name."""
    parts = [f"upstream HTTP {http_status}"]
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        for key in ("code", "type"):
            value = err.get(key)
            if isinstance(value, (int, str)) and not isinstance(value, bool) and _SAFE_TOKEN.match(str(value)):
                parts.append(f"{key}={value}")
        meta = err.get("metadata")
        host = meta.get("provider_name") if isinstance(meta, dict) else None
        if isinstance(host, str) and _SAFE_NAME.match(host):
            parts.append(f"host={host}")
    return " ".join(parts)


def safe_exception_summary(exc: BaseException) -> str:
    """Content-free description of an UNEXPECTED exception, for usage_logs and
    chat_debug_traces `error_message` (changed 2026-10-13). Only the exception's
    class name: the message of an arbitrary exception can quote the text it was
    processing (a value or JSON error repeats the fragment it choked on), and
    API prompts and answers must never be stored. The detail belongs in the
    server log, not in the database."""
    return type(exc).__name__


_CONTEXT_OVERFLOW = re.compile(r"context[ _-]?(length|window)|maximum context|too many (input )?tokens", re.IGNORECASE)

# The one upstream 400 a caller can actually act on, so it keeps a useful answer
# (OpenAI's own code, which SDKs recognise) even though no upstream text is
# passed through. The upstream wording is only pattern-matched, never stored or
# shown: it names the model's real context size.
CONTEXT_OVERFLOW_CLIENT_ERROR = (
    400,
    _envelope("The request is too long for Kael's context window. Shorten your messages, tools or attachments and retry.",
              "invalid_request_error", "context_length_exceeded"),
)


def is_context_overflow(http_status: int, upstream_text: str) -> bool:
    return http_status in (400, 413, 422) and bool(_CONTEXT_OVERFLOW.search(upstream_text or ""))


def credential_or_credit_log_line(model: str, http_status: int, upstream_text: str) -> str:
    """Loud operator-only line for a 401/402/403 from upstream."""
    return (
        f"[routing] UPSTREAM_CREDENTIALS_OR_CREDIT status={http_status} model={model} "
        f"- callers are being told 503; check the upstream API key and credit balance. "
        f"upstream said: {upstream_text[:300]!r}"
    )


# ---------------------------------------------------------------------
# Backup host (owner's choice, 2026-10-05: "any fast one - use Baseten")
# ---------------------------------------------------------------------
# When the speed-first request is refused with a no-provider status, the
# pass is retried ONCE, pinned to this host. Nothing ran and nothing was
# billed on the refused attempt (see above), so the retry can never pay
# twice. The pass's own max_price is carried over unchanged: the owner's
# price ceiling is never relaxed, not even for the backup. So the backup
# only helps when Baseten is itself at or under the ceiling and the first
# refusal was something else (e.g. a transient 503); if Baseten is over
# the ceiling too, the retry is refused the same way and the caller gets
# the same clean 503. Pinning with `order` switches OpenRouter's sticky
# routing off, which is fine for a rare one-off retry.
FALLBACK_PROVIDER_SLUG = "baseten"


def fallback_routing(routing: dict | None) -> dict | None:
    """The `provider` object for the one backup attempt, or None when this
    pass has no routing object (e.g. a direct Z.ai call) or no price
    ceiling to carry over (never retry without one). Carries over the price
    ceiling AND the data policy (`data_collection` / `zdr`) of the pass."""
    if not routing or not routing.get("max_price"):
        return None
    pinned = {
        "order": [FALLBACK_PROVIDER_SLUG],
        "allow_fallbacks": False,
        "max_price": dict(routing["max_price"]),
    }
    # The data policy is never relaxed for a retry (2026-10-13): if the backup
    # host does not qualify, the retry is refused and the caller gets the same
    # clean 503, which is the intended failure.
    for key in ("data_collection", "zdr"):
        if key in routing:
            pinned[key] = routing[key]
    return pinned


def fallback_log_line(model: str, upstream_text: str) -> str:
    return (
        f"[routing] NO_ELIGIBLE_PROVIDER_RETRY model={model} "
        f"retrying once on {FALLBACK_PROVIDER_SLUG} with the same max_price. "
        f"First refusal said: {upstream_text[:200]!r}"
    )


def no_provider_log_line(model: str, http_status: int, upstream_text: str) -> str:
    """Loud, greppable log line (internal logs may name vendors, see
    AGENTS.md). Search the Render logs for NO_ELIGIBLE_PROVIDER."""
    return (
        f"[routing] NO_ELIGIBLE_PROVIDER model={model} "
        f"status={http_status} — no provider at or under the max_price in "
        f"models/kael/config.py was available. Upstream said: {upstream_text[:300]!r}"
    )


# ---------------------------------------------------------------------
# Mid-stream failure: silent failover to the next-best host (2026-10-09)
# ---------------------------------------------------------------------
# OpenRouter can only fall back to another host BEFORE tokens flow. When a
# host dies mid-generation it ends the stream with a chunk carrying a
# top-level `error` object plus finish_reason "error" (documented:
# openrouter.ai/docs/api/reference/errors-and-debugging, "Mid-Stream
# Errors"), and nothing re-routes it. OpenRouter waives the charge for a
# response that ends with that finish reason, so re-running the pass on a
# different host cannot be paid twice.
#
# The pipeline therefore re-runs the pass ONCE, silently, with the failed
# host added to `provider.ignore`. Everything else in the pass's routing
# (sort by throughput, allow_fallbacks, the price ceiling) is kept, so the
# retry lands on the next-fastest host that is still under the ceiling.
# The caller hears about a failure only if that second attempt fails too.
#
# `content_filter` is NOT retried: it is the model's / host's safety verdict
# on the content (likely to repeat) and OpenRouter's docs only promise the
# free-of-charge rule for the "error" finish reason.

def safe_error_fields(err, host=None) -> dict | None:
    """The only parts of an upstream `error` object that are kept: `code`,
    `error_type` (OpenRouter's typed code, error.metadata.error_type) and the
    serving host's name. Each is pattern-checked so it cannot hold prose; the
    free-text `message` and `metadata.raw` can quote the caller's prompt and
    are never read. None when `err` is not an object."""
    if not isinstance(err, dict):
        return None
    out: dict = {}
    code = err.get("code")
    if isinstance(code, (int, str)) and not isinstance(code, bool) and _SAFE_TOKEN.match(str(code)):
        out["code"] = str(code)
    meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    for key, value in (("error_type", meta.get("error_type")), ("error_type", err.get("type"))):
        if "error_type" not in out and isinstance(value, str) and _SAFE_TOKEN.match(value):
            out["error_type"] = value
    for candidate in (host, meta.get("provider_name")):
        if isinstance(candidate, str) and _SAFE_NAME.match(candidate):
            out["provider"] = candidate
            break
    return out


def failed_pass_summary(final_data: dict) -> str:
    """Content-free one-liner for a pass that ended in failure, for logs and
    trace `error_message`: the normalized finish reason, OpenRouter's native
    one, the error object's code / error_type, and the host that served it."""
    fr = final_data.get("upstream_finish_reason")
    parts = [f"finish_reason={fr}" if fr else "stream ended without a finish_reason"]
    native = final_data.get("native_finish_reason")
    if isinstance(native, str) and _SAFE_TOKEN.match(native):
        parts.append(f"native_finish_reason={native}")
    err = final_data.get("upstream_error") or {}
    for key in ("code", "error_type"):
        if err.get(key):
            parts.append(f"{key}={err[key]}")
    host = failed_host(final_data)
    if host:
        parts.append(f"host={host}")
    return " ".join(parts)


def failed_host(final_data: dict) -> str | None:
    """Name of the host that served a failed pass: the error chunk's own
    `provider` first, else the `provider` carried on the stream's chunks."""
    err = final_data.get("upstream_error") or {}
    for candidate in (err.get("provider"), final_data.get("served_by")):
        if isinstance(candidate, str) and _SAFE_NAME.match(candidate):
            return candidate
    return None


def is_failover_candidate(final_data: dict) -> bool:
    """True when a finished pass failed in a way worth re-running on another
    host: status failed, and not a content_filter verdict (see above)."""
    return final_data.get("status") == "failed" and final_data.get("upstream_finish_reason") != "content_filter"


def ignore_slug(host_name: str | None) -> str | None:
    """`provider.ignore` entry for a host name as OpenRouter reports it on
    responses ("CoreWeave" -> "coreweave", "Google Vertex" -> "google-vertex").
    None when the name does not reduce to a plain slug."""
    if not isinstance(host_name, str):
        return None
    slug = re.sub(r"\s+", "-", host_name.strip().lower())
    return slug if _SAFE_TOKEN.match(slug) else None


def failover_routing(routing: dict | None, final_data: dict) -> tuple[dict, str] | None:
    """(`provider` object, log description) for the one silent re-run of a
    pass that failed mid-stream, or None when no safe re-run exists.

    Normal case: the pass's own routing with the failed host added to
    `ignore`, so OpenRouter's usual speed-first ranking picks the next host.
    When the failed host is unknown (no chunk named it) there is nothing to
    ignore, so the pass is pinned to the backup host instead (same as the
    no-provider retry). Like that retry, this never runs without the pass's
    price ceiling, and never relaxes it."""
    if not routing or not routing.get("max_price"):
        return None
    slug = ignore_slug(failed_host(final_data))
    if slug:
        ignore = sorted({*(routing.get("ignore") or []), slug})
        return {**routing, "ignore": ignore, "max_price": dict(routing["max_price"])}, f"ignoring {slug}"
    pinned = fallback_routing(routing)
    if pinned is None:
        return None
    return pinned, f"failed host unknown, pinning {FALLBACK_PROVIDER_SLUG}"


def failover_log_line(model: str, summary: str, how: str) -> str:
    return f"[routing] MIDSTREAM_FAILOVER model={model} first attempt failed ({summary}); retrying once, {how}. The caller has not been told."


def failover_exhausted_log_line(model: str, first: str, second: str) -> str:
    return f"[routing] MIDSTREAM_FAILOVER_EXHAUSTED model={model} first: {first}; retry: {second}. Reporting the failure to the caller."


# ---------------------------------------------------------------------
# Which host served it, and did the cache hit?
# ---------------------------------------------------------------------
def describe_served_by(pass_name: str, model: str, served_by, usage_norm: dict | None, elapsed_ms: int | None = None) -> str:
    """One log line per finished pass. `served_by` is the `provider` field
    OpenRouter puts on every response/stream chunk (None if absent).
    cached/prompt come from the normalized usage dict; compare cached
    against prompt across consecutive turns of one conversation to see
    whether stickiness is working."""
    u = usage_norm or {}
    prompt = u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
    cached = (u.get("input_tokens_details") or {}).get("cached_tokens", u.get("cached_tokens", 0)) or 0
    took = f" took_ms={elapsed_ms}" if elapsed_ms is not None else ""
    return f"[routing] pass={pass_name} model={model} served_by={served_by or 'unknown'} prompt_tokens={prompt} cached_tokens={cached}{took}"
