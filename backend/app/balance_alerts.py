"""Balance emails, fired at the moment a charge crosses the line.

Two emails, both triggered from billing.charge_for_request:

  * LOW BALANCE: a user who turned on the alert in Account -> Notifications
    (user_metadata low_balance_alert_enabled + low_balance_alert_threshold_usd)
    gets one email when a charge takes their balance from ABOVE their
    threshold to AT OR BELOW it.
  * BALANCE DEPLETED: any user whose balance goes from above $0 to $0 or
    below gets one email, because from then on their requests are declined
    (billing.check_balance_or_raise). It is a service notice, so it is not
    gated on the alert preference.

Why event-driven. The older daily scan (app/jobs/low_balance_alerts.py,
still run as a safety net) only works while the backend happens to be
awake: the in-process loop sleeps with the free Render plan, and a user can
burn through their threshold hours before it runs. Here the signal is
exact and needs no scan: the deduct_balance Postgres function returns the
new balance, the previous balance is that plus the cost of the request, and
"previous > line >= new" can be true for only ONE request per crossing, so
a crossing is its own de-duplication. No sent-flag has to be re-armed when
the user tops up: dropping below the line again is, by definition, a new
crossing.

Cost control. This runs after a billed request, so the common case must be
free: the whole handler returns immediately when the new balance is above
PREFILTER_USD (and not a depletion). Below that, the user's preferences
come from Supabase Auth (one admin call), cached per user for
CACHE_TTL_SECONDS, so a heavy user with a low balance costs at most one
lookup per few minutes. (A threshold above PREFILTER_USD is therefore only
served by the daily scan.)

Safety. Everything here is a side effect of billing: it runs as a
fire-and-forget task, catches every exception, and can never delay,
fail, or change a charge. It does nothing unless
config.LOW_BALANCE_ALERTS_ENABLED and email delivery is configured.

The daily scan shares one bit of state with this module: the user_metadata
key `low_balance_alert_sent_at`, which this module sets after a low-balance
email so the scan does not send a second email for the same episode while
the balance is still low. (That key lives in user-writable user_metadata;
see the KNOWN LIMIT in jobs/low_balance_alerts.py. The worst case is a
duplicate or skipped email, never money.)
"""

import asyncio
import datetime
import time
from decimal import Decimal, InvalidOperation

from . import config, email_service, email_templates, supabase_client

PREFILTER_USD = Decimal("250")
CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 5000

# Same literal as jobs/low_balance_alerts._ALERT_SENT_KEY. Not imported
# from there: that module imports billing, which imports this one.
ALERT_SENT_KEY = "low_balance_alert_sent_at"

_cache: dict[str, tuple[float, dict | None]] = {}
_tasks: set = set()


def schedule(user_id: str, previous, new) -> None:
    """Queue the check without making the caller wait. Called by
    billing.charge_for_request once the deduction has succeeded. Never
    raises. Needs a running event loop (always true inside a request)."""
    try:
        if not (config.LOW_BALANCE_ALERTS_ENABLED and config.RESEND_API_KEY):
            return
        new_d = Decimal(str(new))
        prev_d = Decimal(str(previous))
        # Cheap exit for the overwhelmingly common case.
        if new_d > PREFILTER_USD:
            return
        task = asyncio.get_running_loop().create_task(on_charge(user_id, prev_d, new_d))
        _tasks.add(task)  # keep a reference so it is not garbage-collected mid-flight
        task.add_done_callback(_tasks.discard)
    except Exception as e:  # noqa: BLE001 — a billing side effect must never raise
        print(f"[balance_alerts] schedule skipped: {type(e).__name__}", flush=True)


async def _user(user_id: str, fresh: bool = False) -> dict | None:
    now = time.monotonic()
    hit = _cache.get(user_id)
    if hit and not fresh and hit[0] > now:
        return hit[1]
    user = await supabase_client.get_auth_user(user_id)
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[user_id] = (now + CACHE_TTL_SECONDS, user)
    return user


def _first_name_source(meta: dict) -> str | None:
    return meta.get("name") or meta.get("full_name") or meta.get("user_name")


def _threshold(meta: dict) -> Decimal | None:
    """The user's saved threshold, or None when alerts are off or no valid
    number was saved. Mirrors jobs/low_balance_alerts.py (bool is not a
    number here, although it is an int in Python)."""
    if not meta.get("low_balance_alert_enabled"):
        return None
    raw = meta.get("low_balance_alert_threshold_usd")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


async def on_charge(user_id: str, previous: Decimal, new: Decimal) -> None:
    """Decides whether this charge crossed a line that earns an email, and
    sends it. Never raises."""
    try:
        if not (config.LOW_BALANCE_ALERTS_ENABLED and config.RESEND_API_KEY):
            return
        depleted = previous > 0 >= new
        if new > PREFILTER_USD and not depleted:
            return

        user = await _user(user_id)
        if not user or not user.get("email") or supabase_client.is_suspended_user(user):
            return
        meta = user.get("user_metadata") or {}
        name = _first_name_source(meta)

        if depleted:
            tpl = email_templates.balance_depleted(name, f"{new:.2f}")
            await email_service.send_email(
                to=user["email"], subject=tpl.subject, html=tpl.html,
                tags={"category": "billing", "template": "balance_depleted"},
            )
            return

        threshold = _threshold(meta)
        if threshold is None or not (previous > threshold >= new):
            return

        # About to send: re-read the user (the cached copy may be minutes old,
        # and the user may have just switched the alert off), and write the
        # sent-flag from that fresh copy.
        user = await _user(user_id, fresh=True)
        if not user or not user.get("email"):
            return
        meta = user.get("user_metadata") or {}
        threshold = _threshold(meta)
        if threshold is None or not (previous > threshold >= new):
            return
        tpl = email_templates.low_balance(_first_name_source(meta), f"{new:.2f}", f"{threshold:.2f}")
        await email_service.send_email(
            to=user["email"], subject=tpl.subject, html=tpl.html,
            tags={"category": "billing", "template": "low_balance"},
        )
        await supabase_client.update_user_metadata(
            user_id, {**meta, ALERT_SENT_KEY: datetime.datetime.now(datetime.timezone.utc).isoformat()}
        )
    except Exception as e:  # noqa: BLE001 — never let an email problem touch billing
        print(f"[balance_alerts] on_charge failed: {type(e).__name__}", flush=True)
