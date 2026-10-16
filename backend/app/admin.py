"""
Real admin backend — implements prompt-5-admin-backend.md (2026-08-23).

Replaces AdminPage.tsx's old mock entirely: hardcoded stats (2,842
developers, $34,920 MRR, ...), a hardcoded fake user list, and a
"Grant Admin Access" button any signed-in user could click that just
set local React state with nothing checked server-side. Every route
that calls into this module is gated by app/auth.py's require_admin —
see that function's docstring for the app_metadata.role="admin"
mechanism and how the first admin account was bootstrapped (see
require_admin's docstring and supabase/migrations/0006_admin_bootstrap.sql
— real email intentionally not repeated here, see those files' own
2026-09-15 PII notes).

What's deliberately NOT here, per the prompt's "don't build anything
that fakes or approximates data that can't actually be computed":
  - No fabricated infra/ops metrics ("18/18 reasoning nodes active",
    "database pool connections", "99.98% SLA") — nothing in this
    codebase tracks any of that, and there's no honest way to report
    it. Dropped from get_stats() entirely.
  - No "tier" field (Developer/Scale/Enterprise) in get_users() —
    there's no real tiering concept anywhere in this pricing model
    (flat per-token for every user, see app/billing.py), so inventing
    one just to match the old mock shape would itself be fake data.
  - No "MRR" label — Monthly Recurring Revenue implies a subscription
    that doesn't exist here (this is prepaid balance + usage-based
    billing). get_stats() reports a real, precisely-windowed
    `revenue_30d_usd` instead — see supabase_client.admin_revenue_since's
    docstring for exactly what it sums and why (usage charges, not
    deposits).
  - No live database table browser (the old mock's "Database" tab).
    Decision: dropped, not rebuilt — see the bottom of this file.

Task 6 decision (database/table browser): (a) Drop it. Real admins
already have the actual Supabase dashboard for this — live, accurate,
schema-complete, with none of the extra attack surface a second,
narrower in-app version would add for the same information. A
hardcoded-allowlist row-count endpoint (option b) was the alternative;
it wasn't chosen because it adds a real endpoint and real surface area
to save one dashboard tab-switch, for a business at a scale (single-
digit users, dozens of rows total, as of 2026-08-23) where that tab
would rarely if ever get used. Nothing in this module or main.py
implements it — the frontend prompt this session produces removes the
tab rather than wiring it to anything.
"""

from decimal import Decimal
import datetime
from fastapi import HTTPException

from . import account_emails, api_keys, billing, credit_expiry, scheduled_checks, supabase_client

STATS_WINDOW_DAYS = 30

# ~100 years — effectively indefinite until an explicit activate call.
# GoTrue's ban_duration is a relative duration string, not an absolute
# timestamp, so this has to be "long enough to never expire on its own"
# rather than a literal forever; "none" (GoTrue's own documented value)
# is what activate_user uses to lift it.
SUSPEND_BAN_DURATION = "876000h"


async def get_stats() -> dict:
    """GET /api/admin/stats — Task 2. Every figure here is computed from
    real rows; see each supabase_client helper's own docstring for
    exactly what it reads, its time window, and its row-cap caveat."""
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=STATS_WINDOW_DAYS)).isoformat()

    users = await supabase_client.list_auth_users()
    requests_in_window = await supabase_client.exact_count("usage_logs", {"created_at": f"gte.{since}"})
    cache_hit_rate = await supabase_client.admin_cache_hit_rate_since(since)
    revenue = await supabase_client.admin_revenue_since(since)
    active_api_keys = await supabase_client.exact_count("api_keys", {"revoked_at": "is.null"})

    return {
        "total_users": len(users),
        "window_days": STATS_WINDOW_DAYS,
        "requests_in_window": requests_in_window,
        "cache_hit_rate_in_window": cache_hit_rate,  # 0.0-1.0, or null if zero prompt tokens in the window
        "revenue_in_window_usd": str(revenue),
        "active_api_keys": active_api_keys,
    }


async def get_users() -> dict:
    """GET /api/admin/users — Task 3. One real row per Supabase Auth
    account. total_requests/total_spend are all-time (not windowed —
    see supabase_client.admin_usage_counts_by_user's docstring for why
    that's a deliberate difference from get_stats()'s 30-day window)."""
    auth_users = await supabase_client.list_auth_users()
    request_counts = await supabase_client.admin_usage_counts_by_user()
    spend_totals = await supabase_client.admin_spend_by_user()
    balances = await billing.admin_all_balances()
    key_counts = await api_keys.admin_active_key_counts()

    rows = []
    for u in auth_users:
        uid = u["id"]
        balance = balances.get(uid)
        rows.append({
            "id": uid,
            "email": u.get("email"),
            "created_at": u.get("created_at"),
            "last_active": u.get("last_sign_in_at"),
            "github_username": supabase_client.github_username(u),
            "total_spend_usd": str(spend_totals.get(uid, Decimal("0"))),
            "total_requests": request_counts.get(uid, 0),
            "credit_balance_usd": str(balance) if balance is not None else None,
            "active_keys_count": key_counts.get(uid, 0),
            "is_admin": supabase_client.is_admin_user(u),
            "status": "suspended" if supabase_client.is_suspended_user(u) else "active",
        })
    return {"users": rows}


# billing_accounts.balance_usd is numeric(14, 5): 9 digits before the decimal
# point. A credit that would overflow it is refused here with a clear message
# instead of reaching the database as an opaque 500. Nothing else caps what an
# admin may add.
MAX_CREDIT_USD = Decimal("999999999")


async def credit_user(user_id: str, amount_usd, admin_email: str | None = None, admin_id: str | None = None) -> dict:
    """POST /api/admin/users/{user_id}/credit — Task 4. Reuses
    billing.py's existing credit_balance-RPC wrapper rather than a
    second, parallel way to change a balance (see
    billing.admin_credit_account's docstring).

    Ledger descriptions never contain an email address (changed 2026-10-13).
    Until then the row read "Admin credit adjustment by <the admin's email>",
    and the customer can read their own ledger through GET /api/billing, so the
    owner's personal address sat in other people's billing history. Who made a
    credit is not needed in the description: the call is admin-only and logged by
    the platform. `admin_email` is still accepted so existing callers keep working;
    it is not written anywhere.

    An admin may credit their OWN account, by any amount (added
    2026-10-11: the owner tests the product on his own account and needs to
    top it up without a payment). That is the same ledger write as any other
    credit, except that the ledger row says "Admin self-credit", so a self-credit
    can always be told apart from money a customer paid. `admin_id` is the
    caller's own user id, used only to detect this case.

    Every credit, like every other credit on the account, expires 12 months
    after it was added (app/credit_expiry.py)."""
    if isinstance(amount_usd, bool) or not isinstance(amount_usd, (int, float)) or amount_usd != amount_usd or amount_usd <= 0:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "amount_usd must be a positive number.", "type": "invalid_request_error", "param": "amount_usd"}},
        )
    amount = Decimal(str(amount_usd))
    if amount > MAX_CREDIT_USD:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"amount_usd is too large. The most that can be added in one credit is ${MAX_CREDIT_USD:,}.", "type": "invalid_request_error", "param": "amount_usd"}},
        )
    # The balance has 5 decimal places; anything smaller would round to zero.
    if amount.quantize(Decimal("0.00001")) <= 0:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "amount_usd is too small (the smallest credit is $0.00001).", "type": "invalid_request_error", "param": "amount_usd"}},
        )
    is_self = bool(admin_id) and str(user_id).lower() == str(admin_id).lower()
    description = "Admin self-credit" if is_self else "Admin credit adjustment"
    new_balance = await billing.admin_credit_account(user_id, amount, description)
    # Receipt email (best-effort: account_emails never raises, so a failed
    # send can't undo or fail a credit that already went through). The
    # deposit-match promotion is gone, so there is never a bonus line.
    try:
        await account_emails.notify_credits_added(await supabase_client.get_auth_user(user_id), amount, new_balance)
    except Exception as e:  # noqa: BLE001 — the credit already happened; never fail it over a receipt
        print(f"[admin] credit receipt email skipped: {type(e).__name__}", flush=True)
    return {"user_id": user_id, "credited_usd": str(amount), "new_balance_usd": str(new_balance), "self_credit": is_self}


async def suspend_user(user_id: str) -> dict:
    """POST /api/admin/users/{user_id}/suspend — Task 5. Real, two-layer
    suspension, not a cosmetic flag:

    1. GoTrue ban (banned_until set ~100 years out). Blocks all future
       sign-in and token refresh immediately at the Supabase Auth layer.
       Combined with the explicit banned_until check now in
       app/auth.py's require_login, this also blocks every
       dashboard/admin/billing/keys/chat request on this account on its
       very next call — not just "eventually, once their current access
       token expires" (which is all a ban alone would guarantee; see
       require_login's docstring for why an already-issued token isn't
       otherwise auto-invalidated by Supabase).
    2. Every currently-active API key for this account is revoked
       immediately (api_keys.revoke_all_active_keys). Necessary because
       require_account_key — the gate on every /<model>/v1 and generic /v1
       product route — never touches Supabase Auth at all, only the
       api_keys table's own revoked_at; banning the auth user by itself
       would leave existing keys working indefinitely.

    Together, both require_login AND require_account_key genuinely
    reject this account's requests after this call returns — not just
    hide a UI element.

    Admin accounts are categorically excluded (403), checked here
    server-side rather than only hidden in AdminPage.tsx's developer
    table — admin role is granted via app_metadata.role, writable only
    with the service-role key (see app/auth.py's require_admin), so this
    guard can't be bypassed by anything the frontend does or doesn't
    render. Any admin/role change goes through Supabase's own dashboard,
    never this API, so there's deliberately no "unsuspend-with-override"
    path here either."""
    target = await supabase_client.get_auth_user(user_id)
    if target is not None and supabase_client.is_admin_user(target):
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": "Admin accounts can't be suspended from this dashboard. Manage admin accounts directly in Supabase.", "type": "forbidden", "param": "user_id"}},
        )
    was_suspended = target is not None and supabase_client.is_suspended_user(target)
    await supabase_client.set_user_ban(user_id, SUSPEND_BAN_DURATION)
    revoked_count = await api_keys.revoke_all_active_keys(user_id)
    # The Terms promise email notice on suspension (TermsPage.tsx). Only on
    # a real transition, so re-clicking Suspend on an already-suspended
    # account doesn't email them again. Best-effort: never raises.
    if not was_suspended:
        await account_emails.notify_suspended(target)
    return {"user_id": user_id, "status": "suspended", "api_keys_revoked": revoked_count}


async def activate_user(user_id: str) -> dict:
    """POST /api/admin/users/{user_id}/activate — Task 5. Lifts the
    GoTrue ban (ban_duration="none", GoTrue's own documented value for
    clearing banned_until), restoring sign-in and dashboard/admin access
    immediately.

    Deliberately does NOT restore any API keys revoked at suspension
    time — those stay revoked; the account has to generate new ones
    from the dashboard after reactivation. This is a real decision, not
    an oversight: it means a reactivated account can't silently resume
    traffic on key material that was live during whatever got it
    suspended in the first place. If different behavior is wanted, the
    one line to change is here — a bulk "un-revoke" would go in
    app/api_keys.py, mirroring revoke_all_active_keys, and get called
    from this function."""
    try:
        target = await supabase_client.get_auth_user(user_id)
        was_suspended = target is not None and supabase_client.is_suspended_user(target)
    except Exception:  # noqa: BLE001 — lookup is only for the notice; never block reactivation
        target, was_suspended = None, False
    await supabase_client.set_user_ban(user_id, "none")
    # Only on a real transition (see suspend_user). Best-effort: never raises.
    if was_suspended:
        await account_emails.notify_reactivated(target)
    return {"user_id": user_id, "status": "active"}


async def run_reconcile_check() -> dict:
    """POST /api/admin/reconcile — the billing reconciliation on demand, the
    same check the daily loop in app/scheduled_checks.py runs. Read-only.

    Returns the loop's result shape: {"status": "ok"|"drift", "checked_at",
    "drift_count", "drifts": [...], "error": null}. If the check itself could
    not run (e.g. Supabase unreachable) that is a 502, not a 200 with a
    failure buried inside: an admin clicking "run check" must not mistake
    "could not verify" for "verified clean". Unlike the scheduled run, a
    manual run does not send the alert email."""
    outcome = await scheduled_checks.run_reconcile(trigger="manual")
    if outcome.status == "error":
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": f"Reconciliation could not run: {outcome.error}", "type": "server_error"}},
        )
    return outcome.to_dict()


async def run_credit_expiry(dry_run: bool = True) -> dict:
    """POST /api/admin/expire-credits — the 12-month credit expiry on demand
    (app/credit_expiry.py), the same run the daily loop does. A dry run (the
    default for this route) reports what would expire and writes nothing. If
    the run itself cannot start (Supabase unreachable) that is a 502, not a 200
    with a failure buried inside."""
    outcome = await credit_expiry.run_expiry(dry_run=dry_run)
    if outcome.status == "error":
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": f"Credit expiry could not run: {outcome.error}", "type": "server_error"}},
        )
    return outcome.to_dict()
