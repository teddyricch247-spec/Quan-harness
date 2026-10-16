"""Which account events send which transactional email.

Glue only: email_templates.py decides how an email looks and says,
email_service.py delivers it; this module decides WHEN, and makes sure a
failure here can never break the action that triggered it (suspending a
user, creating a key, crediting an account). Every notify_* function:

  * is best-effort: any exception is caught and logged as
    "[account_emails] <template> not sent: <ExceptionName>" (the cause
    itself is already logged by email_service), never raised;
  * does nothing when email delivery isn't configured
    (config.RESEND_API_KEY empty), so local dev and the test suite never
    attempt a send;
  * takes the Supabase Auth user dict (the same shape list_auth_users
    returns) and reads the recipient address and display name from it.

These are service/security notices, not marketing: they are sent
regardless of the user's notification preferences, because the Terms
promise them (suspension: "We will notify you via your registered email
address") or because they are account-security signals (a new API key).
"""

import functools
from datetime import datetime, timezone
from decimal import Decimal

from . import config, email_service, email_templates, rate_limit


def _best_effort(fn):
    """Wraps a notify_* coroutine so NOTHING it does (building the email,
    reading the user, sending) can raise into the caller. Returns False on
    any failure."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[account_emails] {fn.__name__} failed: {type(e).__name__}", flush=True)
            return False

    return wrapper


def _display_name(user: dict | None) -> str | None:
    meta = (user or {}).get("user_metadata") or {}
    return meta.get("full_name") or meta.get("name") or meta.get("user_name")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _money(value) -> str:
    """Two-decimal dollars without the currency sign (the templates add
    it), the same formatting the low-balance email uses."""
    return f"{Decimal(str(value)):.2f}"


async def _deliver(tpl, user: dict | None, template: str, category: str) -> bool:
    to = (user or {}).get("email")
    if not to or not config.RESEND_API_KEY:
        return False
    try:
        await email_service.send_email(
            to=to, subject=tpl.subject, html=tpl.html,
            tags={"category": category, "template": template},
        )
        return True
    except Exception as e:  # noqa: BLE001 — must never break the caller
        print(f"[account_emails] {template} not sent: {type(e).__name__}", flush=True)
        return False


@_best_effort
async def notify_suspended(user: dict | None) -> bool:
    """Terms (TermsPage.tsx, termination/suspension): "We will notify you
    via your registered email address". Sent by admin.suspend_user."""
    return await _deliver(email_templates.account_suspended(_display_name(user)), user, "account_suspended", "account")


@_best_effort
async def notify_reactivated(user: dict | None) -> bool:
    """Sent by admin.activate_user. The email says keys revoked at
    suspension stay revoked, which is what activate_user does."""
    return await _deliver(email_templates.account_reactivated(_display_name(user)), user, "account_reactivated", "account")


@_best_effort
async def notify_api_key_created(user: dict | None, key_name: str | None) -> bool:
    """Security signal: a new API key is a new way to spend the user's
    balance. Contains the key's NAME only, never the secret."""
    label = key_name.strip() if isinstance(key_name, str) else ""
    label = label or "Untitled key"
    tpl = email_templates.api_key_created(_display_name(user), label[:80], _utc_stamp())
    return await _deliver(tpl, user, "api_key_created", "security")


@_best_effort
async def notify_credits_added(user: dict | None, amount, new_balance, bonus=None) -> bool:
    """A receipt for an admin credit (admin.credit_user). `bonus` is the
    deposit-match promo bonus that went in alongside, if any."""
    bonus_text = _money(bonus) if bonus is not None and Decimal(str(bonus)) > 0 else None
    tpl = email_templates.credits_added(
        _display_name(user), _money(amount), _money(new_balance), _utc_stamp(), bonus=bonus_text
    )
    return await _deliver(tpl, user, "credits_added", "billing")


@_best_effort
async def notify_password_changed(user: dict | None) -> bool:
    """"Your password was changed", sent to the signed-in user's own
    address. Password changes happen in the browser (supabase.auth.updateUser),
    so the frontend tells the backend right after one succeeds
    (POST /api/auth/password-changed). That makes this a best-effort notice
    for changes made through the app, NOT a guarantee against someone who
    changes a password by calling Supabase directly; a Supabase-side
    security notification is the complete answer for that (see the email
    audit). Limited to 3 per user per hour so the endpoint cannot be used to
    spam even the user's own inbox."""
    uid = (user or {}).get("id")
    if not uid or not rate_limit.allow(f"password-changed:{uid}", max_requests=3, window_seconds=60 * 60):
        return False
    return await _deliver(
        email_templates.password_changed(_display_name(user), _utc_stamp()), user, "password_changed", "security"
    )


# ---------------------------------------------------------------------
# Account deletion. There is no deletion backend yet (the owner's
# developer is building it); nothing in this repo calls these. See
# backend/EMAIL_ACCOUNT_DELETION.md for the flow and the rules below.
#
# Unlike the notices above, whose callers ignore the result, the caller of
# notify_deletion_requested MUST check it: if the confirmation email could
# not be sent, the person cannot complete the deletion and should be told.
# All four return True only when Resend accepted the message, and none ever
# raises.
# ---------------------------------------------------------------------
def _https_url(url) -> bool:
    return isinstance(url, str) and url.lower().startswith(("https://", "http://"))


@_best_effort
async def notify_deletion_requested(user: dict | None, confirm_url: str, unused_balance=None) -> bool:
    """"Confirm deleting your account", with the confirmation link the
    developer minted. `unused_balance` is the balance in dollars (a number
    or None); a positive value is shown as "not refunded" (Terms). Limited
    to 3 per user per hour. Returns False if the link isn't http(s), the
    limit was hit, or the send failed."""
    uid = (user or {}).get("id")
    if not _https_url(confirm_url) or not uid or not rate_limit.allow(f"deletion-requested:{uid}", max_requests=3, window_seconds=60 * 60):
        return False
    balance = _money(unused_balance) if unused_balance is not None and Decimal(str(unused_balance)) > 0 else None
    tpl = email_templates.account_deletion_requested(_display_name(user), confirm_url, balance)
    return await _deliver(tpl, user, "account_deletion_requested", "account")


@_best_effort
async def notify_deletion_scheduled(user: dict | None, deletion_date: str, cancel_url: str) -> bool:
    """For deletions that wait out a grace period: says when it will
    happen and links to cancel. `deletion_date` is shown as given."""
    if not _https_url(cancel_url) or not isinstance(deletion_date, str) or not deletion_date.strip():
        return False
    return await _deliver(
        email_templates.account_deletion_scheduled(_display_name(user), deletion_date.strip(), cancel_url),
        user, "account_deletion_scheduled", "account",
    )


@_best_effort
async def notify_deletion_cancelled(user: dict | None) -> bool:
    """Sent when a scheduled deletion is cancelled."""
    return await _deliver(email_templates.account_deletion_cancelled(_display_name(user)), user, "account_deletion_cancelled", "account")


@_best_effort
async def notify_account_deleted(user_snapshot: dict | None, unused_balance=None) -> bool:
    """The final email. Call it AFTER the deletion has succeeded, with a
    snapshot of the user dict taken BEFORE deleting (it only needs `email`
    and, optionally, `user_metadata`): once the account is gone there is
    nothing left to look the address up from. A failure here must not undo
    the deletion; it returns False and the cause is in the logs."""
    balance = _money(unused_balance) if unused_balance is not None and Decimal(str(unused_balance)) > 0 else None
    return await _deliver(
        email_templates.account_deleted(_display_name(user_snapshot), _utc_stamp(), balance),
        user_snapshot, "account_deleted", "account",
    )
