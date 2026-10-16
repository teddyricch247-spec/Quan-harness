"""
Self-serve API key management.

This replaces the old model: three static QUAN_*_API_KEY values pasted into
Render's environment variables by hand. Now, every signed-in user generates
their own keys from the dashboard's API Keys page; each key is stored in
Supabase (hashed — the full secret is shown exactly once, at creation, and
never again) and works across all three products. Nothing about which
product a request hits is decided by the key anymore — see auth.py.

Table: public.api_keys (applied to the live database, but its migration file is
not in this repo — see supabase/README.md; the live schema is the source of truth)
  id uuid, user_id uuid, name text, key_prefix text, key_hash text,
  scopes text[], created_at, last_used_at, revoked_at,
  thinking_level text (nullable; migration 0013 — see below)

Thinking level (2026-10-08): each key can pin the thinking tier for every
request made with it. NULL means "SDK": the request's own reasoning_effort
decides, exactly as before. Otherwise it is one of the tier names in
models/kael/config.py's `reasoning_tiers`, and the request's own
reasoning_effort is ignored (kael_pipeline._pinned_tier). This exists for
agents such as Cursor that cannot send reasoning_effort at all. The column
may not exist yet if migration 0013 has not been applied: reads and creates
fall back to working without it (see _missing_column), so deploy order does
not matter.

RLS on api_keys is enabled with zero policies, same as usage_logs — only
this backend, holding the service_role key, can read or write it.
"""

import datetime
import hashlib
import secrets
import httpx
from fastapi import HTTPException
from . import config

KEY_PREFIX = "sk-quan-"
# How many characters *after* KEY_PREFIX are kept visible in the dashboard's
# key list (e.g. "sk-quan-9F2aC81k••••••••"), so a key stays identifiable
# without exposing anything an attacker could use.
PREFIX_VISIBLE_CHARS = 8


def _enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)


def _require_enabled():
    if not _enabled():
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": "Server auth is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).", "type": "server_error"}},
        )


def _headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _hash_secret(secret: str) -> str:
    return hashlib.sha256((config.API_KEY_PEPPER + secret).encode()).hexdigest()


def _generate_secret() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


# What the dashboard and the API call "no pinned level". Stored as NULL.
SDK_LEVEL = "sdk"


def valid_thinking_levels() -> list[str]:
    """Pinnable tier names, straight from the table that defines them
    (models/kael/config.py `reasoning_tiers`), so a tier added or renamed
    there needs no edit here. Reads every product that has such a table
    (first-seen order) instead of one hardcoded product key, so it keeps
    working if products are renamed or split. A product that lacks a pinned
    tier simply lets the request decide (kael_pipeline._pinned_tier)."""
    levels: list[str] = []
    for product in config.PRODUCTS.values():
        for name in product.get("reasoning_tiers") or {}:
            if name not in levels:
                levels.append(name)
    return levels


def normalize_thinking_level(raw) -> str | None:
    """Validates a caller-supplied level for create/update. Returns the tier
    name, or None for "SDK" (None, "", or "sdk"). Anything else is a 400 in
    the app's standard error shape, never a silent fallback: someone who
    mistypes a level should find out."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "thinking_level must be a string.", "type": "invalid_request_error", "param": "thinking_level"}},
        )
    value = raw.strip().lower()
    if value in ("", SDK_LEVEL):
        return None
    levels = valid_thinking_levels()
    if value not in levels:
        listed = ", ".join(f"'{n}'" for n in [SDK_LEVEL, *levels])
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Invalid thinking_level '{raw}'. Use one of {listed}.", "type": "invalid_request_error", "param": "thinking_level"}},
        )
    return value


def _missing_column(resp) -> bool:
    """True when PostgREST rejected a request because api_keys.thinking_level
    does not exist yet (migration 0013 not applied)."""
    return resp.status_code == 400 and "thinking_level" in resp.text


def _public_level(stored) -> str:
    """What the dashboard sees: a tier name, or "sdk" for NULL / anything
    that is no longer a real tier."""
    return stored if stored in valid_thinking_levels() else SDK_LEVEL


async def create_api_key(user_id: str, name: str | None, thinking_level: str | None = None) -> dict:
    """Creates a new key for `user_id`. Returns the plaintext secret — the
    ONLY time it will ever be available. Only the hash is stored.
    `thinking_level` is a raw caller value ("sdk" or a tier name); it is
    validated here, before anything is created."""
    _require_enabled()
    level = normalize_thinking_level(thinking_level)
    secret = _generate_secret()
    display_prefix = secret[: len(KEY_PREFIX) + PREFIX_VISIBLE_CHARS]
    clean_name = (name or "").strip()[:80] or "Default key"

    row = {
        "user_id": user_id,
        "name": clean_name,
        "key_prefix": display_prefix,
        "key_hash": _hash_secret(secret),
    }
    # Only sent when pinned, so creating an "SDK" key never touches the new
    # column and keeps working before migration 0013 is applied.
    if level is not None:
        row["thinking_level"] = level
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/rest/v1/api_keys",
            headers=_headers({"Prefer": "return=representation"}),
            json=row,
        )
    if level is not None and _missing_column(resp):
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Thinking levels are not available yet. Create the key with SDK for now.", "type": "server_error"}},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not create API key.", "type": "server_error"}})
    created = resp.json()[0]

    return {
        "id": created["id"],
        "name": created["name"],
        "prefix": created["key_prefix"],
        "created_at": created["created_at"],
        "last_used_at": None,
        "revoked": False,
        "thinking_level": level or SDK_LEVEL,
        "secret": secret,  # show once, then discard — never logged, never re-fetchable
    }


async def list_api_keys(user_id: str) -> list[dict]:
    _require_enabled()
    base_columns = "id,name,key_prefix,created_at,last_used_at,revoked_at"
    params = {
        "select": f"{base_columns},thinking_level",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/api_keys", headers=_headers(), params=params)
        if _missing_column(resp):  # migration 0013 not applied yet: every key is "SDK"
            params["select"] = base_columns
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/api_keys", headers=_headers(), params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not load API keys.", "type": "server_error"}})
    rows = resp.json()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "prefix": r["key_prefix"],
            "created_at": r["created_at"],
            "last_used_at": r.get("last_used_at"),
            "revoked": r.get("revoked_at") is not None,
            "thinking_level": _public_level(r.get("thinking_level")),
        }
        for r in rows
    ]


async def update_thinking_level(user_id: str, key_id: str, thinking_level) -> str | None:
    """Sets (or clears, with "sdk") one key's pinned thinking level. Takes
    effect on that key's very next request: verify_api_key reads the column
    on every call, nothing is cached. Ownership is enforced by the user_id
    filter, and a revoked key cannot be edited. Returns the stored public
    value ("sdk" or a tier name), or None if no such active key exists for
    this user."""
    _require_enabled()
    level = normalize_thinking_level(thinking_level)
    params = {"id": f"eq.{key_id}", "user_id": f"eq.{user_id}", "revoked_at": "is.null"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{config.SUPABASE_URL}/rest/v1/api_keys",
            headers=_headers({"Prefer": "return=representation"}),
            params=params,
            json={"thinking_level": level},
        )
    if _missing_column(resp):
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Thinking levels are not available yet. Please try again shortly.", "type": "server_error"}},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not update the thinking level.", "type": "server_error"}})
    rows = resp.json()
    if not rows:
        return None
    return level or SDK_LEVEL


async def revoke_api_key(user_id: str, key_id: str) -> bool:
    """Soft-deletes a key by setting revoked_at. Ownership is enforced via
    the user_id filter, so one account can never revoke another's key."""
    _require_enabled()
    params = {"id": f"eq.{key_id}", "user_id": f"eq.{user_id}", "revoked_at": "is.null"}
    body = {"revoked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{config.SUPABASE_URL}/rest/v1/api_keys",
            headers=_headers({"Prefer": "return=representation"}),
            params=params,
            json=body,
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not revoke API key.", "type": "server_error"}})
    return len(resp.json()) > 0


async def revoke_all_active_keys(user_id: str) -> int:
    """Bulk revoke — every currently-active key for one account, in one
    call. This is the piece that makes POST /api/admin/users/{id}/suspend
    (app/admin.py) actually stop API traffic: banning the Supabase Auth
    user (app/supabase_client.py's set_user_ban) touches auth.users only
    — require_account_key (this app's gate for every /<model>/v1 and
    generic /v1 route) never looks at Supabase Auth at all, only this
    table's own key_hash + revoked_at. Without this, a suspended user's
    existing keys would keep authenticating product requests
    indefinitely. Returns how many keys were actually revoked (0 if the
    account had none active) so the caller can report a real number, not
    just "done"."""
    _require_enabled()
    params = {"user_id": f"eq.{user_id}", "revoked_at": "is.null"}
    body = {"revoked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{config.SUPABASE_URL}/rest/v1/api_keys",
            headers=_headers({"Prefer": "return=representation"}),
            params=params,
            json=body,
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not revoke API keys.", "type": "server_error"}})
    return len(resp.json())


async def admin_active_key_counts() -> dict[str, int]:
    """{user_id: active_key_count} — every non-revoked key across every
    account, grouped client-side (PostgREST has no server-side GROUP BY
    here). Feeds GET /api/admin/users' active_keys_count column
    (app/admin.py)."""
    _require_enabled()
    params = {"select": "user_id", "revoked_at": "is.null"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/api_keys", headers=_headers(), params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"message": "Could not load API key counts.", "type": "server_error"}})
    counts: dict[str, int] = {}
    for row in resp.json():
        uid = row.get("user_id")
        if uid:
            counts[uid] = counts.get(uid, 0) + 1
    return counts


async def verify_api_key(secret: str) -> dict | None:
    """Used on every /<model>/v1 and generic /v1 request (there is no /flash or
    /ultra product anymore — both removed, see models/__init__.py's
    docstring).
    Returns {"user_id", "key_id", "name", "thinking_level"} for a valid,
    non-revoked key, else None. `thinking_level` is the key's pinned tier
    name, or None for "SDK" (the request decides) — see this module's
    docstring and kael_pipeline._pinned_tier. Never raises for a bad key — that's a normal 401, not a
    server error."""
    if not _enabled() or not secret or not secret.startswith(KEY_PREFIX):
        return None

    key_hash = _hash_secret(secret)
    params = {"select": "id,user_id,name,revoked_at,thinking_level", "key_hash": f"eq.{key_hash}", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/api_keys", headers=_headers(), params=params)
            if _missing_column(resp):
                # Migration 0013 not applied yet. Without this retry, selecting
                # a column that does not exist would 400 and EVERY key would
                # fail to authenticate.
                params["select"] = "id,user_id,name,revoked_at"
                resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/api_keys", headers=_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
    except httpx.HTTPError:
        return None

    if not rows or rows[0].get("revoked_at"):
        return None
    row = rows[0]

    # Fire-and-forget last_used_at bump — must never block or fail the
    # actual API request over a bookkeeping write.
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{config.SUPABASE_URL}/rest/v1/api_keys",
                headers=_headers(),
                params={"id": f"eq.{row['id']}"},
                json={"last_used_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
            )
    except Exception:
        pass

    level = row.get("thinking_level")
    return {
        "user_id": row["user_id"], "key_id": row["id"], "name": row["name"],
        "thinking_level": level if level in valid_thinking_levels() else None,
    }
