import datetime
import httpx
from fastapi import Header, HTTPException, Depends, Request
from . import config, api_keys, rate_limit


def _extract_key(authorization: str | None, x_api_key: str | None) -> str:
    """Accepts either header convention, so neither SDK ecosystem needs
    special-casing to point at Quan:
    - Authorization: Bearer <key>   — OpenAI SDK / openai-compatible clients
    - x-api-key: <key>              — Anthropic SDK (ANTHROPIC_API_KEY)

    x-api-key wins if a caller somehow sends both, since it's already a
    bare key with nothing to parse out of it.
    """
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "message": "Missing API key. Use 'Authorization: Bearer <your-key>' or 'x-api-key: <your-key>'.",
                "type": "authentication_error",
                "param": None,
                "code": "missing_api_key",
            }
        },
    )


async def require_account_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict:
    """Gate for every product endpoint — the OpenAI-format routes (each model's
    /<model>/v1 prefix and generic /v1, both + /chat/completions and /responses) and the
    Anthropic-format routes (/<model>/v1/messages and /v1/messages, added
    2026-09-09 — see app/anthropic_api.py's module docstring). No /flash
    or /ultra product — both were removed (see the top-level README's
    removal notes / models/__init__.py's docstring).

    First thing this function does, before even parsing a key out of
    the headers: an IP-based throttle (rate_limit.
    enforce_unauthenticated_product_rate_limit(), added 2026-09-15) that
    runs regardless of whether the eventual key turns out to be valid.
    Added because api_keys.verify_api_key() makes a real Supabase REST
    call for any secret that merely starts with the right prefix
    (KEY_PREFIX, "sk-quan-" — a publicly documented convention, not a
    secret itself) whether or not it's actually a real key, and nothing
    upstream of that stopped unlimited such calls before this fix. A
    key, once verified, is additionally bounded by
    rate_limit.enforce_product_rate_limit() (per-user, called from
    two_pass_pipeline.run_pipeline() — see that module) — this earlier
    IP-based check exists specifically for the gap before an identity is
    even known, not as a replacement for the per-user limiting that
    already existed.

    This function's own x-api-key support (see _extract_key() above,
    "Anthropic SDK (ANTHROPIC_API_KEY)") predates the Anthropic-format
    routes above by weeks — it was already here, unused for its stated
    purpose, from before app/anthropic_proxy.py was deleted 2026-08-19.
    Not a coincidence and not new work: a real Anthropic SDK client
    pointed at /kael-beta/v1/messages authenticates correctly against this
    exact function with zero changes, because the auth layer never
    actually stopped anticipating it, only the route/format layer did.
    Accepts any active, non-revoked key
    generated from the dashboard's API
    Keys page — verified against Supabase, not a static env var. A key
    isn't tied to one product or one wire format; which product gets
    called is decided by which endpoint (or "model") the request uses.

    Returns {"user_id", "key_id", "name"} so the caller can attribute the
    request to an account for usage logging."""
    rate_limit.enforce_unauthenticated_product_rate_limit(request)
    key = _extract_key(authorization, x_api_key)
    requestor = await api_keys.verify_api_key(key)
    if requestor is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid or revoked API key. Generate one from the dashboard's API Keys page.",
                    "type": "authentication_error",
                    "param": None,
                    "code": "invalid_api_key",
                }
            },
        )
    return requestor


async def require_login(authorization: str | None = Header(default=None)) -> dict:
    """Gate for all /api/* dashboard endpoints (stats, keys, theme): requires
    a valid Supabase session (a logged-in dashboard user), not a product API
    key. Verifies the JWT by asking Supabase's own auth server whether it's
    still valid — no JWT secret needs to live in this codebase. Returns the
    full Supabase user object (id, email, user_metadata, ...)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Login required.", "type": "authentication_error", "code": "login_required"}},
        )
    token = authorization.split(" ", 1)[1].strip()

    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": "Server auth is not configured (missing SUPABASE_ANON_KEY).", "type": "server_error"}},
        )

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            f"{config.SUPABASE_URL}/auth/v1/user",
            headers={"apikey": config.SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Session expired or invalid — please log in again.", "type": "authentication_error", "code": "session_invalid"}},
        )
    user = resp.json()

    # Real-time suspension check (2026-08-23 admin work, see app/admin.py's
    # suspend_user). Supabase's own ban (banned_until) only blocks future
    # sign-in and token refresh — it does NOT retroactively invalidate an
    # access token already in the caller's hands; that stays valid until
    # its own expiry regardless of a ban set afterward (confirmed against
    # Supabase's own docs: "a temporary ban only blocks sign-in for its
    # duration and does not revoke existing sessions"). This function
    # already makes a live round-trip to GoTrue on every single call
    # (never a cached/local JWT decode), and GoTrue's /auth/v1/user
    # response already includes banned_until on the user object — so
    # checking it here costs nothing extra and is what actually makes
    # suspension immediate for every /api/* route on this account's very
    # next request, instead of "eventually, once their token happens to
    # expire."
    banned_until = user.get("banned_until")
    if banned_until:
        try:
            until = datetime.datetime.fromisoformat(banned_until.replace("Z", "+00:00"))
            if until > datetime.datetime.now(datetime.timezone.utc):
                raise HTTPException(
                    status_code=403,
                    detail={"error": {"message": "This account has been suspended.", "type": "authentication_error", "code": "account_suspended"}},
                )
        except ValueError:
            pass  # unparseable timestamp — fail open on the parse itself, not on a real ban
    return user


async def require_admin(user: dict = Depends(require_login)) -> dict:
    """Gate for every /api/admin/* route (app/admin.py) — wraps
    require_login (so a banned admin loses access exactly like anyone
    else, via the check above) and additionally requires
    app_metadata.role == "admin".

    Why app_metadata and not user_metadata: app_metadata lives on the
    auth.users row and is writable only with the service_role key (the
    GoTrue admin API, or direct SQL with that key) — never by anything a
    signed-in user's own session can reach. user_metadata, by contrast,
    is user-writable (see supabase_client.update_user_theme, which uses
    it deliberately for that reason) and would let anyone grant
    themselves admin — exactly the bug this replaces (AdminPage.tsx used
    to have a "Grant Admin Access" button that just set local React
    state, checked and enforced by nothing server-side).

    Bootstrap: nobody has this flag by default. The first admin account
    was set directly against the live Supabase project via:
        update auth.users
        set raw_app_meta_data = raw_app_meta_data || jsonb_build_object('role', 'admin')
        where email = '<the actual admin email — see internal ops notes, not source control>';
    — confirmed applied: that row's app_metadata is now
    {"role": "admin", "provider": "email", "providers": ["email"]}. To
    promote another account later, run the same UPDATE for its email (or
    build a one-off admin-only route for it if this becomes routine —
    deliberately not exposed over HTTP yet, since an admin-granting
    endpoint is real attack surface for very little day-to-day value at
    this scale — 2026-09-15 review: still true at current team size and
    traffic; revisit if promoting admins by hand stops being rare).
    2026-09-15: the real email address and the live Supabase project
    ref used to be spelled out verbatim right here. Scrubbed — this
    repo gets shared with contractors, and neither belongs in source
    control regardless of how low-stakes each individually seems; keep
    the actual values wherever internal ops/credentials already live.

    Rejects with a plain 403 (not 404) — no reason to hide that these
    routes exist, same as any other permission error in this app."""
    app_metadata = user.get("app_metadata") or {}
    if app_metadata.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": "Admin access required.", "type": "authentication_error", "code": "admin_required"}},
        )
    return user
