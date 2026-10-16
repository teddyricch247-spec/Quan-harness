"""Every email Quancis can send, as pure functions: data in, `Email`
(subject + html) out. No I/O, so each one is previewable
(render_email_previews.py) and testable (test_email_templates.py) without
sending anything. Delivery is email_service.send_email().

Rules for adding a template:
  1. Build it from the block classes in email_layout.py. Never write raw
     HTML here and never f-string a user value into markup: pass it as
     plain text to a block and the layout escapes it.
  2. Never put a user-controlled value (name, key label) in the SUBJECT.
  3. One primary button at most. Security emails (confirm, reset) also get
     a LinkFallback.
  4. State only what the code really does (e.g. the suspension email says
     keys are revoked because admin.suspend_user revokes them).
  5. Add the function to SAMPLES in render_email_previews.py and a check in
     test_email_templates.py.

Wired (a real code path sends them): confirm_signup, reset_password,
already_registered, admin_account_touched, low_balance and
balance_depleted (app/balance_alerts.py), password_changed
(POST /api/auth/password-changed), account_suspended,
account_reactivated, api_key_created, credits_added, admin_drift,
admin_check_failed, admin_email_cap_reached.

Templates marked (NOT WIRED) render and are tested but nothing sends them
yet, because each needs something that is not code: welcome needs a
"sent" record so it goes out once (a send-log table), and price_change /
legal_update are operator broadcasts that need that log to be safely
re-runnable. See the email audit. account_deleted is wired: app/account.py
sends it after DELETE /api/account succeeds. The other three
account-deletion emails (account_deletion_requested / _scheduled / _cancelled)
are NOT WIRED because the live flow is a typed confirmation in the app that
deletes at once, with no email link and no waiting period;
backend/EMAIL_ACCOUNT_DELETION.md says how they would be wired.
"""

from __future__ import annotations

import re

from .email_layout import (
    Button,
    Callout,
    Email,
    Facts,
    LinkFallback,
    Para,
    Stat,
    Steps,
    Table,
    render,
    DEFAULT_SITE_URL,
)


def _site() -> str:
    """The frontend origin. Imported lazily so this module stays importable
    (and testable) without the backend's env/config."""
    try:
        from . import config

        return (config.FRONTEND_URL or DEFAULT_SITE_URL).rstrip("/")
    except Exception:
        return DEFAULT_SITE_URL


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", str(name)).strip()[:60]
    return cleaned or None


def _hi(name: str | None) -> Para:
    """Greets by FIRST name only (the whole name read oddly in the first
    production email). Escaping happens in the layout, not here."""
    n = _clean_name(name)
    first = n.split(" ")[0] if n else None
    return Para(f"Hi {first}," if first else "Hi,")


def _r(**kw) -> Email:
    return render(site_url=_site(), **kw)


# ============================================================ account
def confirm_signup(action_link: str, name: str | None) -> Email:
    return _r(
        subject="Confirm your Quancis account",
        preheader="One click to activate your account.",
        eyebrow="Welcome",
        title="Confirm your email",
        blocks=[
            _hi(name),
            Para("Thanks for signing up. Confirm your email address to activate your account and start using Quancis."),
            Button("Confirm email", action_link),
            LinkFallback(action_link),
            Para("Didn't sign up for Quancis? You can safely ignore this email. Nothing will be activated.", muted=True),
        ],
        reason="You're receiving this because someone used this address to sign up for Quancis.",
    )


def welcome(name: str | None) -> Email:  # (NOT WIRED)
    site = _site()
    return _r(
        subject="Welcome to Quancis",
        preheader="Your account is ready. Here is how to make your first request.",
        eyebrow="Welcome",
        title="Your account is ready",
        blocks=[
            _hi(name),
            Para("Your email is confirmed. Three steps get you to a first response from Kael:"),
            Steps(
                (
                    "**Create an API key** on the Keys page. The secret is shown once, so copy it somewhere safe.",
                    "**Send a first request.** The quickstart covers all three request formats.",
                    "**Track spend** on the Usage page, where your balance and token usage live.",
                )
            ),
            Button("Create an API key", f"{site}/keys"),
            Button("Read the quickstart", f"{site}/docs/quickstart", secondary=True),
        ],
    )


# ============================================================ security
def reset_password(action_link: str) -> Email:
    return _r(
        subject="Reset your Quancis password",
        preheader="Choose a new password. The link works once.",
        eyebrow="Security",
        title="Reset your password",
        blocks=[
            Para(
                "We received a request to reset the password on your Quancis account. "
                "This link can be used once and expires shortly after this email was sent."
            ),
            Button("Reset password", action_link),
            LinkFallback(action_link),
            Para("Didn't request this? Ignore this email and your password won't change.", muted=True),
        ],
    )


def password_changed(name: str | None, when_utc: str) -> Email:
    return _r(
        subject="Your Quancis password was changed",
        preheader="If this wasn't you, act now.",
        eyebrow="Security",
        title="Your password was changed",
        blocks=[
            _hi(name),
            Para("The password on your Quancis account was just changed."),
            Facts((("When", when_utc),)),
            Callout(
                "danger",
                "If this wasn't you, reset your password straight away from the sign-in page and contact support.",
                title="Wasn't you?",
            ),
            Button("Go to sign in", f"{_site()}/login", secondary=True),
        ],
    )


def already_registered() -> Email:
    return _r(
        subject="Someone tried to create a Quancis account with your email",
        preheader="An account already exists for this address. No action needed.",
        eyebrow="Security",
        title="Someone tried to sign up with your email",
        blocks=[
            Para(
                "Someone just tried to sign up for Quancis using this email address, but an account already "
                "exists for it. If that was you, sign in as usual. If you've forgotten your password, use "
                "**Forgot password** on the sign-in page."
            ),
            Button("Go to sign in", f"{_site()}/login"),
            Para("If it wasn't you, no action is needed and your account is unaffected.", muted=True),
        ],
        reason="You're receiving this because this address is registered with Quancis.",
    )


def admin_account_touched(action: str) -> Email:
    """`action` is a short phrase such as "tried to sign up" or
    "requested a password reset"; it is escaped like all text."""
    return _r(
        subject=f"Someone attempted {'signup' if 'sign' in action else 'a password reset'} on your admin account",
        preheader="Admin passwords can only be changed in the Supabase dashboard.",
        eyebrow="Admin security",
        title="Activity on your admin account",
        blocks=[
            Para(f"Someone just {action} for this email address, which has admin access on Quancis."),
            Callout(
                "warning",
                "As a security measure, admin passwords can only be set or reset directly in the Supabase "
                "dashboard, not through the app. If this was you, reset it there. If it wasn't, review your "
                "account's recent activity.",
            ),
        ],
        reason="You're receiving this because this address has admin access on Quancis.",
    )


def api_key_created(name: str | None, key_label: str, created_utc: str) -> Email:
    return _r(
        subject="A new API key was created on your Quancis account",
        preheader="Review it if you didn't create it.",
        eyebrow="Security",
        title="New API key created",
        blocks=[
            _hi(name),
            Para("A new API key was just created on your account. The secret is never included in email."),
            Facts((("Key name", key_label), ("Created", created_utc))),
            Callout(
                "warning",
                "If you didn't create this key, revoke it on the Keys page and change your password.",
                title="Wasn't you?",
            ),
            Button("Review API keys", f"{_site()}/keys", secondary=True),
        ],
    )


# ============================================================ billing
def low_balance(name: str | None, balance: str, threshold: str) -> Email:
    return _r(
        subject="Your Quancis balance is running low",
        preheader=f"Your balance is ${balance}, at or below your ${threshold} alert.",
        eyebrow="Billing",
        title="Your balance is running low",
        blocks=[
            _hi(name),
            Stat("Current balance", f"${balance}", note=f"At or below your ${threshold} alert threshold."),
            Para("Requests are declined with a 402 error once your balance reaches $0.00, so top up before then to avoid interruptions."),
            Button("Open Usage", f"{_site()}/usage"),
            Para(
                "Questions about adding credits? Write to support@quancis.space. "
                "You can turn this alert off any time in Account & Settings, under Notifications.",
                muted=True,
            ),
        ],
        reason="You're receiving this because you turned on low-balance alerts.",
    )


def balance_depleted(name: str | None, balance: str) -> Email:
    return _r(
        subject="Your Quancis balance has run out",
        preheader="Requests are being declined until you add credits.",
        eyebrow="Billing",
        title="Your balance has run out",
        blocks=[
            _hi(name),
            Stat("Current balance", f"${balance}"),
            Callout(
                "warning",
                "Requests are declined with a 402 error until your balance is above $0.00.",
                title="Requests are paused",
            ),
            Button("Open Usage", f"{_site()}/usage"),
            Para("Questions about adding credits? Write to support@quancis.space.", muted=True),
        ],
    )


def credits_added(
    name: str | None,
    amount: str,
    new_balance: str,
    when_utc: str,
    reference: str | None = None,
    bonus: str | None = None,
) -> Email:
    rows = []
    if bonus:
        rows.append(("Promotional bonus", f"+${bonus}"))
    rows += [("New balance", f"${new_balance}"), ("Date", when_utc)]
    if reference:
        rows.append(("Reference", reference, True))
    return _r(
        subject="Credits added to your Quancis balance",
        preheader=f"+${amount} was added. Your balance is now ${new_balance}.",
        eyebrow="Billing",
        title="Credits added",
        blocks=[
            _hi(name),
            Stat("Credits added", f"+${amount}"),
            Facts(tuple(rows)),
            Button("View usage", f"{_site()}/usage", secondary=True),
        ],
    )


# ============================================================ account status
def account_suspended(name: str | None) -> Email:
    return _r(
        subject="Your Quancis account has been suspended",
        preheader="Sign-in and API access are disabled.",
        eyebrow="Account",
        title="Your account is suspended",
        blocks=[
            _hi(name),
            Callout(
                "danger",
                "You can't sign in, and every active API key on the account has been revoked.",
                title="What this means",
            ),
            Para("If you believe this is a mistake, contact us and we'll look into it."),
            Button("Contact support", "mailto:support@quancis.space", secondary=True),
        ],
        reason="You're receiving this because of a change to your Quancis account status.",
    )


def account_reactivated(name: str | None) -> Email:
    return _r(
        subject="Your Quancis account has been reactivated",
        preheader="You can sign in again. Create new API keys to resume.",
        eyebrow="Account",
        title="Your account is active again",
        blocks=[
            _hi(name),
            Para("You can sign in again."),
            Callout(
                "info",
                "API keys revoked during the suspension stay revoked. Create a new key on the Keys page to resume requests.",
                title="Before you start",
            ),
            Button("Sign in", f"{_site()}/login"),
        ],
        reason="You're receiving this because of a change to your Quancis account status.",
    )


# ============================================================ policy notices
def price_change(name: str | None, effective: str, rows: list[tuple]) -> Email:  # (NOT WIRED)
    """rows: (model, item, current, new) tuples, already formatted by the
    caller from backend/app/models/kael/config.py (the price source of
    truth). Do not hard-code prices here."""
    return _r(
        subject="Pricing change for Quancis",
        preheader=f"New rates apply from {effective}.",
        eyebrow="Pricing",
        title="Our prices are changing",
        blocks=[
            _hi(name),
            Para(f"Prices per 1M tokens change on **{effective}**. Requests made before then are billed at the current rates."),
            Table(("Model", "Item", "Current", "New"), tuple(tuple(r) for r in rows)),
            Button("See pricing", f"{_site()}/pricing", secondary=True),
        ],
        reason="You're receiving this because we give registered users notice of material pricing changes.",
    )


def legal_update(name: str | None, effective: str, points: list[str]) -> Email:  # (NOT WIRED)
    return _r(
        subject="Updates to the Quancis Terms and Privacy Policy",
        preheader=f"Changes take effect {effective}.",
        eyebrow="Legal",
        title="We're updating our Terms and Privacy Policy",
        blocks=[
            _hi(name),
            Para(f"The updated documents take effect on **{effective}**. What changes:"),
            *[Para(f"\u2022 {p}") for p in points],
            Button("Read the Terms", f"{_site()}/terms-of-service"),
            Button("Read the Privacy Policy", f"{_site()}/privacy-policy", secondary=True),
            Para("Continuing to use Quancis after that date means you accept the updated documents.", muted=True),
        ],
        reason="You're receiving this because we notify registered users of changes to our legal documents.",
    )


# ============================================================ operator
def admin_drift(drifts: list[tuple]) -> Email:
    """drifts: (user_id, expected, actual, drift), all pre-formatted strings."""
    return _r(
        subject=f"Quancis billing check: drift in {len(drifts)} account(s)",
        preheader="Balances do not match their ledger history. Nothing was changed.",
        eyebrow="Admin",
        title="Billing check found drift",
        blocks=[
            Para(f"The scheduled check found **{len(drifts)}** account(s) whose balance does not match their ledger history."),
            Table(("Account", "Expected", "Actual", "Drift"), tuple(tuple(d) for d in drifts)),
            Callout(
                "info",
                "Nothing was changed. The check is read-only on purpose: work out why before any balance is touched. "
                "You can re-run it from the Admin page, Overview tab.",
            ),
        ],
        reason="Sent to the configured ADMIN_ALERT_EMAIL address.",
    )


def admin_check_failed(error: str) -> Email:
    return _r(
        subject="Quancis billing check could not run",
        preheader="Balances were not verified.",
        eyebrow="Admin",
        title="Billing check could not run",
        blocks=[
            Para("The scheduled billing check could not run, so balances were not verified."),
            Facts((("Error", error, True),)),
            Para("Nothing was changed. You can retry from the Admin page, Overview tab.", muted=True),
        ],
        reason="Sent to the configured ADMIN_ALERT_EMAIL address.",
    )


def admin_email_cap_reached(cap: int) -> Email:
    return _r(
        subject="Quancis: hourly auth-email cap reached",
        preheader="Signup and reset emails are paused until the hour rolls over.",
        eyebrow="Admin",
        title="Auth email cap reached",
        blocks=[
            Para(
                f"This server reached its limit of **{cap}** signup, password-reset and security emails in one hour. "
                "Further requests are answered normally but send nothing until the window clears."
            ),
            Callout(
                "warning",
                "If this was not a launch or a traffic spike you expected, someone may be using the public signup or "
                "forgot-password endpoints to mail many addresses. Check recent signups in Supabase and consider "
                "tightening the limits.",
                title="Worth a look",
            ),
            Para("Raise or lower the ceiling with AUTH_EMAIL_HOURLY_CAP. A value of 0 turns the cap off.", muted=True),
        ],
        reason="Sent to the configured ADMIN_ALERT_EMAIL address.",
    )


# ============================================================ account deletion
# Account deletion has no backend yet (the owner's developer is building it).
# These four emails and the notify_* functions in account_emails.py are the
# email side; backend/EMAIL_ACCOUNT_DELETION.md says how to wire them.
# Wording leans only on what the published legal pages already say:
#   Privacy Policy, "Data Retention": on account deletion personal
#     information is removed, except where retention is required by law
#     (e.g. financial records, or evidence of a flagged violation).
#   Terms of Service: unused credits are not refunded on account deletion.
# The owner should have the final wording reviewed against those pages.


def account_deletion_requested(
    name: str | None,
    confirm_url: str,
    unused_balance: str | None = None,
) -> Email:  # (NOT WIRED)
    """"Confirm you want to delete your account". Sent when someone asks to
    delete their account and deletion needs an emailed confirmation (the
    Privacy Policy reserves the right to verify identity before deleting).
    `unused_balance` (dollars, no sign, e.g. "12.50") adds a line saying it
    will not be refunded; pass None to leave it out."""
    blocks = [
        _hi(name),
        Para("We received a request to permanently delete your Quancis account. Confirm below to go ahead."),
    ]
    if unused_balance:
        blocks.append(Facts((("Unused balance", f"${unused_balance} (not refunded)"),)))
    blocks += [
        Callout(
            "danger",
            "Deleting your account ends your access, revokes your API keys and removes your personal information. "
            "Unused credits are not refunded.",
            title="This can't be undone",
        ),
        Button("Delete my account", confirm_url),
        LinkFallback(confirm_url),
        Para(
            "Didn't ask for this? Ignore this email and your account stays exactly as it is. "
            "If you think someone else has access to it, reset your password.",
            muted=True,
        ),
    ]
    return _r(
        subject="Confirm deleting your Quancis account",
        preheader="Confirm to permanently delete your account. Ignore this if it wasn't you.",
        eyebrow="Account",
        title="Confirm account deletion",
        blocks=blocks,
        reason="You're receiving this because a request was made to delete your Quancis account.",
    )


def account_deletion_scheduled(name: str | None, deletion_date: str, cancel_url: str) -> Email:  # (NOT WIRED)
    """For a deletion that happens after a waiting period: tells the person
    exactly when, and gives a one-click way to cancel. `deletion_date` is
    shown as given (format it as you like, e.g. "20 October 2026")."""
    return _r(
        subject="Your Quancis account is scheduled for deletion",
        preheader=f"Your account will be deleted on {deletion_date}. You can still cancel.",
        eyebrow="Account",
        title="Your account will be deleted",
        blocks=[
            _hi(name),
            Para(f"Your Quancis account is scheduled to be permanently deleted on **{deletion_date}**."),
            Callout(
                "warning",
                "Until then you can change your mind. After that date your API keys stop working for good, your personal "
                "information is removed and unused credits are not refunded.",
                title="Changed your mind?",
            ),
            Button("Keep my account", cancel_url),
            Para("Didn't ask for this? Press the button above, then reset your password.", muted=True),
        ],
        reason="You're receiving this because a request was made to delete your Quancis account.",
    )


def account_deletion_cancelled(name: str | None) -> Email:  # (NOT WIRED)
    return _r(
        subject="Your Quancis account will not be deleted",
        preheader="The deletion was cancelled. Your account stays active.",
        eyebrow="Account",
        title="Deletion cancelled",
        blocks=[
            _hi(name),
            Para("The request to delete your Quancis account was cancelled. Your account stays active and nothing was removed."),
            Callout(
                "info",
                "If you didn't cancel it yourself, change your password and contact support.",
                title="Wasn't you?",
            ),
            Button("Go to sign in", f"{_site()}/login", secondary=True),
        ],
        reason="You're receiving this because of a change to your Quancis account.",
    )


def account_deleted(name: str | None, when_utc: str, unused_balance: str | None = None) -> Email:
    """The last email an account ever gets. Send it AFTER the deletion has
    succeeded, to an address and name captured BEFORE it (the account is
    gone afterwards)."""
    rows: list = [("Deleted", when_utc)]
    if unused_balance:
        rows.append(("Unused balance", f"${unused_balance} (not refunded)"))
    return _r(
        subject="Your Quancis account has been deleted",
        preheader="Your account and personal information have been removed.",
        eyebrow="Account",
        title="Your account has been deleted",
        blocks=[
            _hi(name),
            Para(
                "Your Quancis account has been deleted and your personal information removed from our systems, "
                "except for records we are required by law to keep, such as financial records."
            ),
            Para(
                "Your API keys, Playground conversations, usage and billing records on the account are gone, and any "
                "credits left on it were forfeited. Your payment provider keeps its own records of past purchases, "
                "as described in our Privacy Policy."
            ),
            Facts(tuple(rows)),
            Para("This is the last email you'll get from us about this account. Thanks for trying Quancis."),
            Para("Didn't ask for this? Write to response@quancis.space straight away.", muted=True),
        ],
        reason="You're receiving this one last time because your Quancis account was deleted.",
    )
