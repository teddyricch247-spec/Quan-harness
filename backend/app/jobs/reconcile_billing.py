"""Nightly billing reconciliation — the job app/jobs/README.md's
"Candidate jobs" section describes ("sum billing_ledger against
billing_accounts.balance_usd per user, flag drift"). The actual
comparison logic lives in app.billing.reconcile_all_accounts(); this
file is deliberately thin, per this folder's own README ("Reuse the
real modules... a job is just another caller of the same billing/
supabase logic already trusted for real traffic, not a rewrite of it").

Run: `python -m app.jobs.reconcile_billing` from backend/, with
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY set (see README.md's own setup
steps for wiring this into a Render Cron Job).

Read-only. Never writes or corrects anything — see
billing.reconcile_all_accounts()'s own docstring for why auto-correcting
a drifted balance from inside the same check that found it would be
backwards, not helpful.

Exit code doubles as the alert signal: 0 if every account reconciles
cleanly, 1 if ANY account shows drift, 2 if reconciliation itself
couldn't run (e.g. Supabase env vars missing or unreachable) — a Cron
Job's own failure/alerting picks up a nonzero exit the same way it would
any other script crashing, no separate notification wiring needed on
top of what Render already does for a failed run.

Doubles as the first real end-to-end exercise of billing.py's
deduct_balance()/credit_balance() Postgres functions against a real
Supabase project — see supabase/migrations/0004_billing.sql's own
module comment, "Not live-verified yet." Worth running this once by
hand against a real project specifically to find out whether those
functions work at all, independent of whether it ever finds real
drift.

Added 2026-09-15, deliberately BEFORE this product has a live payment
path (credit_balance() still isn't called from any HTTP route — see
billing.py's DEFAULT_STARTING_BALANCE comment and main.py:get_billing's
docstring): the balance-race window rate_limit.py's own module
docstring already documents (a burst of concurrent requests can overdraw
an account before any of them settle) doesn't need real money moving
through the system to happen — an admin-credited test balance can drift
exactly the same way a real deposit's balance could. Building and
running this now, while the only money at stake is admin-issued test
credit, is far cheaper than discovering it works wrong the first time
it's guarding something real.
"""
import asyncio
import sys

from .. import billing


async def main() -> int:
    if not billing._enabled():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured — nothing to reconcile against.", file=sys.stderr)
        return 2

    try:
        drifts = await billing.reconcile_all_accounts()
    except Exception as e:
        print(f"Reconciliation failed to run: {e!r}", file=sys.stderr)
        return 2

    if not drifts:
        print("Reconciliation clean: every billing_accounts row matches its billing_ledger history.")
        return 0

    print(f"DRIFT FOUND in {len(drifts)} account(s):\n")
    for d in drifts:
        print(f"  user_id={d.user_id}  expected={billing.format_usd(d.expected_balance)}  actual={billing.format_usd(d.actual_balance)}  drift={billing.format_usd(d.drift)}")
    print(f"\n{len(drifts)} account(s) need a human to look at WHY before anything touches their balance again — see billing.reconcile_all_accounts()'s own docstring for why this script doesn't auto-correct.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
