"""Low-balance email alerts — reads the per-user notification
preference AccountPage's Notifications tab now persists for real
(`low_balance_alert_enabled` / `low_balance_alert_threshold_usd` in
Supabase Auth user_metadata, written client-side via
supabase.auth.updateUser() — see frontend/src/context/AppContext.tsx's
updateNotificationPrefs) and emails anyone whose balance has dropped to
or below their own threshold. Before this job existed, that toggle
persisted but nothing ever acted on it — this is the delivery half.

Run: `python -m app.jobs.low_balance_alerts` from backend/, with
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / RESEND_API_KEY set (see this
folder's README.md for wiring this into a Render Cron Job — once daily
is a reasonable schedule; the dedupe behavior below means running it
more often than that doesn't send more emails anyway).

Dedupe / re-alert behavior: a `low_balance_alert_sent_at` timestamp is
written into the user's own user_metadata (via
supabase_client.update_user_metadata, the service-role admin API) the
first time their balance crosses at-or-below their threshold, and a
repeat alert is skipped for as long as that field is set. Once their
balance rises back above the threshold (a top-up), the field is
cleared, so a *future* dip alerts again.

KNOWN LIMIT (email audit): this flag lives in the same user_metadata the
browser can rewrite. supabase.auth.updateUser({data}) replaces user_metadata
wholesale, so a user (or a stale session saving Notification prefs) can drop
or resurrect the flag. The effect is only a duplicate or a skipped alert for
that user, never money movement. The durable fix is a server-owned table
(email_preferences / email_log) behind a backend route.

Read-only about money — never touches billing_accounts/billing_ledger,
only reads a balance already computed by billing.admin_all_balances()
(same helper, same pre-existing PostgREST-implicit-row-cap caveat as
reconcile_billing.py's own admin reads — fine at this product's current
scale, not fixed here, not this job's concern to fix).

Skips suspended accounts (supabase_client.is_suspended_user) — no point
emailing someone about topping up a balance they're currently blocked
from spending anyway.

Two ways to run the same logic (run_once()):
  - this file as a command (main(), below), e.g. from a Render Cron Job;
  - the in-process loop in app/scheduled_checks.py, ONLY when
    LOW_BALANCE_ALERTS_ENABLED (default on since 2026-10-13). This scan is
    now the safety net: the primary trigger is app/balance_alerts.py, which
    emails at the moment a charge crosses the threshold and sets the same
    sent-flag so this scan does not send a second email. Don't enable both against
    the same database without thinking: the dedupe key above makes a double
    run harmless in the steady state, but two runs at the same moment can
    both see "not yet alerted" and both send.
"""
import asyncio
import datetime
import sys
from dataclasses import dataclass

from .. import billing, email_service, email_templates, supabase_client

_ALERT_SENT_KEY = "low_balance_alert_sent_at"


def _alert_html(name: str | None, balance: str, threshold: str) -> str:
    """The email body. Built by email_templates.low_balance (shared shell,
    every value escaped); kept as a function here so the call below and any
    caller of lba._alert_html keep working."""
    return email_templates.low_balance(name, balance, threshold).html


class LowBalanceRunError(Exception):
    """The run could not start at all (billing not configured, or the
    users/balances could not be loaded). str(e) is the message main() prints
    to stderr. Per-user failures are NOT raised — they are counted in
    LowBalanceResult.errors so one bad account never stops the rest."""


@dataclass
class LowBalanceResult:
    sent: int = 0
    cleared: int = 0
    errors: int = 0


async def run_once() -> LowBalanceResult:
    """One pass over every account. Raises LowBalanceRunError if it cannot
    load its inputs; otherwise returns counts (errors are counted, printed to
    stderr per user, and never raised)."""
    if not billing._enabled():
        raise LowBalanceRunError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured — nothing to check.")

    try:
        users = await supabase_client.list_auth_users()
        balances = await billing.admin_all_balances()
    except Exception as e:
        raise LowBalanceRunError(f"Could not load users/balances: {e!r}") from e

    result = LowBalanceResult()

    for user in users:
        if supabase_client.is_suspended_user(user):
            continue

        meta = user.get("user_metadata") or {}
        if not meta.get("low_balance_alert_enabled"):
            continue

        threshold = meta.get("low_balance_alert_threshold_usd")
        if not isinstance(threshold, (int, float)):
            continue  # enabled but no valid threshold saved yet — nothing to compare against

        user_id = user["id"]
        balance = balances.get(user_id)
        if balance is None:
            continue  # no billing_accounts row yet (never made a billed request) — nothing to alert on

        already_alerted = bool(meta.get(_ALERT_SENT_KEY))
        balance_float = float(balance)

        try:
            if balance_float <= threshold and not already_alerted:
                email = user.get("email")
                if not email:
                    continue
                greeting_name = meta.get("name") or meta.get("full_name") or meta.get("user_name")
                await email_service.send_email(
                    to=email,
                    subject="Your Quancis balance is running low",
                    html=_alert_html(greeting_name, f"{balance_float:.2f}", f"{float(threshold):.2f}"),
                )
                await supabase_client.update_user_metadata(
                    user_id,
                    {**meta, _ALERT_SENT_KEY: datetime.datetime.now(datetime.timezone.utc).isoformat()},
                )
                result.sent += 1
            elif balance_float > threshold and already_alerted:
                await supabase_client.update_user_metadata(
                    user_id, {k: v for k, v in meta.items() if k != _ALERT_SENT_KEY}
                )
                result.cleared += 1
        except Exception as e:
            result.errors += 1
            print(f"  user_id={user_id}: {e!r}", file=sys.stderr)

    return result


async def main() -> int:
    try:
        result = await run_once()
    except LowBalanceRunError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"Low-balance alerts: {result.sent} sent, {result.cleared} cleared, {result.errors} error(s).")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
