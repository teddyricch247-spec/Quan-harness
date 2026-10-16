"""In-memory rate limiting. Three independent sections:

1. The public, unauthenticated auth endpoints (/api/auth/signup,
   /api/auth/forgot-password) — added 2026-08-28. Keyed by BOTH the
   caller's IP (stops one attacker hammering the endpoint) and the
   target email (stops someone spreading requests across many IPs to
   bomb a single victim's inbox); either limit tripping blocks the
   request.

2. The billed product (Kael Beta inference) endpoints — added
   2026-09-13. Keyed by user_id instead of IP/email, and enforces both
   a requests-per-window limit and a concurrent-in-flight cap. See the
   "Product (billed inference) endpoints" section below for why this
   was missing before and what specifically the concurrency cap fixes
   that a window limit alone can't.

3. A pre-authentication IP throttle on those same product endpoints —
   added 2026-09-15. Keyed by IP only, and runs BEFORE the API key on
   the request is looked up at all, valid or not. This closes a
   different gap than #2: #2's per-user limits only start counting once
   a key has already been verified against Supabase — they do nothing
   for a request carrying an unverifiable or entirely made-up key, and
   every one of those still cost a real Supabase REST round-trip inside
   api_keys.verify_api_key() before this fix, since the only check
   there ahead of the database call is a cheap local prefix match
   (secret.startswith(KEY_PREFIX)), not actual validity. An attacker who
   knows the "sk-quan-" prefix convention (public, part of the product's
   own docs — not a secret), or a broken client stuck retry-looping on
   a bad key, could previously send unlimited such requests with no
   identity yet to rate-limit by. See "Pre-authentication IP throttle"
   below, called from auth.require_account_key() as the very first
   thing that function does.

Deliberately in-process memory, not Redis or any other shared store:
this app runs a single backend instance today, so every request already
lands on the one process, and a plain dict is enough — zero new
infrastructure, zero new cost. Two caveats worth knowing if the deploy
setup ever changes:
  - Counts reset on every restart/redeploy. Fine for abuse prevention
    (an attacker triggering a redeploy to reset their own limit isn't a
    realistic threat) — not fine if this were ever needed for anything
    requiring real persistence.
  - If this app ever runs as more than one process (multiple uvicorn
    workers, multiple instances behind a load balancer), each process
    keeps its own separate counters, so the effective limit becomes
    (configured limit) x (number of processes) for sections 1 and 3's
    window limits, and — worse, specifically for section 2's
    concurrency cap — the per-user in-flight count in _active_requests
    would no longer reflect reality at all, since a given user's
    concurrent requests could land on different processes that can't
    see each other's counts. At that point, both _buckets and
    _active_requests need a shared store (Redis, or even a Postgres
    table with a TTL sweep) — this module's interface
    (enforce_auth_rate_limit / enforce_product_rate_limit /
    enforce_unauthenticated_product_rate_limit) wouldn't need to change
    at the call site.
"""

import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request
from . import config

# key -> deque of unix timestamps (seconds) of recent requests, oldest first
_buckets: dict[str, deque] = defaultdict(deque)


def _hit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Records one request for `key` and returns True if it's within
    the limit, False if it should be rejected. Sliding window: drops
    timestamps older than `window_seconds` before counting, so it's a
    true "at most N in the last window_seconds", not a fixed-clock
    bucket that resets all at once."""
    now = time.time()
    bucket = _buckets[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= max_requests:
        return False
    bucket.append(now)
    return True


def client_ip(request: Request) -> str:
    """Best-effort caller IP. Behind a PaaS proxy (Render, Railway, Fly,
    etc.) request.client.host is the proxy's own address, not the real
    caller — the real IP shows up in X-Forwarded-For instead, so that's
    checked first; take its first entry (the original client, per the
    standard left-to-right convention). Falls back to
    request.client.host for local/direct connections (e.g. running the
    backend locally with no proxy in front)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def allow(key: str, max_requests: int, window_seconds: int) -> bool:
    """Public face of the sliding-window counter for callers outside this
    module (e.g. account_emails limiting how often one user can trigger a
    notice email). True while under the limit (and counts this call)."""
    return _hit(key, max_requests=max_requests, window_seconds=window_seconds)


def canonical_email_key(email: str) -> str:
    """The identity a MAILBOX has, for rate-limit keys only (the stored
    address is never changed). Gmail ignores dots and "+tags" in the local
    part and treats googlemail.com as gmail.com, so a.b@gmail.com,
    ab@gmail.com and ab+x@googlemail.com are one inbox; without this each
    variant got its own 3-per-15-minutes budget and one victim could be
    mailed far more often than intended. Other providers: "+tag" is
    collapsed (it is the same mailbox almost everywhere), dots are kept."""
    # Anything that is not a string (a JSON number, list, ...) has no mailbox
    # identity; give it the empty key instead of raising, so garbage input
    # reaches the validators and gets a 400 rather than a 500.
    value = email.strip().lower() if isinstance(email, str) else ""
    local, _, domain = value.partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def auth_email_budget_allows() -> bool:
    """Global circuit breaker on signup-confirmation / password-reset /
    security-notice emails: at most config.AUTH_EMAIL_HOURLY_CAP per rolling
    hour from this process, regardless of who asked. The per-IP and
    per-email limits above bound any ONE caller or ONE victim; this bounds
    the total, so the public endpoints cannot be used to mail hundreds of
    different addresses from the sending domain (spam complaints and
    bounces would damage its reputation, and it also carries the support
    mailbox). Returns True (and counts one email) while under the cap;
    False once it is reached. A cap of 0 or less disables the check."""
    cap = config.AUTH_EMAIL_HOURLY_CAP
    if cap <= 0:
        return True
    return _hit("auth-email:global", max_requests=cap, window_seconds=60 * 60)


def enforce_auth_rate_limit(request: Request, email: str | None, scope: str) -> None:
    """Raises HTTPException(429) if either the caller's IP or the
    target email has made too many requests to this `scope` recently.
    Call this first, before any real work, in each route handler.

    Limits are deliberately different for IP vs. email: 10 requests /
    15 min per IP is generous enough that a real user fumbling their
    password a few times never hits it, while 3 requests / 15 min per
    email is tight enough to blunt an email-bombing attempt even if
    it's spread across many IPs."""
    ip = client_ip(request)
    if not _hit(f"{scope}:ip:{ip}", max_requests=10, window_seconds=15 * 60):
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "Too many requests. Please try again in a few minutes.", "type": "rate_limit_error"}},
        )
    if email:
        normalized = canonical_email_key(email)
        if not _hit(f"{scope}:email:{normalized}", max_requests=3, window_seconds=15 * 60):
            raise HTTPException(
                status_code=429,
                detail={"error": {"message": "Too many requests for this email. Please try again in a few minutes.", "type": "rate_limit_error"}},
            )


# ============================================================
# Product (billed inference) endpoints — added 2026-09-13
# ============================================================
# Until now, each model's /<model>/v1/chat/completions, /responses and /messages routes,
# and the generic /v1/* routers that resolve to them had NO throttling at
# all — the only gate was billing.check_balance_or_raise(), which (by its
# own docstring) only blocks a user who is ALREADY at $0, and isn't atomic
# with the deduction that happens after the call completes. That leaves
# two separate problems this module's existing per-scope design doesn't
# already solve:
#
# 1. Slow-paced abuse: a user with real balance scripting requests well
#    under any obviously-suspicious rate, running up upstream cost that's
#    theirs to spend but still worth bounding — same reasoning as the
#    auth-endpoint limits above, just for a different resource.
# 2. The balance-race itself: check_balance_or_raise() is a plain read.
#    N concurrent requests fired at the moment an account still has ANY
#    positive balance all pass that read before any of them reach
#    charge_for_request()'s deduction — each individual charge is atomic
#    (a single Postgres UPDATE...RETURNING, see billing.charge_for_
#    request()'s docstring), but nothing stops all N from being allowed
#    to START. A requests-per-window limit alone doesn't fix this: it
#    caps requests over TIME, not requests IN FLIGHT AT ONCE, and a
#    single Kael Beta request can legitimately occupy the pipeline for
#    minutes (GENERATION_HARD_CEILING_SECONDS in two_pass_pipeline.py is
#    480s PER PASS). A concurrency cap is the actual fix for this
#    specific problem — it bounds how many requests can be simultaneously
#    past the balance check and not yet billed, which bounds how far
#    negative one burst can drive an account, regardless of window size.
#
# Both below key by user_id, not IP/API-key — the paid product's identity
# that actually owns the balance being protected; call sites already have
# it as `requestor["user_id"]` (see two_pass_pipeline.run_pipeline(), the
# one choke point every caller_shape funnels through, which is where
# these get called from — see that module for the actual call sites).
#
# Owner-set numbers as of 2026-10-03: 150 requests / 60s per user and 30
# in flight per user (earlier starting numbers were 30 / 60s and 3; the
# prose below describes that first reasoning and its overdraft math scales
# with the cap: up to 30 requests can now pass the balance check at once).
# Original note: 30 requests / 60s per user (roughly
# one every 2 seconds sustained — generous enough for the "not always a
# human" agentic/coding-tool use case system_identity itself describes,
# tight enough to blunt a scripted balance-drain attempt) and a
# concurrency cap of 3 in-flight requests per user (small enough to bound
# the balance-race's worst case to a handful of requests' worth of
# overdraft rather than unbounded, generous enough that a legitimate
# agent firing off a couple of parallel calls — e.g. one per file in a
# multi-file edit — doesn't get throttled for normal use). Revisit both
# against real traffic once there's production data to tune on; these
# exist to put a ceiling in place before launch, not to be the final
# word. A third, GLOBAL concurrency cap across all users (independent of
# any one account) is also worth adding once there's a real number for
# how many concurrent 480s-capable upstream calls this single backend
# instance can hold open without degrading everyone's latency — that
# number depends on actual load testing (memory per open httpx stream,
# event-loop responsiveness under load), not something to guess at here.
PRODUCT_RATE_MAX_REQUESTS = 150  # owner decision 2026-10-03: 150 requests/minute per user
PRODUCT_RATE_WINDOW_SECONDS = 60
PRODUCT_MAX_CONCURRENT_PER_USER = 30  # owner decision 2026-10-03: 30 in flight per user

# user_id -> count of requests currently past the rate/concurrency gate
# and not yet finished. Same in-memory, single-instance caveat as
# _buckets above (see module docstring) — move to a shared store first if
# this app ever runs more than one process.
_active_requests: dict[str, int] = defaultdict(int)


def enforce_product_rate_limit(user_id: str) -> None:
    """Raises HTTPException(429) if `user_id` has either made too many
    product requests recently, or already has too many in flight right
    now. Call this once per request, from run_pipeline() (see module
    docstring above for why that single choke point is the right call
    site), AFTER check_balance_or_raise() (no point rate-limiting a
    request that was going to get a 402 anyway) and BEFORE
    start_product_request() below."""
    if not _hit(f"product:user:{user_id}", max_requests=PRODUCT_RATE_MAX_REQUESTS, window_seconds=PRODUCT_RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "Too many requests. Please slow down and try again shortly.", "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
        )
    if _active_requests[user_id] >= PRODUCT_MAX_CONCURRENT_PER_USER:
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": f"Too many requests in progress at once (max {PRODUCT_MAX_CONCURRENT_PER_USER}). Wait for one to finish before starting another.", "type": "rate_limit_error", "code": "concurrency_limit_exceeded"}},
        )


def start_product_request(user_id: str) -> None:
    """Marks one request as in-flight for `user_id` — call immediately
    after enforce_product_rate_limit() passes, so the window between
    'allowed to start' and 'actually counted' stays as small as
    possible. Always pair with end_product_request() in a finally block;
    an uncounted-down request would leak a permanent slot."""
    _active_requests[user_id] += 1


def end_product_request(user_id: str) -> None:
    """Releases one in-flight slot for `user_id`. Safe to call even if
    start_product_request() was never called for this user (floors at
    0) — cheaper than requiring every call site to track whether it
    actually incremented, and a request that never started was never
    occupying a slot regardless."""
    if user_id in _active_requests:
        _active_requests[user_id] = max(0, _active_requests[user_id] - 1)


# ============================================================
# Voice typing (added 2026-10-14)
# ============================================================
# One call here is one short recording sent for transcription
# (app/transcription.py). Quancis pays for it (about a tenth of a cent for a
# clip of a minute), so it is bounded per signed-in user on its own, apart from
# the chat limits above. A person dictating message after message sends one clip
# every 10-20 seconds at most; 20 in 10 minutes is above that and far below
# anything abusive. A reasoned starting number, not load-tested. Same
# in-memory, single-instance caveat as everything in this file.
TRANSCRIBE_RATE_MAX_REQUESTS = 20
TRANSCRIBE_RATE_WINDOW_SECONDS = 600


def enforce_transcribe_rate_limit(user_id: str) -> None:
    """Raises HTTPException(429) if `user_id` has sent too many recordings for
    transcription recently."""
    if not _hit(f"transcribe:user:{user_id}", max_requests=TRANSCRIBE_RATE_MAX_REQUESTS, window_seconds=TRANSCRIBE_RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "That's a lot of recordings in a short time. Please wait a few minutes, or type your message.", "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
        )


# ============================================================
# Pre-authentication IP throttle for product endpoints — added
# 2026-09-15. See the module docstring's section 3 above for the full
# "why" (the gap this closes that section 2 above doesn't: an
# unverified/garbage key never reaches a user_id to key by, but still
# cost a real Supabase round-trip inside api_keys.verify_api_key()
# before this fix).
# ============================================================
# Deliberately generous relative to PRODUCT_RATE_MAX_REQUESTS above:
# this gate fires before a key is verified, so — unlike section 2's
# limits — it can't yet tell one legitimate high-volume account (which
# is already bounded to PRODUCT_RATE_MAX_REQUESTS per
# PRODUCT_RATE_WINDOW_SECONDS once authenticated) apart from several
# unrelated legitimate callers who simply happen to share one apparent
# IP — a corporate NAT, a shared outbound proxy, or a customer's own
# backend fanning many of their own end users' calls through one
# Quancis account. Set high enough that no single real account should
# ever be able to trip this on its own even running at its full
# authenticated rate, while still bounding a key-guessing or
# retry-looping flood to a fixed, non-infinite number of Supabase
# round-trips per minute rather than an unbounded one. Like
# PRODUCT_RATE_MAX_REQUESTS above, this is a reasoned starting number,
# not load-tested — revisit once there's real traffic data (see item 6
# of the 2026-09-15 audit notes).
UNAUTH_PRODUCT_RATE_MAX_REQUESTS = 300
UNAUTH_PRODUCT_RATE_WINDOW_SECONDS = 60


def enforce_unauthenticated_product_rate_limit(request: Request) -> None:
    """Raises HTTPException(429) if this IP (client_ip(request) — real
    caller via X-Forwarded-For when behind a proxy, same helper section
    1 above already uses) has made too many requests to a product
    endpoint recently. Checked before the API key on the request is
    looked up at all, so it throttles identically whether that key
    turns out to be valid, revoked, or entirely made up.

    Call this first thing in auth.require_account_key() — before
    _extract_key(), before api_keys.verify_api_key(). Not a replacement
    for enforce_product_rate_limit() above: that one still runs later,
    per-user, once a key is actually verified; this one exists
    specifically for the request that arrives before any identity is
    known yet."""
    ip = client_ip(request)
    if not _hit(f"unauth-product:ip:{ip}", max_requests=UNAUTH_PRODUCT_RATE_MAX_REQUESTS, window_seconds=UNAUTH_PRODUCT_RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "Too many requests from this network. Please try again shortly.", "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
        )
