"""
Billing — balance tracking and per-request metering.

Only products in config.BILLED_PRODUCTS touch any of this — as of
Aura Beta's removal (2026-09-08) that was just Kael Beta. Kael Pro Beta joined it on 2026-10-08, each at its
own price (Aura Beta, "ultra", billed alongside Kael Beta from 2026-08-19
until its removal; see backend/HISTORY.md). Membership is
derived automatically in config.py from whether a product's
customer_price_per_million is set, not a separate flag to keep in sync
by hand — see that module. Everything here is keyed by product on
purpose, so a future second product needs only a real
customer_price_per_million in its own config.py to start billing, no
edit here.

=== How a request is billed (read this before touching the math) ===

Every request to a billed product makes 1 or 2 upstream calls — see
app/two_pass_pipeline.py's shared draft-then-critic flow (app/critic/,
README.md), which app/kael_pipeline.py runs on. A "first" (draft) call
always happens; a "last" (critic) call happens too, *unless* the critic
pass didn't run at all (an entirely empty/filtered draft — the only
remaining skip condition as of 2026-08-20, see
app/two_pass_pipeline.py's module docstring — or the critic call itself
failed) — in which case the draft is both the first call and the last
call.

The rule:
  - Billed INPUT tokens  = the FIRST call's prompt_tokens.
  - Billed OUTPUT tokens = the LAST call's completion_tokens (the critic
    call's, if one happened — otherwise the draft's).

Why: the critic pass is an internal quality step this API adds on its
own initiative, not something the caller asked for. Its prompt is
(the caller's original messages) + (one appended system message) — i.e.
almost the exact same input as the first call — so billing its input
tokens too would charge the user twice for their own conversation. Its
*output*, though, is exactly what gets returned to the caller, so that
half is real usage and belongs on the bill. Net effect: the user is
billed roughly what a single well-behaved pass would have cost them.
The gap between that and what this API actually pays DeepSeek — both
calls, in full — is the cost of running the self-review step, and it's
absorbed by the company, not the user. (Contrast with
supabase_client.log_usage, which still sums both calls' full usage —
that's the real internal cost figure the dashboard's "estimated cost"
is built from, a different number for a different audience.)

**Adding a new billed model?** Apply this same first-call-input /
last-call-output rule to it too — it's a property of the two-pass
request shape, not of which upstream model is involved. Don't
special-case a new model's math; give it a real customer_price_per_million
in its own models/*/config.py (which puts it in config.BILLED_PRODUCTS
automatically) and it inherits this for free via calculate_cost().

=== Cache-hit input tokens ===

DeepSeek reports `prompt_cache_hit_tokens` on every call's `usage` object
— this is a real, reliable field. As of 2026-08-20 this app normalizes it
from the Responses API's `input_tokens_details.cached_tokens` field via
app/response_api.py:usage_from_responses()/client_usage() before it ever
reaches this module — see log_usage's call sites in
app/two_pass_pipeline.py — so it's still the same reliable number, just
read off a differently-shaped upstream payload than before. Two different
totals use it, for two different audiences:

  - Internal accounting (supabase_client.log_usage) sums cache-hit
    tokens from BOTH calls — that's our real, total cost savings as a
    company. The critic call in particular is nearly one giant cache hit
    by construction (its prompt is the first call's prompt plus one
    appended message), and that saving is the payoff for eating the
    critic call's cost in the first place. It's ours to keep.
  - Billing (this module) only ever looks at the FIRST call's cache-hit
    tokens — consistent with "billed input = first call's input" above.
    The critic call's massive cache hit never enters this calculation at
    all, by construction, since the critic call's usage is only ever
    used here for its completion_tokens.

For the portion of billed input tokens that were a cache hit on that
first call, CACHE_DISCOUNT_PCT (80%) comes off the normal per-token
input price — the user pays 20% of the normal input rate on those
tokens, not full price. That's a genuine discount, but it is NOT the
same as passing through customer_price_per_million["standard"]["cached_input"]
(what a product's own config.py sets as the customer-facing cache rate —
see models/kael/config.py). The gap
between the 20%-of-input rate charged here and whatever number sits in
that config field is margin, same idea as the critic call's savings
above. That config field is read elsewhere (supabase_client.py, for the
account's own estimated-cost figure) but never read by this module —
this module always derives the cache rate as 20% of the input rate, full
stop.

If a future upstream provider doesn't report a reliable cache-hit
number, that's the one thing to special-case around inside
calculate_cost() — leave the discount out of the total rather than
estimate it, don't touch the input/output call-selection rule above to
work around it.

=== Pricing is flat, as of 2026-08-19 ===

Kael Beta bills at one flat rate regardless of time of day, set in
models/kael/config.py under customer_price_per_million["standard"]. The
earlier peak/off-peak split (a separate peak_pricing_per_million rate
card, active during specific UTC hours) was retired along with it —
there is no "peak" tier anymore, and calculate_cost() below always reads
the "standard" tier unconditionally. The `at` parameter threaded through
calculate_cost/charge_for_request still exists for now (harmless —
nothing currently branches on it) but carries no pricing meaning; if
peak pricing is ever reintroduced, restore a real peak lookup here
rather than assuming `at` already does something.

Current price: $3.00 in / $10.00 out / $0.60 cached-in per 1M tokens
(repriced 2026-10-08, owner decision, from $2.00 / $6.00 / $0.40: aim for
roughly 80% gross margin and compete on reliability rather than on being
the cheapest. Cached-in is still exactly 20% of input. Before that,
2026-09-28 raised output $4.00 -> $6.00; 2026-09-21 repriced from
$1.00 / $3.00 / $0.20, which itself replaced $1.50 / $4.00 / $0.15 on
2026-09-01. Billed output is only the final answer's tokens while the
draft pass, the review pass and the thinking-title calls are not billed,
so real cost per billed token is a multiple of the model's list rate; do
not read the price as a markup over one model's rate). The numbers live in
models/kael/config.py, not here; see
its customer_price_per_million comment for the full reasoning, including
why cached_input is deliberately set to exactly 20% of the input rate
(matching CACHE_DISCOUNT_PCT below) rather than an independently-chosen
number.

(Aura Beta, while it existed, repriced separately from Kael Beta
at this same point — "flat rate" above meant "flat across time of day,
per product," not "one number for every product" — but that's history
now; see the top-level README's removal note.)
"""

import httpx
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from . import config

# Users pay 20% of the normal input rate on cache-hit tokens (i.e. an 80%
# discount off that rate) — see the module docstring's "Cache-hit input
# tokens" section for why this isn't the same as
# customer_price_per_million["standard"]["cached_input"].
CACHE_DISCOUNT_PCT = Decimal("0.80")

# New accounts start here. As of 2026-09-02 that's $0 — there is no more
# free signup credit; the only way a real balance now enters the system is
# a real deposit (currently recorded by an admin via admin_credit_account
# below, until a real payment webhook exists — see main.py:get_billing's
# docstring). Keep in sync with the `balance_usd` column default in
# supabase/migrations/*.sql — this constant is what actually gets
# written (see _create_account); the column default only matters if a
# row is ever inserted some other way. (This WAS out of sync with the
# original 0004_billing.sql default of 5.00000 until
# 0008_balance_default_sync.sql corrected the column default to match,
# 2026-09-15 — see that migration's comment for the full history; it
# was not yet applied to the live project as of writing it, so confirm
# it's actually been run before trusting the two are in sync in
# practice, not just on paper.)
DEFAULT_STARTING_BALANCE = Decimal("0.00000")

# 5 decimal places, matching billing_accounts.balance_usd's numeric(14,5).
_QUANT = Decimal("0.00001")


def format_usd(amount: Decimal) -> str:
    """'-$0.00012', not '$-0.00012' — Python's :.5f format spec puts the
    sign before the number, which lands between the '$' and the digits if
    you naively write f"${amount:.5f}". Balances CAN go slightly negative
    by design (see check_balance_or_raise's docstring), so this isn't a
    hypothetical: use this instead of hand-rolled f-string formatting
    anywhere a Decimal dollar amount reaches a human."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):.5f}"


def _quantize(amount: Decimal) -> Decimal:
    """Round to 5 decimal places using ordinary half-up rounding — this
    number eventually gets read by a human on the billing dashboard, and
    banker's rounding there would just be a confusing surprise."""
    return amount.quantize(_QUANT, rounding=ROUND_HALF_UP)


class InsufficientBalanceError(Exception):
    """Account balance is at or below $0. Raised by check_balance_or_raise,
    caught in app/two_pass_pipeline.py:run_pipeline() and turned into an
    HTTP 402 — a plain exception (not an HTTPException) so this module
    doesn't need a FastAPI import just to signal this."""

    def __init__(self, balance: Decimal):
        self.balance = balance
        super().__init__(f"balance is {balance}")


class BillingUnavailableError(Exception):
    """The billing account couldn't be read or created at all (Supabase
    unreachable, misconfigured, row-creation failed, etc). Deliberately
    NOT the same as InsufficientBalanceError — app/two_pass_pipeline.py's
    run_pipeline() turns this into a
    500, not a 402, so a billing-service hiccup doesn't look like "you're
    out of money" to the caller.

    This is also the one place in this module that fails CLOSED (blocks
    the request) rather than open. supabase_client.log_usage and this
    module's own charge_for_request both fail open — a write failure
    there just means one request goes unlogged/unbilled, which is a far
    smaller problem than a billing hiccup taking down real traffic. But
    check_balance_or_raise is the actual spend gate, not a bookkeeping
    side effect, so silently letting every request through when it can't
    even read the balance would defeat the point of having it."""

    pass


def _headers(extra: dict | None = None) -> dict:
    """Bug fix (2026-08-16): this used to take zero parameters while
    _create_account called it as _headers({"Prefer": "return=representation"})
    — a TypeError on every single first-time account creation, i.e. every
    brand-new user's very first billed request or first visit to the
    Billing page. Every other call site here calls _headers() with no
    arguments, which still works unchanged with extra defaulting to None."""
    headers = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)


async def _fetch_account(user_id: str) -> dict | None:
    params = {"select": "user_id,balance_usd", "user_id": f"eq.{user_id}", "limit": "1"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_accounts", headers=_headers(), params=params)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def _create_account(user_id: str) -> dict:
    """Sent as a JSON number, not a string — PostgREST maps a bare JSON
    number cleanly onto a numeric column; a JSON string relies on an
    implicit text->numeric cast that isn't guaranteed. float() is exact
    enough here since DEFAULT_STARTING_BALANCE only ever has 5 decimal
    places and float64 comfortably represents that without drift."""
    row = {"user_id": user_id, "balance_usd": float(DEFAULT_STARTING_BALANCE)}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/rest/v1/billing_accounts",
            headers=_headers({"Prefer": "return=representation"}),
            json=row,
        )
    if resp.status_code == 409:
        # Lost a race to a concurrent first-request for the same brand-new
        # user — someone else's insert already won. Read what's there
        # instead of treating this as a failure.
        existing = await _fetch_account(user_id)
        if existing is not None:
            return existing
    resp.raise_for_status()
    return resp.json()[0]


async def ensure_account(user_id: str) -> Decimal:
    """Returns the account's current balance, creating it at
    DEFAULT_STARTING_BALANCE first if this is the user's first request
    against a billed product (or their first visit to the billing page)."""
    if not _enabled():
        raise BillingUnavailableError("Supabase is not configured")
    try:
        account = await _fetch_account(user_id)
        if account is None:
            account = await _create_account(user_id)
        return Decimal(str(account["balance_usd"]))
    except BillingUnavailableError:
        raise
    except Exception as e:
        raise BillingUnavailableError(str(e)) from e


async def check_balance_or_raise(user_id: str) -> Decimal:
    """The pre-call gate. app/two_pass_pipeline.py:run_pipeline() calls
    this before making ANY upstream call for a billed product — raises
    InsufficientBalanceError if the account is at or below $0, which
    run_pipeline() turns into a 402 before a single DeepSeek/OpenAI token
    is spent. This is what actually blocks further calls once the balance
    runs out; the deduction in charge_for_request happens afterward,
    against real usage, and isn't itself a blocker — see that function's
    docstring for why it can't be."""
    balance = await ensure_account(user_id)
    if balance <= Decimal("0"):
        raise InsufficientBalanceError(balance)
    return balance


def _select_billed_usage(first_call_usage: dict, last_call_usage: dict | None) -> dict:
    """First-call input, last-call output — see the module docstring.
    `last_call_usage=None` means the critic pass never ran, so the draft
    is both the first AND last call and its own completion_tokens is
    what's billable."""
    output_usage = last_call_usage if last_call_usage is not None else first_call_usage
    prompt_tokens = first_call_usage.get("prompt_tokens", 0) or 0
    cached_tokens = first_call_usage.get("prompt_cache_hit_tokens", 0) or 0
    completion_tokens = output_usage.get("completion_tokens", 0) or 0
    # Cached tokens are a subset of prompt tokens, never additional on top
    # of them — clamp defensively in case an upstream response is ever
    # internally inconsistent.
    cached_tokens = min(cached_tokens, prompt_tokens)
    return {
        "billed_prompt_tokens": prompt_tokens,
        "billed_cached_tokens": cached_tokens,
        "billed_completion_tokens": completion_tokens,
    }


def calculate_cost(
    product: str, first_call_usage: dict, last_call_usage: dict | None, at: datetime | None = None
) -> dict:
    """Pure calculation, no I/O — kept separate from charge_for_request so
    it's independently testable and so a future caller (e.g. a "preview
    this request's cost" endpoint) can reuse it without writing anything.
    Returns the billed token breakdown alongside cost_usd so ledger rows
    and logging don't have to recompute any of it from scratch.

    `at` is accepted for call-site compatibility with
    app/two_pass_pipeline.py (which passes the request's start time) but is
    currently unused — pricing is flat as of 2026-08-19, see the module
    docstring's "Pricing is flat" section. Kept as a parameter rather than
    removed so reintroducing time-based pricing later doesn't require
    touching every call site again."""
    billed = _select_billed_usage(first_call_usage, last_call_usage)
    product_config = config.PRODUCTS[product]
    pricing = product_config["customer_price_per_million"]["standard"]

    uncached = max(billed["billed_prompt_tokens"] - billed["billed_cached_tokens"], 0)
    cached = billed["billed_cached_tokens"]
    completion = billed["billed_completion_tokens"]

    million = Decimal(1_000_000)
    # str() first, not Decimal(float) directly — floats like 0.14 don't
    # have an exact binary representation, and Decimal(0.14) would carry
    # that binary noise forward. Decimal(str(0.14)) == Decimal("0.14") exactly.
    input_rate = Decimal(str(pricing["input"]))
    output_rate = Decimal(str(pricing["output"]))
    cached_rate = input_rate * (Decimal("1") - CACHE_DISCOUNT_PCT)  # 20% of normal input rate

    cost = (
        Decimal(uncached) / million * input_rate
        + Decimal(cached) / million * cached_rate
        + Decimal(completion) / million * output_rate
    )
    return {**billed, "cost_usd": _quantize(cost)}


async def charge_for_request(
    user_id: str,
    product: str,
    first_call_usage: dict,
    last_call_usage: dict | None,
    at: datetime | None = None,
) -> dict | None:
    """Deducts the cost of one request from the account, atomically, via
    the deduct_balance Postgres function (supabase/migrations/0004_billing.sql)
    — a single UPDATE ... RETURNING server-side, so two concurrent
    requests on the same account can't both read a stale balance and both
    think they can afford their own charge (the lost-update race a plain
    Python read-then-write can't avoid on its own).

    `at` is accepted for call-site compatibility — see calculate_cost's
    docstring; it's currently unused since pricing is flat.

    Fire-and-forget, same as supabase_client.log_usage: a write failure
    here means one request goes unbilled, which is a much smaller problem
    than a billing outage taking down real traffic. This is deliberately
    more lenient than check_balance_or_raise (the pre-call gate), which
    fails closed — see BillingUnavailableError's docstring for why the
    two functions make opposite tradeoffs.

    Can't itself block a call already in flight — by the time this runs,
    the upstream call has already happened and DeepSeek/OpenAI has already
    been paid for it, so there's nothing left to gate. Enforcement is
    entirely check_balance_or_raise's job, on the *next* request.

    Returns the calculated breakdown (incl. cost_usd) on success, or None
    if the write failed (nothing meaningful to hand back)."""
    if not _enabled():
        return None
    calc = calculate_cost(product, first_call_usage, last_call_usage, at=at)
    if calc["cost_usd"] <= 0:
        return calc  # nothing to charge — e.g. a fully-cached, empty-output edge case
    body = {
        "p_user_id": user_id,
        # Same reasoning as _create_account: JSON number, not a JSON
        # string, for a numeric RPC parameter.
        "p_amount": float(calc["cost_usd"]),
        "p_product": product,
        "p_billed_prompt_tokens": calc["billed_prompt_tokens"],
        "p_billed_cached_tokens": calc["billed_cached_tokens"],
        "p_billed_completion_tokens": calc["billed_completion_tokens"],
        "p_description": f"{config.PRODUCTS[product]['label']} request",
        # p_is_peak omitted — defaults to false in deduct_balance() (see
        # 0004_billing.sql). Pricing is flat as of 2026-08-19; every ledger
        # row is correctly "not peak" now, there's no time-based rate left
        # to flag.
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.SUPABASE_URL}/rest/v1/rpc/deduct_balance",
                headers=_headers(),
                json=body,
            )
        resp.raise_for_status()
        # deduct_balance returns the NEW balance (see 0004_billing.sql). Hand
        # it to the balance-email check: previous = new + this request's
        # cost, so "crossed the line" is exact. Pure side effect: scheduled
        # as a background task, own try/except, so it can never delay or fail
        # a charge (and a problem in it must not be reported as CHARGE_FAILED).
        try:
            from . import balance_alerts

            new_balance = Decimal(str(resp.json()))
            balance_alerts.schedule(user_id, new_balance + calc["cost_usd"], new_balance)
        except Exception:  # noqa: BLE001
            pass
        return calc
    except Exception as e:
        # Still fails open (the reply was already served), but no longer
        # silently (changed 2026-10-06). A failed deduction changes neither
        # the balance nor the ledger, so reconcile_billing cannot see it —
        # this line is the ONLY trace that a served request went unbilled.
        # Grep the logs for CHARGE_FAILED. Contains no request content.
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(
            f"[billing] CHARGE_FAILED user={user_id} product={product} "
            f"amount_usd={calc['cost_usd']} error={type(e).__name__} http_status={status}"
        )
        return None


async def _credit_ledger_row(user_id: str, amount_usd: Decimal, description: str) -> Decimal:
    """One deposit-kind ledger entry via the credit_balance Postgres
    function (supabase/migrations/0004_billing.sql) — same atomic
    single-UPDATE-plus-INSERT pattern as deduct_balance, just adding
    instead of subtracting. Returns the resulting balance. Shared by
    admin_credit_account below, which calls it once per credit."""
    body = {
        "p_user_id": user_id,
        "p_amount": float(_quantize(amount_usd)),
        "p_description": description,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{config.SUPABASE_URL}/rest/v1/rpc/credit_balance",
            headers=_headers(),
            json=body,
        )
    resp.raise_for_status()
    return Decimal(str(resp.json()))


async def admin_credit_account(user_id: str, amount_usd: Decimal, description: str) -> Decimal:
    """Adds credits to an account's balance — the whole point of
    POST /api/admin/users/{user_id}/credit (app/admin.py). This is
    deliberately the only caller of the credit_balance RPC (see
    _credit_ledger_row): credit_balance itself has no payment
    verification of its own (see its docstring in the migration —
    "don't expose this over an authenticated-user-facing endpoint
    without a real payment verification step in front of it"), and
    require_admin (app/auth.py) IS that verification step here, the same
    way it would be for a real payment-webhook handler. Right now this
    IS how a deposit gets recorded, full stop — there's no payment
    webhook yet (see main.py:get_billing's docstring), so an admin
    entering an amount here after a user actually pays is standing in
    for one.

    One ledger row (kind 'deposit') per call. The deposit-match promotion that
    used to add a second, bonus row ended on 2026-09-08 and its code was removed
    on 2026-10-13 (backend/HISTORY.md); ledger rows it wrote stay as history.
    `description` must not contain personal data of the admin or the customer:
    customers can read it back through GET /api/billing (see admin.credit_user).

    Credits expire 12 months after the ledger row that added them: see
    app/credit_expiry.py. Nothing needs doing here for that.

    Calls ensure_account first — credit_balance's
    `update ... where user_id = ...` is a silent no-op turned into a
    raised exception if the row doesn't exist yet (see its `if
    v_new_balance is null` check), which would otherwise make crediting
    a brand-new user who's never made a request fail for a confusing
    reason."""
    if not _enabled():
        raise BillingUnavailableError("Supabase is not configured")
    await ensure_account(user_id)
    return await _credit_ledger_row(user_id, amount_usd, description)


async def admin_all_balances() -> dict[str, Decimal]:
    """{user_id: balance_usd} for every billing_accounts row that
    exists. Not every signed-up user has one yet — ensure_account only
    creates it lazily, on that user's first billed request or first
    visit to the Billing page — so an account with no row simply isn't a
    key in this dict; see app/admin.py's get_users() for how that's
    represented (None/null) rather than fabricated as the starting
    balance (currently $0 — see DEFAULT_STARTING_BALANCE) a not-yet-created
    account would eventually get."""
    if not _enabled():
        return {}
    params = {"select": "user_id,balance_usd"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_accounts", headers=_headers(), params=params)
    resp.raise_for_status()
    return {r["user_id"]: Decimal(str(r["balance_usd"])) for r in resp.json()}


# =======================================================================
# Reconciliation — added 2026-09-15. See app/jobs/README.md's "Candidate
# jobs" section (this is what that entry describes) and app/jobs/
# reconcile_billing.py (the thin script that actually calls this).
#
# Deliberately does NOT reuse supabase_client.admin_all_balances() or
# admin_spend_by_user() even though both already query these same two
# tables — both were built for the admin dashboard, where "recent,
# fast, good enough for a trend number" is the right tradeoff:
# admin_spend_by_user() filters to kind='usage' only (deposits/admin
# credits don't count as "spend" for that widget, correctly) and both
# cap at ADMIN_AGGREGATE_ROW_CAP (50,000) most-recent rows with no
# pagination beyond that. For reconciliation specifically, both of
# those choices would make the result actively WRONG instead of just
# approximate: a real drift-detector needs every ledger row (every
# kind — a missed or double-applied admin_credit_account() deposit is
# exactly the kind of thing this exists to catch, not just usage
# charges) and needs it exhaustively, not capped, since silently
# ignoring a user's older rows once they cross the cap would make a
# genuinely drifted account look clean. Built as its own paginated
# fetch below instead of threading a "no really, ALL of them, and ALL
# kinds" flag through the existing dashboard helpers and hoping every
# future caller of those helpers gets the flag's default right.
# =======================================================================

# PostgREST's own implicit default (commonly 1000, project-configurable
# via db-max-rows) applies to ANY query with no explicit `limit` —
# including supabase_client.admin_all_balances(), which has no `limit`
# param at all. That's a real, separate, pre-existing gap (not
# introduced here, not fixed here — admin_all_balances() serves the
# admin dashboard's user list, a different concern from this file's),
# but it means this reconciliation deliberately does NOT call that
# function either, for the same reason it doesn't call
# admin_spend_by_user(): an unbounded, explicitly-paginated fetch,
# built once here, is correct regardless of what either dashboard
# helper does or doesn't fix separately.
_RECONCILE_PAGE_SIZE = 1000


async def _fetch_all_accounts_paginated() -> dict[str, Decimal]:
    """{user_id: balance_usd}, EVERY billing_accounts row, explicitly
    paginated — see this section's own header comment for why this
    doesn't reuse supabase_client.admin_all_balances() despite querying
    the same table."""
    if not _enabled():
        return {}
    accounts: dict[str, Decimal] = {}
    offset = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "select": "user_id,balance_usd",
                "order": "user_id.asc",
                "limit": str(_RECONCILE_PAGE_SIZE),
                "offset": str(offset),
            }
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_accounts", headers=_headers(), params=params)
            resp.raise_for_status()
            rows = resp.json()
            for row in rows:
                accounts[row["user_id"]] = Decimal(str(row["balance_usd"]))
            if len(rows) < _RECONCILE_PAGE_SIZE:
                break
            offset += _RECONCILE_PAGE_SIZE
    return accounts


async def _fetch_all_ledger_sums_paginated() -> dict[str, Decimal]:
    """{user_id: sum(amount_usd)}, EVERY billing_ledger row, every
    `kind` (usage charges stored negative, deposits/admin credits
    stored positive — see supabase/migrations/0004_billing.sql's
    deduct_balance()/credit_balance() — so a plain sum already nets
    them correctly, no sign-flipping needed here the way
    supabase_client.admin_revenue_since() has to for its own,
    usage-only, display purposes). Explicitly paginated — see this
    section's own header comment for why."""
    if not _enabled():
        return {}
    totals: dict[str, Decimal] = {}
    offset = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "select": "user_id,amount_usd",
                "order": "user_id.asc,created_at.asc",
                "limit": str(_RECONCILE_PAGE_SIZE),
                "offset": str(offset),
            }
            resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_ledger", headers=_headers(), params=params)
            resp.raise_for_status()
            rows = resp.json()
            for row in rows:
                uid = row.get("user_id")
                if not uid:
                    continue
                amt = Decimal(str(row.get("amount_usd") or 0))
                totals[uid] = totals.get(uid, Decimal("0")) + amt
            if len(rows) < _RECONCILE_PAGE_SIZE:
                break
            offset += _RECONCILE_PAGE_SIZE
    return totals


@dataclass
class AccountDrift:
    """One billing_accounts row whose actual balance_usd didn't match
    what its own billing_ledger history says it should be. `drift` is
    actual - expected: positive means the account has MORE than its
    ledger accounts for (e.g. a manual SQL edit, or a credit that
    bypassed credit_balance()); negative means it has LESS (e.g. the
    balance-race a concurrent-request burst could cause — see
    check_balance_or_raise()'s own docstring — or a charge that
    bypassed deduct_balance())."""
    user_id: str
    expected_balance: Decimal
    actual_balance: Decimal
    drift: Decimal


async def reconcile_all_accounts() -> list[AccountDrift]:
    """The actual check: for every billing_accounts row, does
    balance_usd equal DEFAULT_STARTING_BALANCE + sum(that user's
    billing_ledger.amount_usd)? DEFAULT_STARTING_BALANCE has to be
    added back in, not just the ledger sum on its own — see that
    constant's own comment: _create_account() writes balance_usd
    directly at account-creation time, with NO corresponding ledger
    row, so the starting balance is real money (or, today, real $0 —
    see DEFAULT_STARTING_BALANCE's "no more free signup credit" note)
    that the ledger alone doesn't account for. Skipping this term
    would make every single account look like it's drifted by exactly
    DEFAULT_STARTING_BALANCE, which is a false positive, not a finding.

    Read-only, always — this never writes/corrects anything, on
    purpose. Auto-correcting a drifted balance from inside the same
    check that found it is exactly backwards: a drift is a signal that
    something upstream (a race, a bypassed function, a bad manual
    edit) needs a human to understand WHY before anything touches the
    number again — silently overwriting balance_usd to match the
    ledger would erase the only evidence of what actually happened,
    and would be actively wrong in the case where the LEDGER is what's
    incomplete (a charge that hit balance_usd via deduct_balance() but
    whose ledger insert failed partway) rather than the balance.

    Tolerance: quantized to _QUANT (0.00001, matching balance_usd's own
    numeric(14,5) precision) before comparing, so this doesn't flag
    phantom sub-cent drift from Decimal(str(some_float)) round-tripping
    through JSON — a real property of how every admin_* helper in this
    file and in supabase_client.py already reads these same numeric
    columns, not something new this function introduces."""
    accounts, ledger_sums = await _fetch_all_accounts_paginated(), await _fetch_all_ledger_sums_paginated()
    drifts: list[AccountDrift] = []
    for user_id in sorted(set(accounts) | set(ledger_sums)):
        actual = accounts.get(user_id, Decimal("0"))
        expected = (DEFAULT_STARTING_BALANCE + ledger_sums.get(user_id, Decimal("0"))).quantize(_QUANT)
        actual_q = actual.quantize(_QUANT)
        drift = (actual_q - expected).quantize(_QUANT)
        if drift != Decimal("0"):
            drifts.append(AccountDrift(user_id=user_id, expected_balance=expected, actual_balance=actual_q, drift=drift))
    return drifts




async def fetch_billing_summary(user_id: str, ledger_limit: int = 20) -> dict:
    """For the dashboard's Billing page: current balance + recent ledger
    entries. Creates the account (at DEFAULT_STARTING_BALANCE) first if
    this user has never made a billed request or visited this page
    before, so a brand-new account shows a real balance instead of an
    error."""
    if not _enabled():
        return {"enabled": False}
    balance = await ensure_account(user_id)
    params = {
        "select": (
            "created_at,kind,product,amount_usd,balance_after_usd,"
            "billed_prompt_tokens,billed_cached_tokens,billed_completion_tokens,is_peak,description"
        ),
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(ledger_limit),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.SUPABASE_URL}/rest/v1/billing_ledger", headers=_headers(), params=params)
    resp.raise_for_status()
    return {
        "enabled": True,
        "balance_usd": str(balance),
        "starting_balance_usd": str(DEFAULT_STARTING_BALANCE),
        "ledger": resp.json(),
    }
