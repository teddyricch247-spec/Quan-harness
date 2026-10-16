import asyncio
import datetime
import time
import uuid
import httpx
from decimal import Decimal
from . import chat_history, config


def _public_model_name(product) -> str:
    """What customers see in the MODEL column of the dashboard's request table:
    the model's own public slug, never the stored upstream model id. A row whose
    product is not a current model (old test data should be gone, but a row
    written by an older deploy might exist) shows as the default model."""
    if isinstance(product, str) and product in config.PRODUCTS:
        return config.PRODUCTS[product]["slug"]
    return next(iter(config.PRODUCTS.values()))["slug"]


def _headers():
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)


# Admin aggregate reads (see "Admin" section near the bottom of this
# file) fetch matching rows and sum/count them client-side, the same
# tradeoff fetch_stats below already makes at its own limit=10000 — 
# PostgREST has no server-side SUM/GROUP BY here. 50000 is generous for
# this app's actual current scale (low hundreds of rows total as of
# 2026-08-23) and documented per-function, not silently assumed exact
# forever.
ADMIN_AGGREGATE_ROW_CAP = 50_000


async def log_usage(
    product: str,
    model: str,
    requestor: dict | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int | None = None,
    status: str = "success",
    error_message: str | None = None,
    stream: bool = False,
):
    """Fire-and-forget usage log write. Never raises — logging must never
    break a real request. `requestor` is {"user_id","key_id","name"} —
    from auth.require_account_key for a real API call (key_id is that
    key's real id), or from main.py's _in_app_requestor() for the in-app
    chat feature (key_id=None — there is no API key involved; usage_logs.
    key_id is nullable specifically so this row still gets attributed to
    user_id even without one). Every row is now attributed to the account
    that made the call, so /api/stats can scope results to only the
    signed-in user."""
    if not _enabled():
        return
    requestor = requestor or {}
    row = {
        "product": product,
        "model": model,
        "user_id": requestor.get("user_id"),
        "key_id": requestor.get("key_id"),
        "api_key_label": requestor.get("name"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "status": status,
        # Always short, and always built from content-free parts (see
        # provider_routing.safe_upstream_summary / safe_exception_summary).
        "error_message": error_message[:500] if isinstance(error_message, str) else error_message,
        "stream": stream,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{config.SUPABASE_URL}/rest/v1/usage_logs",
                headers=_headers(),
                json=row,
            )
    except Exception:
        # Logging failures should never take down a live API request.
        pass


async def fetch_stats(user_id: str, days: int = 30) -> dict:
    """Usage for one account only — every user sees exclusively their own
    requests and cost, the way a real API provider's console works."""
    if not _enabled():
        return {"enabled": False}

    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    params = {
        # "id" added 2026-08-29 so `recent` rows below have a stable React
        # key on the frontend — every other field here was already selected.
        "select": "id,created_at,product,model,api_key_label,prompt_tokens,completion_tokens,cached_tokens,total_tokens,status,latency_ms",
        "user_id": f"eq.{user_id}",
        "created_at": f"gte.{since}",
        "order": "created_at.desc",
        "limit": "10000",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{config.SUPABASE_URL}/rest/v1/usage_logs",
            headers=_headers(),
            params=params,
        )
        resp.raise_for_status()
        rows = resp.json()

    totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "total_tokens": 0, "errors": 0}
    by_product: dict[str, dict] = {}
    daily: dict[str, dict] = {}

    # Estimated cost — Quan's customer price (config.current_customer_price),
    # not DeepSeek's/OpenAI's upstream cost, since this is what a frontend
    # shows as the account's own spend. Flat rate as of 2026-08-19 — no
    # peak-hour lookup, so this is cacheable per product rather than
    # needing each row's own timestamp. Rows for a product with no
    # customer pricing yet (not public/billed) are skipped — there's
    # nothing meaningful to charge them for (row_cost stays 0.0).
    #
    # CAVEAT: this recomputes each row's cost from its token counts at the
    # CURRENT price on every read; usage_logs stores no cost column. After a
    # repricing, past rows therefore display at the new price, while
    # billing_ledger (the real charges) keeps the price actually charged.
    # Storing the charged cost per row would fix it, but needs a column.
    _price_cache: dict[str, dict | None] = {}

    def _row_cost(row: dict) -> float:
        product = row.get("product", "")
        if product not in _price_cache:
            _price_cache[product] = config.current_customer_price(product)
        pricing = _price_cache[product]
        if not pricing:
            return 0.0
        prompt_tokens = row.get("prompt_tokens") or 0
        cached_tokens = row.get("cached_tokens") or 0
        cache_miss_input = max(prompt_tokens - cached_tokens, 0)
        return (
            cache_miss_input / 1_000_000 * pricing["input"]
            + cached_tokens / 1_000_000 * pricing["cached_input"]
            + (row.get("completion_tokens") or 0) / 1_000_000 * pricing["output"]
        )

    estimated_cost = 0.0
    for row in rows:
        totals["requests"] += 1
        totals["prompt_tokens"] += row.get("prompt_tokens") or 0
        totals["completion_tokens"] += row.get("completion_tokens") or 0
        totals["cached_tokens"] += row.get("cached_tokens") or 0
        totals["total_tokens"] += row.get("total_tokens") or 0
        if row.get("status") != "success":
            totals["errors"] += 1

        p = row.get("product", "unknown")
        bp = by_product.setdefault(p, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "total_tokens": 0})
        bp["requests"] += 1
        bp["prompt_tokens"] += row.get("prompt_tokens") or 0
        bp["completion_tokens"] += row.get("completion_tokens") or 0
        bp["cached_tokens"] += row.get("cached_tokens") or 0
        bp["total_tokens"] += row.get("total_tokens") or 0

        row_cost = _row_cost(row)
        estimated_cost += row_cost

        day = (row.get("created_at") or "")[:10]
        if day:
            d = daily.setdefault(day, {
                "requests": 0, "prompt_tokens": 0, "cached_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0,
                "cost_usd": 0.0, "latency_sum_ms": 0, "latency_count": 0,
            })
            d["requests"] += 1
            d["prompt_tokens"] += row.get("prompt_tokens") or 0
            d["cached_tokens"] += row.get("cached_tokens") or 0
            d["completion_tokens"] += row.get("completion_tokens") or 0
            d["total_tokens"] += row.get("total_tokens") or 0
            d["cost_usd"] += row_cost
            if row.get("latency_ms") is not None:
                d["latency_sum_ms"] += row["latency_ms"]
                d["latency_count"] += 1

    daily_out = [
        {
            "date": day,
            "input_tokens": v["prompt_tokens"],
            "cached_tokens": v["cached_tokens"],
            "output_tokens": v["completion_tokens"],
            "total_requests": v["requests"],
            "cost_usd": round(v["cost_usd"], 4),
            "avg_latency_ms": round(v["latency_sum_ms"] / v["latency_count"]) if v["latency_count"] else 0,
        }
        for day, v in sorted(daily.items())
    ]

    # Shaped for the dashboard's request table — usage_logs doesn't track
    # which literal route (chat/completions vs responses) a call hit, only
    # its product tier, so `endpoint` reflects the tier's route family, not
    # necessarily the exact path. A real per-request endpoint column
    # (populated by log_usage's callers) would make this exact — noted in
    # the handover doc as a follow-up, not done here.
    def _endpoint_for_product(product: str | None) -> str:
        """The route family a row's model is served on: /<model>/v1/chat/completions.
        usage_logs records the model, not the literal path or wire shape, so this
        is the model's own prefix, not necessarily the exact path called."""
        if isinstance(product, str) and product in config.PRODUCTS:
            return f"/{product}/v1/chat/completions"
        return "/v1/chat/completions"

    # usage_logs.model holds the UPSTREAM model ids (e.g. "<draft>+<critic>"
    # on a two-pass row, and different ids on older rows). Customers must
    # never see those, so the dashboard always gets Kael's public name no
    # matter what is stored. Fixed 2026-10-06 — the dashboard's request table
    # used to print the raw stored value.
    recent_out = [
        {
            "id": str(row.get("id")),
            "timestamp": row.get("created_at"),
            "endpoint": _endpoint_for_product(row.get("product")),
            "model": _public_model_name(row.get("product")),
            "status": 200 if row.get("status") == "success" else 500,
            "tokens": row.get("total_tokens") or 0,
            "cache_hit": bool(row.get("cached_tokens")),
            "latency_ms": row.get("latency_ms") or 0,
            "cost_usd": round(_row_cost(row), 5),
        }
        for row in rows[:20]
    ]

    return {
        "enabled": True,
        "window_days": days,
        "totals": totals,
        "estimated_cost_usd": round(estimated_cost, 4),
        "by_product": by_product,
        "daily": daily_out,
        "recent": recent_out,
    }


def _truncate(text, n=1500):
    if not isinstance(text, str):
        return text
    return text if len(text) <= n else text[:n] + f"…[+{len(text) - n} chars truncated]"


def last_user_text(messages) -> str | None:
    """Best-effort extraction of the last user turn's plain text, for a
    chat_debug_traces row's `last_user_message` column — just enough to
    eyeball what was actually asked without opening the full payload.
    Handles both a plain string `content` and the OpenAI-style list-of-
    content-blocks shape."""
    if not isinstance(messages, list):
        return None
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [b.get("text") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
            return " ".join(texts) if texts else None
        return None
    return None


# ---- Prompt/answer content policy for chat_debug_traces -----------------
# Rule (owner, 2026-10-06): text from the in-app Playground and Chat is kept
# (those users see it in their own history anyway); text from real API
# callers is NEVER stored — only counts, timings and status. The pipeline
# tags in-app requests source="app_chat" and API requests source="api".
#
# Default-deny: content is kept ONLY for the sources listed here. A new
# source value, or a call site that forgets to think about this, stores no
# text. Enforced at this single choke point (every trace write goes through
# start_chat_trace / update_chat_trace) rather than at each of the ~25 call
# sites in two_pass_pipeline.py.
CONTENT_TRACE_SOURCES = frozenset({"app_chat"})
_TRACE_CONTENT_FIELDS = ("last_user_message", "content_preview", "draft_content_preview")

# Trace ids that were opened by a content-allowed source. update_chat_trace
# only receives an id (no source), so it checks membership here; an id that
# is missing — API trace, unknown id, or a process restart mid-request —
# means "strip content". Bounded so it can never grow without limit.
_CONTENT_TRACE_IDS: "dict[str, None]" = {}
_CONTENT_TRACE_IDS_MAX = 5000


def _strip_trace_content(row: dict) -> dict:
    for key in _TRACE_CONTENT_FIELDS:
        row.pop(key, None)
    return row


def _remember_content_trace(trace_id: str) -> None:
    _CONTENT_TRACE_IDS[trace_id] = None
    while len(_CONTENT_TRACE_IDS) > _CONTENT_TRACE_IDS_MAX:
        _CONTENT_TRACE_IDS.pop(next(iter(_CONTENT_TRACE_IDS)))


# chat_debug_traces.session_id (migration 0016) links a Playground diagnostic row
# to its conversation, so deleting the conversation deletes the row. Same rule as
# chat_messages.thinking and chat_message_images: the code works with or without
# the column. If the database reports it as unknown, rows are saved without the
# link until TRACE_SESSION_COLUMN_RETRY_SECONDS later, and requests are never
# affected. Rows saved that way are still removed by the 30-day purge.
TRACE_SESSION_COLUMN_RETRY_SECONDS = 300.0
_trace_session_retry_at = 0.0


def _trace_session_column_usable() -> bool:
    return time.monotonic() >= _trace_session_retry_at


def _note_trace_session_column_missing(status_code: int, body: str) -> bool:
    """True (and the link is shelved for a while) when a failed insert was
    rejected because chat_debug_traces.session_id does not exist."""
    global _trace_session_retry_at
    text = (body or "").lower()
    if status_code in (400, 404) and "session_id" in text and ("could not find" in text or "does not exist" in text):
        _trace_session_retry_at = time.monotonic() + TRACE_SESSION_COLUMN_RETRY_SECONDS
        print("[chat_trace] chat_debug_traces.session_id column unavailable; saving traces without the conversation link (apply migration 0016)")
        return True
    return False


async def start_chat_trace(**fields) -> str | None:
    """Insert the initial chat_debug_traces row for one chat request.
    Returns the row's id (pass it to update_chat_trace as the request
    progresses), or None if tracing is disabled or the insert itself
    failed — every call site treats None as 'tracing unavailable' and
    just skips further update_chat_trace calls rather than erroring.

    Same fire-and-forget contract as log_usage — a trace write must never
    break or slow down a real chat request — except failures are also
    printed (not fully silent), since a debugging tool that fails
    invisibly defeats its own purpose."""
    if not _enabled():
        return None
    row = {k: v for k, v in fields.items() if v is not None}
    keep_content = row.get("source") in CONTENT_TRACE_SOURCES
    if keep_content:
        if "last_user_message" in row:
            row["last_user_message"] = _truncate(row["last_user_message"], 500)
    else:
        _strip_trace_content(row)  # API traffic: counts and status only
        row.pop("session_id", None)  # only Playground rows belong to a conversation
    if "session_id" in row and not _trace_session_column_usable():
        row.pop("session_id")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{config.SUPABASE_URL}/rest/v1/chat_debug_traces",
                headers={**_headers(), "Prefer": "return=representation"},
                json=row,
            )
            if "session_id" in row and resp.status_code >= 400 and _note_trace_session_column_missing(resp.status_code, resp.text):
                # Migration 0016 is not applied yet: save the row without the link.
                row.pop("session_id")
                resp = await client.post(
                    f"{config.SUPABASE_URL}/rest/v1/chat_debug_traces",
                    headers={**_headers(), "Prefer": "return=representation"},
                    json=row,
                )
        if resp.status_code >= 300:
            print(f"[chat_trace] insert failed: {resp.status_code} {resp.text[:300]}")
            return None
        data = resp.json()
        trace_id = data[0]["id"] if data else None
        if trace_id and keep_content:
            _remember_content_trace(trace_id)
        return trace_id
    except Exception as e:
        print(f"[chat_trace] insert error: {e}")
        return None


async def update_chat_trace(trace_id: str | None, **fields) -> None:
    """Patch an existing chat_debug_traces row by id. No-op if trace_id is
    None (tracing was disabled or the initial insert failed), so every
    call site can call this unconditionally without checking first."""
    if not trace_id or not _enabled():
        return
    row = dict(fields)
    if isinstance(row.get("error_message"), str):
        row["error_message"] = row["error_message"][:500]
    if trace_id in _CONTENT_TRACE_IDS:
        for key in ("content_preview", "draft_content_preview"):
            if key in row and row[key] is not None:
                row[key] = _truncate(row[key])
    else:
        _strip_trace_content(row)  # API traffic: never store the text
    row["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.patch(
                f"{config.SUPABASE_URL}/rest/v1/chat_debug_traces",
                headers=_headers(),
                params={"id": f"eq.{trace_id}"},
                json=row,
            )
        if resp.status_code >= 300:
            print(f"[chat_trace] update failed: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        print(f"[chat_trace] update error: {e}")


async def fetch_chat_traces(user_id: str | None = None, limit: int = 30) -> list:
    """Recent chat_debug_traces rows, newest first. Scoped to one user if
    user_id is given (used by /chatbot/api/traces), otherwise all rows."""
    if not _enabled():
        return []
    params = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if user_id:
        params["user_id"] = f"eq.{user_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.SUPABASE_URL}/rest/v1/chat_debug_traces",
                headers=_headers(),
                params=params,
            )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[chat_trace] fetch error: {e}")
        return []


# ---- Retention and account deletion (2026-10-13) --------------------------
# Rules the Privacy Policy states:
#   * a Playground diagnostic record is deleted with its conversation (the
#     session_id foreign key, migration 0016) and in any case when it is 30 days
#     old (purge_expired_chat_traces, run daily by app/scheduled_checks.py);
#   * deleting an account deletes everything keyed to it (account.py).
TRACE_RETENTION_DAYS = 30


async def purge_expired_chat_traces(retention_days: int = TRACE_RETENTION_DAYS) -> int:
    """Deletes every chat_debug_traces row older than `retention_days` through
    the purge_expired_chat_traces() database function (migration 0016) and
    returns how many rows went. Raises on any failure, including the function
    not existing yet, so the caller can log it: a purge that silently does
    nothing would break the retention promise unnoticed."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/rest/v1/rpc/purge_expired_chat_traces",
            headers=_headers(),
            json={"p_retention": f"{int(retention_days)} days"},
        )
    resp.raise_for_status()
    value = resp.json()
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


# Tables whose rows are keyed to a user but do NOT disappear when the auth user
# is deleted: chat_debug_traces.user_id and usage_logs.user_id are ON DELETE SET
# NULL (the rows stay, ownerless). Everything else cascades from auth.users.
_ROWS_KEPT_AFTER_USER_DELETE = ("chat_debug_traces", "usage_logs")


async def delete_user_rows(table: str, user_id: str) -> int | None:
    """Deletes every row of `table` whose user_id is `user_id`. Only the two
    tables above are allowed. Returns the number deleted when the database
    reports it, else None. Raises on a non-2xx response: account deletion must
    stop rather than delete the account while these rows remain."""
    if table not in _ROWS_KEPT_AFTER_USER_DELETE:
        raise ValueError(f"delete_user_rows: {table!r} is not a table this may delete from")
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.delete(
            f"{config.SUPABASE_URL}/rest/v1/{table}",
            headers={**_headers(), "Prefer": "return=minimal,count=exact"},
            params={"user_id": f"eq.{user_id}"},
        )
    resp.raise_for_status()
    content_range = resp.headers.get("content-range", "")
    total = content_range.split("/", 1)[1] if "/" in content_range else ""
    return int(total) if total.isdigit() else None


async def delete_auth_user(user_id: str) -> None:
    """Permanently deletes a Supabase Auth account through GoTrue's admin API
    (hard delete, not a soft delete). The database then removes, by foreign-key
    cascade: the user's conversations, messages and pictures, API keys, billing
    account and ledger, and legal acceptances. A 404 (already gone) counts as
    success, so a retried deletion is harmless. Raises on any other failure."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            "DELETE",
            f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=_headers(),
            json={"should_soft_delete": False},
        )
    if resp.status_code == 404:
        return
    resp.raise_for_status()


# ============================================================
# Chat sessions + messages — real conversation persistence for the
# in-app chat feature (app/main.py's /api/chat/* routes, added
# 2026-08-20). Distinct from chat_debug_traces above: that's a
# diagnostic log (one row per request, truncated previews, for
# debugging); this is the actual source of truth a chat UI reads from to
# restore a conversation after a refresh or a session switch. A session
# is locked to the product it was created with — there's no "switch
# model mid-chat" endpoint, matching how a real deployed product
# wouldn't silently switch either.
#
# These tables and these functions both predate the in-app chat feature —
# they were originally built for the internal admin chatbot, which was
# deleted on 2026-08-19 (see main.py's module docstring). What got
# deleted then was that chatbot's OWN router and page
# (chatbot/router.py, chatbot/chatbot.html) — not these functions, and
# not these tables. They were deliberately left in place, unused for
# about a day, as exactly the reusable hook a future real chat feature
# would need (this was noted explicitly at the time, and turned out to
# be right): main.py's send_chat_message() is that feature, and it calls
# these same functions unchanged.
# ============================================================

class ChatStoreError(Exception):
    """The chat tables could not be read (Supabase down, timeout, a non-2xx).
    Raised by the chat READ helpers below so a route can answer 503 instead of
    mistaking an outage for "no such chat" (404) or "no messages" (an empty
    history that is then sent to the model). Writes stay best-effort."""


async def create_chat_session(user_id: str, model: str, thinking_enabled: bool = False, reasoning_effort: str | None = None) -> dict | None:
    if not _enabled():
        return None
    row = {"user_id": user_id, "model": model, "thinking_enabled": thinking_enabled, "reasoning_effort": reasoning_effort,
           "title": chat_history.DEFAULT_TITLE}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{config.SUPABASE_URL}/rest/v1/chat_sessions",
                headers={**_headers(), "Prefer": "return=representation"},
                json=row,
            )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"[chat_sessions] create error: {e}")
        return None


async def list_chat_sessions(user_id: str, limit: int = 100) -> list:
    if not _enabled():
        return []
    params = {
        "select": "id,model,title,thinking_enabled,reasoning_effort,created_at,last_message_at",
        "user_id": f"eq.{user_id}",
        "order": "last_message_at.desc",
        "limit": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_sessions", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[chat_sessions] list error: {e}")
        raise ChatStoreError(str(e)) from e


async def chat_sessions_with_messages(session_ids: list[str]) -> set[str]:
    """Which of `session_ids` have at least one saved message. Used to tell an
    abandoned empty playground conversation (a first send that failed) from one
    whose bookkeeping update was missed. Raises ChatStoreError on failure so the
    caller can fail open (show everything, delete nothing)."""
    if not _enabled() or not session_ids:
        return set()
    params = {
        "select": "session_id",
        "session_id": "in.(" + ",".join(session_ids) + ")",
        "limit": "500",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_messages", headers=_headers(), params=params)
        resp.raise_for_status()
        return {row["session_id"] for row in resp.json() if row.get("session_id")}
    except Exception as e:
        print(f"[chat_sessions] with_messages error: {e}")
        raise ChatStoreError(str(e)) from e


async def get_chat_session(session_id: str, user_id: str) -> dict | None:
    """Ownership-checked fetch — returns None if the session doesn't exist
    OR belongs to someone else, so callers can't tell the two apart (a
    404 either way, never a 403 that would leak existence). Raises
    ChatStoreError if the lookup itself failed (that is not a 404)."""
    if not _enabled():
        return None
    params = {
        "select": "id,model,title,thinking_enabled,reasoning_effort,created_at,last_message_at",
        "id": f"eq.{session_id}",
        "user_id": f"eq.{user_id}",
        "limit": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_sessions", headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"[chat_sessions] get error: {e}")
        raise ChatStoreError(str(e)) from e


async def touch_chat_session(session_id: str, title: str | None = None) -> None:
    """Bump last_message_at (drives sidebar ordering) and, if given, set
    the title — called once, right after a session's first message, to
    derive a title from it. Best-effort, never raises."""
    if not _enabled():
        return
    row = {"last_message_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if title is not None:
        row["title"] = title
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{config.SUPABASE_URL}/rest/v1/chat_sessions",
                headers=_headers(),
                params={"id": f"eq.{session_id}"},
                json=row,
            )
    except Exception as e:
        print(f"[chat_sessions] touch error: {e}")


async def rename_chat_session(session_id: str, user_id: str, title: str) -> bool:
    if not _enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.patch(
                f"{config.SUPABASE_URL}/rest/v1/chat_sessions",
                headers={**_headers(), "Prefer": "return=representation"},
                params={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}"},
                json={"title": title},
            )
        resp.raise_for_status()
        return bool(resp.json())
    except Exception as e:
        print(f"[chat_sessions] rename error: {e}")
        return False


async def delete_chat_session(session_id: str, user_id: str) -> bool:
    """Deletes the session and, via ON DELETE CASCADE, all its messages and
    pictures and (migration 0016) the Playground diagnostic row of each of its
    requests (chat_debug_traces.session_id). Rows written before 0016 have no
    session_id; the 30-day purge removes those.
    Scoped by user_id so one account can never delete another's session."""
    if not _enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(
                f"{config.SUPABASE_URL}/rest/v1/chat_sessions",
                headers={**_headers(), "Prefer": "return=representation"},
                params={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}"},
            )
        resp.raise_for_status()
        return bool(resp.json())
    except Exception as e:
        print(f"[chat_sessions] delete error: {e}")
        return False


# chat_messages.thinking (jsonb, nullable) holds the thinking titles Kael streamed
# for an assistant reply (migration 0009). The code works with or without the
# column: if the database rejects it as unknown, thinking is neither saved nor
# read until THINKING_COLUMN_RETRY_SECONDS later, and chat history itself is
# never affected. That keeps a backend deploy that lands before the migration
# from breaking chats.
THINKING_COLUMN_RETRY_SECONDS = 300.0
_thinking_column_retry_at = 0.0


def _thinking_column_usable() -> bool:
    return time.monotonic() >= _thinking_column_retry_at


def _note_thinking_column_missing(status_code: int, body: str) -> bool:
    """True (and the column is shelved for a while) when a failed request was
    rejected because chat_messages.thinking does not exist."""
    global _thinking_column_retry_at
    # Match the database's own wording for an unknown column (PostgREST:
    # "Could not find the 'thinking' column of ..."; Postgres: "column
    # chat_messages.thinking does not exist"), not just the word "thinking",
    # which can also appear in an error that echoes a user's message.
    text = (body or "").lower()
    if status_code in (400, 404) and ("'thinking' column" in text or "chat_messages.thinking" in text):
        _thinking_column_retry_at = time.monotonic() + THINKING_COLUMN_RETRY_SECONDS
        print("[chat_sessions] chat_messages.thinking column unavailable; saving chats without thinking (apply migration 0009)")
        return True
    return False


async def list_chat_messages(session_id: str, limit: int | None = None, with_thinking: bool = False) -> list:
    """Messages of one session, oldest first. With `limit`, the NEWEST `limit`
    messages (still returned oldest first). Without a limit PostgREST's own
    1000-row cap applied silently and cut off the newest messages of a long
    chat, so callers should always pass one. Raises ChatStoreError on failure:
    an empty list must mean "no messages", never "the read failed".
    `with_thinking` also returns each reply's saved thinking titles (only the
    page needs them, not the history sent to the model)."""
    if not _enabled():
        return []
    want_thinking = with_thinking and _thinking_column_usable()
    params = {"select": "id,role,content,created_at" + (",thinking" if want_thinking else ""), "session_id": f"eq.{session_id}"}
    if limit:
        params["order"] = "created_at.desc,id.desc"
        params["limit"] = str(limit)
    else:
        params["order"] = "created_at.asc,id.asc"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_messages", headers=_headers(), params=params)
            if want_thinking and resp.status_code >= 400 and _note_thinking_column_missing(resp.status_code, resp.text):
                params["select"] = "id,role,content,created_at"
                resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_messages", headers=_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        print(f"[chat_sessions] list_messages error: {e}")
        raise ChatStoreError(str(e)) from e
    if limit:
        rows.reverse()
    return rows


async def insert_chat_message(session_id: str, role: str, content: str) -> bool:
    """Best-effort — if this write fails, the live turn still completes
    (the user still sees their answer), it just won't be there on reload.
    Failures are printed so that's visible in Render's logs rather than
    silently losing history."""
    if not _enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{config.SUPABASE_URL}/rest/v1/chat_messages",
                headers=_headers(),
                json={"session_id": session_id, "role": role, "content": content},
            )
        if resp.status_code >= 300:
            print(f"[chat_sessions] insert_message failed: {resp.status_code} {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"[chat_sessions] insert_message error: {e}")
        return False


async def insert_chat_exchange(session_id: str, user_content: str, assistant_content: str, user_created_at: datetime.datetime, thinking: list | None = None, images: list | None = None) -> bool:
    """Saves one completed turn — the user's message AND the assistant's reply
    — in a single insert. Called only once a reply has succeeded, so a send
    that fails (402, 429, upstream error, empty reply) leaves nothing behind;
    before 2026-10-04 the user's message was saved first and a failure left it
    orphaned, so the next send put two user messages in a row in the history.
    Explicit created_at values keep the pair ordered (a bulk insert would
    otherwise give both rows the same now()). `thinking` is the list of
    thinking titles Kael streamed for this reply; it is stored on the
    assistant row when the column exists (see _thinking_column_usable above).

    PostgREST rejects a bulk insert whose rows have different keys (400
    PGRST102 "All object keys must match"). From 2026-10-05 to 2026-10-06 only
    the assistant row carried `thinking`, so every reply that streamed thinking
    titles failed to save. Both rows now always carry the same keys, and a
    reply is never lost to the optional thinking titles: if the insert with
    them fails for any reason it is retried once without them.

    `images` is the pictures attached to the user's message, as returned by
    chat_history.clean_images(). They are saved AFTER the exchange, in a
    second request, once the user's message row exists (they reference it).
    That save is best-effort and never changes the result: if it fails (or
    migration 0015 is not applied) the exchange is still saved and this still
    returns True; the pictures are then missing after a reload.

    Best-effort like insert_chat_message: on failure the live turn still
    completed, and the caller reports the reply as unsaved."""
    if not _enabled():
        return False
    saved_thinking = chat_history.clean_thinking(thinking)
    with_thinking = bool(saved_thinking) and _thinking_column_usable()
    # Pictures need the user row's id up front. Every row of a bulk insert must
    # carry the same keys, so both rows get an explicit id when there are pictures.
    saved_images = [i for i in (images or []) if isinstance(i, dict) and i.get("data") and i.get("mime")] if _images_table_usable() else []
    user_message_id = str(uuid.uuid4()) if saved_images else None

    def build(include_thinking: bool) -> list[dict]:
        rows = [
            {"session_id": session_id, "role": "user", "content": user_content, "created_at": user_created_at.isoformat()},
            {"session_id": session_id, "role": "assistant", "content": assistant_content,
             "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        ]
        if saved_images:
            rows[0]["id"] = user_message_id
            rows[1]["id"] = str(uuid.uuid4())
        if include_thinking:
            # Every row in a bulk insert must have the same keys.
            rows[0]["thinking"] = None
            rows[1]["thinking"] = saved_thinking
        return rows

    variants = [True, False] if with_thinking else [False]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for include_thinking in variants:
                rows = build(include_thinking)
                resp = await client.post(f"{config.SUPABASE_URL}/rest/v1/chat_messages", headers=_headers(), json=rows)
                if resp.status_code == 503:
                    # Service unavailable: the request was not processed, so
                    # repeating it once cannot create a duplicate.
                    await asyncio.sleep(0.5)
                    resp = await client.post(f"{config.SUPABASE_URL}/rest/v1/chat_messages", headers=_headers(), json=rows)
                if resp.status_code < 300:
                    if saved_images:
                        await _insert_chat_images(client, session_id, user_message_id, saved_images)
                    return True
                if include_thinking:
                    _note_thinking_column_missing(resp.status_code, resp.text)
                print(f"[chat_sessions] insert_exchange failed (thinking={include_thinking}): {resp.status_code} {resp.text[:300]}")
                if resp.status_code >= 500:
                    # A server error may or may not have committed the rows;
                    # only a definite rejection (4xx) is retried without the
                    # thinking titles, so a turn is never saved twice.
                    return False
        return False
    except Exception as e:
        print(f"[chat_sessions] insert_exchange error: {e}")
        return False


# chat_message_images (migration 0015) holds the pictures attached to user
# messages. Same rule as chat_messages.thinking above: the code works with or
# without the table. If the database reports it as missing, pictures are
# neither saved nor read until IMAGES_TABLE_RETRY_SECONDS later, and the chat
# itself is never affected. A message with pictures is still answered; the
# pictures are just not kept.
IMAGES_TABLE_RETRY_SECONDS = 300.0
_images_table_retry_at = 0.0


def _images_table_usable() -> bool:
    return time.monotonic() >= _images_table_retry_at


def _note_images_table_missing(status_code: int, body: str) -> bool:
    """True (and the table is shelved for a while) when a failed request was
    rejected because chat_message_images does not exist."""
    global _images_table_retry_at
    text = (body or "").lower()
    if status_code in (400, 404) and "chat_message_images" in text and ("could not find the table" in text or "does not exist" in text):
        _images_table_retry_at = time.monotonic() + IMAGES_TABLE_RETRY_SECONDS
        print("[chat_sessions] chat_message_images table unavailable; pictures are not being saved (apply migration 0015)")
        return True
    return False


async def _insert_chat_images(client, session_id: str, message_id: str, images: list[dict]) -> bool:
    """One bulk insert of a message's pictures. Never raises; False on failure."""
    rows = [
        {"session_id": session_id, "message_id": message_id, "position": i, "mime": img["mime"], "data": img["data"],
         "byte_size": int(img.get("bytes") or (len(img["data"]) * 3 // 4))}
        for i, img in enumerate(images)
    ]
    try:
        resp = await client.post(f"{config.SUPABASE_URL}/rest/v1/chat_message_images", headers=_headers(), json=rows)
        if resp.status_code < 300:
            return True
        if not _note_images_table_missing(resp.status_code, resp.text):
            print(f"[chat_sessions] insert_images failed: {resp.status_code} {resp.text[:300]}")
        return False
    except Exception as e:
        print(f"[chat_sessions] insert_images error: {e}")
        return False


async def list_chat_images(session_id: str, with_data: bool = False) -> list:
    """Pictures of one conversation, oldest first: [{id, message_id, position,
    mime, byte_size}] (plus `data`, the base64, when with_data). Without `data` this is
    cheap and is what the page's message list needs; with it, this is the
    history sent to the model on the next turn. [] when migration 0015 is not
    applied. Raises ChatStoreError on any other failure: a history that
    silently lost its pictures would make the model answer a different
    conversation than the user is looking at."""
    if not _enabled() or not _images_table_usable():
        return []
    params = {
        "select": "id,message_id,position,mime,byte_size" + (",data" if with_data else ""),
        "session_id": f"eq.{session_id}",
        "order": "created_at.asc,position.asc,id.asc",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0 if with_data else 10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_message_images", headers=_headers(), params=params)
        if resp.status_code >= 400 and _note_images_table_missing(resp.status_code, resp.text):
            return []
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[chat_sessions] list_images error: {e}")
        raise ChatStoreError(str(e)) from e


async def get_chat_image(session_id: str, image_id: str) -> dict | None:
    """{mime, data} of one picture of this conversation, or None if there is no
    such picture. Raises ChatStoreError if the read itself failed."""
    if not _enabled() or not _images_table_usable():
        return None
    params = {"select": "mime,data", "id": f"eq.{image_id}", "session_id": f"eq.{session_id}", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/chat_message_images", headers=_headers(), params=params)
        if resp.status_code >= 400 and _note_images_table_missing(resp.status_code, resp.text):
            return None
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        print(f"[chat_sessions] get_image error: {e}")
        raise ChatStoreError(str(e)) from e
    return rows[0] if rows else None


async def _admin_replace_user_metadata(user_id: str, merged_user_metadata: dict) -> None:
    """Shared core for update_user_theme/update_user_metadata below —
    PUTs a full user_metadata replacement via GoTrue's admin API.
    `merged_user_metadata` must already include every existing key the
    caller wants kept, not just the ones changing: GoTrue replaces the
    whole object here, it doesn't deep-merge server-side.

    Raises on a non-2xx response (via raise_for_status) — callers that
    want to swallow failures, like update_user_theme below, catch it
    themselves rather than this function hiding it. An earlier version
    of this function awaited the PUT without checking its status at
    all, so a bad service-role key or a bad user_id would silently look
    identical to success — the specific failure mode update_user_metadata's
    docstring already warned about, just not actually guarded against."""
    if not _enabled():
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.put(
            f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=_headers(),
            json={"user_metadata": merged_user_metadata},
        )
        resp.raise_for_status()


async def update_user_theme(user_id: str, merged_user_metadata: dict) -> None:
    """Persists the theme preference on the Supabase user's own
    user_metadata via the GoTrue admin API, so it follows the account
    across devices. `merged_user_metadata` should already include every
    existing metadata key plus the new "theme" — callers merge client-side
    first so this call can't clobber unrelated metadata regardless of
    whether the admin endpoint merges or replaces server-side."""
    try:
        await _admin_replace_user_metadata(user_id, merged_user_metadata)
    except Exception:
        # Theme is a nice-to-have preference, not a critical write.
        pass


async def update_user_metadata(user_id: str, merged_user_metadata: dict) -> None:
    """General-purpose sibling of update_user_theme, for server-side code
    (cron jobs, not request handlers — a logged-in user updates their own
    user_metadata directly via supabase.auth.updateUser() client-side,
    same as name/notification prefs in AccountPage; nothing in main.py
    calls this) that needs to write into a user's metadata using the
    service role. Added for app/jobs/low_balance_alerts.py, which needs
    to record `low_balance_alert_sent_at` so it doesn't re-email someone
    once a day for every request that finds their balance still low.
    Unlike update_user_theme, this re-raises on failure — a job silently
    losing its own dedupe-state write would re-alert every run instead of
    once, which is worse than the job just failing loudly."""
    await _admin_replace_user_metadata(user_id, merged_user_metadata)


# ============================================================
# Admin (added 2026-08-23 — see app/admin.py and app/auth.py's
# require_admin). Everything below is read/written only by an
# already-admin-gated caller; nothing here does its own authorization
# check, same division of responsibility as every other function in this
# file (the FastAPI dependency is the gate, not the data layer).
#
# There is no way to read auth.users over PostgREST — Supabase only
# exposes `public`/`storage`/`graphql_public` there by default, not
# `auth` — so every "real user directory" read below goes through
# GoTrue's own admin API instead, the same one update_user_theme above
# already uses for writes.
# ============================================================

ADMIN_LIST_USERS_PAGE_SIZE = 200


async def list_auth_users() -> list[dict]:
    """Every Supabase Auth account, via GoTrue's admin listUsers
    endpoint, paginated until a short page confirms the end. Each
    returned dict is GoTrue's own User shape, untouched (id, email,
    created_at, last_sign_in_at, app_metadata, user_metadata,
    identities, banned_until, ...) — see is_admin_user/is_suspended_user/
    github_username below for how callers read specific fields off of
    it, rather than this function reshaping a copy that could drift from
    a future GoTrue response change."""
    if not _enabled():
        return []
    users: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{config.SUPABASE_URL}/auth/v1/admin/users",
                headers=_headers(),
                params={"page": str(page), "per_page": str(ADMIN_LIST_USERS_PAGE_SIZE)},
            )
            resp.raise_for_status()
            batch = resp.json().get("users", [])
            users.extend(batch)
            if len(batch) < ADMIN_LIST_USERS_PAGE_SIZE:
                break
            page += 1
    return users


async def get_auth_user(user_id: str) -> dict | None:
    """A single Supabase Auth account by id, via GoTrue's admin get-user
    endpoint (GET /auth/v1/admin/users/{id}) — same User shape as
    list_auth_users' entries. Returns None if the account doesn't exist
    or the request fails, rather than raising, since callers (e.g.
    admin.suspend_user's is_admin_user guard) should fail safe: an
    unreadable target is not proof it's safe to suspend, but this
    function itself just reports "unknown" and lets the caller decide."""
    if not _enabled():
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                headers=_headers(),
            )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[admin] get_auth_user error: {e}")
        return None


def github_username(user: dict) -> str | None:
    """Best-effort GitHub handle for a GoTrue user dict, read from the
    github identity's OWN identity_data — not the top-level
    user_metadata bag, which GoTrue merges across every linked provider
    and could carry a stale/ambiguous value once more than one provider
    is ever linked to the same account. Verified directly against a real
    signed-in GitHub user's row on the live Supabase project (ref
    redacted — see internal ops notes; verified 2026-08-23): identity_data
    carries both `user_name` and
    `preferred_username` holding the same value; `user_name` is read
    first, `preferred_username` kept as a fallback in case a future
    GitHub OAuth payload shape only carries one of the two. Returns None
    for anyone who didn't sign in via GitHub (email accounts) —
    never fabricated, per the prompt's instruction not to fake a value
    here."""
    for identity in user.get("identities") or []:
        if identity.get("provider") == "github":
            data = identity.get("identity_data") or {}
            return data.get("user_name") or data.get("preferred_username")
    return None


def is_admin_user(user: dict) -> bool:
    """True iff app_metadata.role == "admin" — see app/auth.py's
    require_admin for why app_metadata (service-role-only-writable) and
    not user_metadata (user-writable) is the mechanism."""
    return (user.get("app_metadata") or {}).get("role") == "admin"


def is_suspended_user(user: dict) -> bool:
    """True iff banned_until is set AND still in the future. GoTrue
    never clears banned_until once it passes — it's a timestamp, not a
    boolean, and stays populated after expiry (confirmed via Supabase's
    own issue tracker) — so a stale past timestamp must read as "not
    suspended", not just "banned_until is not null"."""
    banned_until = user.get("banned_until")
    if not banned_until:
        return False
    try:
        until = datetime.datetime.fromisoformat(banned_until.replace("Z", "+00:00"))
    except ValueError:
        return False
    return until > datetime.datetime.now(datetime.timezone.utc)


async def set_user_ban(user_id: str, ban_duration: str) -> None:
    """Suspend (ban_duration e.g. "876000h", ~100 years — see
    app/admin.py's SUSPEND_BAN_DURATION) or reactivate
    (ban_duration="none", GoTrue's own documented "lift the ban" value)
    a user for real, via the same GoTrue admin
    PUT /auth/v1/admin/users/{id} pattern update_user_theme above already
    uses. This is what actually blocks sign-in and token refresh at the
    Supabase Auth layer — see app/admin.py's suspend_user for why
    product API-key traffic additionally needs api_keys revoked
    directly; banning the auth user alone never touches that table."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=_headers(),
            json={"ban_duration": ban_duration},
        )
    resp.raise_for_status()


async def create_auth_user(email: str, password: str, name: str | None = None) -> dict:
    """Creates a new Supabase Auth user directly via GoTrue's admin API
    (POST /auth/v1/admin/users), for the backend-controlled email+password
    signup flow (see app/auth_email.py). email_confirm=False — this app
    never lets Supabase auto-confirm or send its own email; confirmation
    happens only once the user clicks the link this app emails them via
    Resend. Raises httpx.HTTPStatusError (via raise_for_status) on
    failure, notably a 422/400 if the email is already registered —
    callers should check find_auth_user_by_email first to give a cleaner
    error path than catching this."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/auth/v1/admin/users",
            headers=_headers(),
            json={
                "email": email,
                "password": password,
                "email_confirm": False,
                "user_metadata": {"full_name": name} if name else {},
            },
        )
    resp.raise_for_status()
    return resp.json()


async def update_user_password(user_id: str, password: str) -> None:
    """Resets a user's password directly via GoTrue's admin API — used
    when someone re-submits the signup form for an email that already
    has an unconfirmed account (an earlier incomplete signup): rather
    than reject them, this app updates the password to whatever they
    just typed and resends confirmation (see app/auth_email.py's
    signup())."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(
            f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=_headers(),
            json={"password": password},
        )
    resp.raise_for_status()


async def record_legal_acceptance(
    user_id: str,
    documents: list[str],
    method: str = "signup_form",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Inserts one row per document into public.legal_acceptances (see
    supabase/migrations/0007_legal_acceptances.sql) — the durable,
    server-side record that a given user actually accepted the Terms of
    Service / Privacy Policy, and when. `documents` is normally
    ["terms", "privacy"] (both accepted together via the single signup
    checkbox). Versions are pulled from config.TERMS_VERSION /
    config.PRIVACY_VERSION rather than passed in, so there's one place
    to bump when the page content changes.

    Best-effort: logs and swallows failures rather than raising, same
    as update_user_theme above — a failed insert here shouldn't fail
    the signup itself (the account already exists by the time this is
    called; the alternative is a confirmed user stuck in an error
    state over a logging write). If this ever needs to be a hard
    requirement instead, call it BEFORE create_auth_user and roll back
    account creation on failure.
    """
    if not _enabled():
        return
    version_by_document = {"terms": config.TERMS_VERSION, "privacy": config.PRIVACY_VERSION}
    rows = [
        {
            "user_id": user_id,
            "document": doc,
            "version": version_by_document.get(doc, "unknown"),
            "method": method,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        for doc in documents
    ]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.SUPABASE_URL}/rest/v1/legal_acceptances",
                headers={**_headers(), "Prefer": "return=minimal"},
                json=rows,
            )
        if resp.status_code >= 400:
            print(f"[legal_acceptances] insert failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[legal_acceptances] insert raised: {e}")


async def has_legal_acceptance(user_id: str, document: str = "terms") -> bool:
    """Whether `user_id` already has ANY recorded acceptance for
    `document` — used to make record_oauth_consent idempotent (the
    OAuth flow below can plausibly fire more than once for the same
    user, e.g. a stale pending-consent flag from a previous incomplete
    attempt; this stops a second call from writing duplicate rows into
    an otherwise-append-only audit table)."""
    if not _enabled():
        return False
    params = {"select": "id", "user_id": f"eq.{user_id}", "document": f"eq.{document}", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/legal_acceptances", headers=_headers(), params=params)
        if resp.status_code >= 400:
            print(f"[legal_acceptances] lookup failed ({resp.status_code}): {resp.text}")
            return False
        return len(resp.json()) > 0
    except Exception as e:
        print(f"[legal_acceptances] lookup raised: {e}")
        return False


async def find_auth_user_by_email(email: str) -> dict | None:
    """Looks up a single Auth user by exact (case-insensitive) email —
    used by the signup and forgot-password flows to check whether an
    account already exists, without creating one. Filters
    list_auth_users() client-side rather than relying on a GoTrue
    query-param filter (whose exact support/behavior isn't guaranteed
    stable across GoTrue versions); fine at this app's current scale per
    list_auth_users()'s own docstring."""
    target = email.strip().lower()
    for u in await list_auth_users():
        if (u.get("email") or "").strip().lower() == target:
            return u
    return None


async def generate_action_link(link_type: str, email: str, redirect_to: str | None = None) -> dict:
    """GoTrue admin generate_link (POST /auth/v1/admin/generate_link) —
    mints a one-time verification URL WITHOUT Supabase sending its own
    email for it, so this app can email it via Resend instead (see
    app/auth_email.py / app/email_service.py).

    link_type is "magiclink" (used for BOTH the initial signup
    confirmation and any resend, since — unlike type="signup" — it works
    for an email that already has an unconfirmed account; GoTrue's
    "signup" type only succeeds when the user doesn't exist yet) or
    "recovery" (password reset). Clicking either link confirms the
    user's email as a side effect if it wasn't already confirmed.

    Returns GoTrue's raw response; the emailable URL is at
    `properties.action_link`. Raises httpx.HTTPStatusError (via
    raise_for_status) if GoTrue rejects the request, e.g. "recovery" for
    an email with no account."""
    if not _enabled():
        raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    body: dict = {"type": link_type, "email": email}
    if redirect_to:
        body["options"] = {"redirect_to": redirect_to}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/auth/v1/admin/generate_link",
            headers=_headers(),
            json=body,
        )
    resp.raise_for_status()
    return resp.json()


async def exact_count(table: str, params: dict) -> int:
    """Row count for a filtered query against `table`, via PostgREST's
    exact-count header, without pulling any actual rows — the response's
    Content-Range header comes back as e.g. "0-0/47" (or "*/0" for an
    empty result); the number after "/" is the real total. Used for
    admin counts (total users derived from list_auth_users() instead;
    this is for usage_logs/api_keys row counts) that need to be exactly
    right, not an approximation from a capped fetch."""
    if not _enabled():
        return 0
    headers = {**_headers(), "Prefer": "count=exact", "Range": "0-0"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/{table}", headers=headers, params=params)
    resp.raise_for_status()
    content_range = resp.headers.get("content-range", "")
    if "/" not in content_range:
        return 0
    total = content_range.split("/", 1)[1]
    return int(total) if total.isdigit() else 0


async def admin_cache_hit_rate_since(since_iso: str) -> float | None:
    """sum(cached_tokens)/sum(prompt_tokens) across every usage_logs row
    created since `since_iso`, ALL accounts — the admin-wide counterpart
    to fetch_stats' per-account version above. Capped at
    ADMIN_AGGREGATE_ROW_CAP most-recent matching rows (see that
    constant's comment) since this sums client-side over what it
    actually fetched, not a server-side aggregate. Returns None — not 0 —
    if there were zero prompt tokens in the window, since a real "no
    data yet" and a real "0% hit rate" mean different things on a
    dashboard."""
    if not _enabled():
        return None
    params = {
        "select": "prompt_tokens,cached_tokens",
        "created_at": f"gte.{since_iso}",
        "order": "created_at.desc",
        "limit": str(ADMIN_AGGREGATE_ROW_CAP),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/usage_logs", headers=_headers(), params=params)
    resp.raise_for_status()
    rows = resp.json()
    total_prompt = sum(r.get("prompt_tokens") or 0 for r in rows)
    total_cached = sum(r.get("cached_tokens") or 0 for r in rows)
    if total_prompt <= 0:
        return None
    return round(total_cached / total_prompt, 4)


async def admin_revenue_since(since_iso: str) -> Decimal:
    """Real revenue since `since_iso` = actual usage-based charges, NOT
    deposits — a top-up isn't revenue until it's actually spent. Sums
    billing_ledger's kind='usage' rows' amount_usd (stored negative, see
    app/billing.py's deduct_balance() call / the 0004_billing.sql
    migration) and negates to a positive dollar figure. Same
    ADMIN_AGGREGATE_ROW_CAP tradeoff as admin_cache_hit_rate_since
    above. Deliberately not called "MRR" anywhere in this codebase —
    see app/admin.py's module docstring for why that term doesn't really
    fit a prepaid-balance, flat-per-token pricing model with no
    subscription concept."""
    if not _enabled():
        return Decimal("0")
    params = {
        "select": "amount_usd",
        "kind": "eq.usage",
        "created_at": f"gte.{since_iso}",
        "order": "created_at.desc",
        "limit": str(ADMIN_AGGREGATE_ROW_CAP),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_ledger", headers=_headers(), params=params)
    resp.raise_for_status()
    total = sum((Decimal(str(r.get("amount_usd") or 0)) for r in resp.json()), Decimal("0"))
    return -total  # usage rows are stored negative (see deduct_balance)


async def admin_usage_counts_by_user() -> dict[str, int]:
    """{user_id: total_requests}, all-time, across every usage_logs row —
    grouped client-side (PostgREST has no server-side GROUP BY over this
    REST interface). Capped at ADMIN_AGGREGATE_ROW_CAP most-recent rows;
    see that constant's comment. Feeds GET /api/admin/users'
    total_requests column (app/admin.py) — deliberately all-time there,
    unlike admin_cache_hit_rate_since's 30-day window for the stats
    widget, since a per-user admin table is more useful as a lifetime
    total."""
    if not _enabled():
        return {}
    params = {
        "select": "user_id",
        "order": "created_at.desc",
        "limit": str(ADMIN_AGGREGATE_ROW_CAP),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/usage_logs", headers=_headers(), params=params)
    resp.raise_for_status()
    counts: dict[str, int] = {}
    for row in resp.json():
        uid = row.get("user_id")
        if uid:
            counts[uid] = counts.get(uid, 0) + 1
    return counts


async def admin_spend_by_user() -> dict[str, Decimal]:
    """{user_id: total_spend_usd}, all-time, positive dollars — every
    billing_ledger kind='usage' row, grouped and summed client-side, sign
    flipped the same way admin_revenue_since does. Same cap/tradeoff as
    admin_usage_counts_by_user above."""
    if not _enabled():
        return {}
    params = {
        "select": "user_id,amount_usd",
        "kind": "eq.usage",
        "order": "created_at.desc",
        "limit": str(ADMIN_AGGREGATE_ROW_CAP),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_ledger", headers=_headers(), params=params)
    resp.raise_for_status()
    totals: dict[str, Decimal] = {}
    for row in resp.json():
        uid = row.get("user_id")
        if not uid:
            continue
        amt = Decimal(str(row.get("amount_usd") or 0))
        totals[uid] = totals.get(uid, Decimal("0")) - amt  # stored negative
    return totals
