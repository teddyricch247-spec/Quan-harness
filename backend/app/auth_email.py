"""
Email+password signup and password-reset, added 2026-08-27 alongside
the existing GitHub OAuth flow (app/auth.py's require_login already
accepts ANY valid Supabase session regardless of which provider created
it, so no change was needed there — a password-based sign-in produces
the exact same kind of session GitHub does, and the frontend's
supabase.auth.signInWithPassword() call needs no backend route at all,
since Supabase verifies the password itself against the anon key).

What this module actually adds is the account-creation and
confirmation-email side, entirely backend-controlled rather than
Supabase's own built-in email sender:

  1. POST /api/auth/signup — creates an unconfirmed Supabase Auth user
     (supabase_client.create_auth_user) and emails a confirmation link
     via Resend (email_service.send_email). The user isn't a real
     logged-in account until they click it.
  2. POST /api/auth/forgot-password — emails a password-recovery link
     via Resend for an existing, confirmed account.
  3. POST /api/auth/resend-confirmation — emails a fresh confirmation
     link to an existing UNCONFIRMED account, without touching its
     password (re-submitting signup does overwrite it; see signup()).

All link types are minted via supabase_client.generate_action_link,
which asks GoTrue for a one-time link WITHOUT Supabase sending anything
itself — this app owns the email content end to end.

Resend confirmation, deliberately via "magiclink" not "signup": GoTrue's
generate_link(type="signup") only succeeds when the email has no
account yet (it creates the user itself in that call) — trying it again
for an already-created-but-unconfirmed user 422s. There is no
"resend confirmation" link type in GoTrue's admin API (a known,
long-standing gap — see supabase/supabase#3526). "magiclink" is the
standard workaround: it works for any existing user regardless of
confirmation state, and verifying it confirms the email as a side
effect (proving mailbox ownership is exactly what both flows need).

No enumeration via response shape: signup() and forgot_password() both
return the same generic message whether or not the email already has
an account, so this pair of public, unauthenticated endpoints can't be
used to probe which emails are registered. Actual behavior still
differs internally (see each function's docstring) — only the response
looks the same.

Admin accounts are never touched by either flow, on purpose. Both
functions check supabase_client.is_admin_user(existing) first and, if
true, do nothing except (for signup) fire the same "someone tried to
touch your account" notice used for any already-registered email —
never generate a real action link, never call update_user_password.
This means an admin's password can ONLY be changed by someone with
direct Supabase project access (the dashboard, or SQL with the service
role key) — the same bar as granting admin in the first place (see
app/auth.py's require_admin docstring for how the first admin was
bootstrapped). Concretely, this closes two paths that would otherwise
exist purely because these routes are unauthenticated by necessity:
  1. forgot_password() minting a real recovery link for an admin's
     email and mailing it out — password recovery normally proves
     nothing beyond "controls the inbox", which is a lower bar than
     this app wants for its own admin accounts.
  2. signup() calling update_user_password() on an existing-but-
     unconfirmed account — the branch meant for an ordinary user
     retrying an incomplete signup — if that account happened to carry
     the admin flag.
Nothing about this affects how an admin SIGNS IN day to day: that's
still the same signInWithPassword() call through the same LoginPage
every other user goes through (see AppContext.tsx) — only account
creation and credential recovery are restricted here.

Rate limiting on these two routes lives in app/rate_limit.py, not here —
main.py calls enforce_auth_rate_limit() (keyed by both caller IP and
target email) before either signup() or forgot_password() below runs,
so neither is actually reachable without it despite living in a
different module.
"""

import time
import unicodedata
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from . import config, supabase_client, email_service, email_templates, rate_limit

GENERIC_SIGNUP_MESSAGE = "If that email can be registered, we've sent a confirmation link — check your inbox."
GENERIC_RESET_MESSAGE = "If an account exists for that email, we've sent a password reset link."


def _require_frontend_url() -> str:
    if not config.FRONTEND_URL:
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": "Server is not configured (missing FRONTEND_URL).", "type": "server_error"}},
        )
    return config.FRONTEND_URL


def _action_link(link_response: dict) -> str | None:
    return (link_response.get("properties") or {}).get("action_link") or link_response.get("action_link")


# Email content lives in app/email_templates.py (built on
# app/email_layout.py, which carries the platform's design tokens and
# escapes every value). This module only decides WHO gets WHICH email.
# Before 2026-10 the HTML was hand-written in this file and the signup
# `name` was interpolated into it unescaped: anyone could POST a victim's
# address with HTML in `name` and the victim received it inside a genuine
# Quancis email. The layout escapes by default now, and _validate_name
# below rejects markup characters up front; keep both.

NAME_MAX_LENGTH = 80
GENERIC_RESEND_MESSAGE = "If that email is waiting to be confirmed, we've sent a new confirmation link — check your inbox."

_BIDI_CONTROLS = {"\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"}


def _validate_name(name) -> str:
    """The display name given at signup. Whitespace (including newlines
    and tabs) is collapsed, then: required, at most NAME_MAX_LENGTH
    characters, no control characters, no bidirectional-override
    characters, and no "<" or ">". The email layout escapes the name
    regardless; this keeps junk (and attempted markup) out of the account
    record, the admin dashboard, and every future surface that shows it.
    Mirrored in LoginPage.tsx's validateNameField."""

    def bad(message: str):
        return HTTPException(
            status_code=400,
            detail={"error": {"message": message, "type": "invalid_request_error", "param": "name"}},
        )

    if not isinstance(name, str) or not name.strip():
        raise bad("Name is required.")
    cleaned = " ".join(name.split())
    if len(cleaned) > NAME_MAX_LENGTH:
        raise bad(f"Name must be {NAME_MAX_LENGTH} characters or fewer.")
    if "<" in cleaned or ">" in cleaned:
        raise bad("Name can't contain < or > characters.")
    if any(unicodedata.category(c) == "Cc" or c in _BIDI_CONTROLS for c in cleaned):
        raise bad("Name contains characters that aren't allowed.")
    return cleaned


def _auth_link(link_response: dict, frontend_url: str) -> str | None:
    """The URL the confirm / reset email's button points at.

    config.AUTH_LINK_MODE == "confirm_page": a link on the frontend
    origin, /auth/confirm?token_hash=...&type=..., which shows a button
    and only then spends the one-time token (supabase.auth.verifyOtp).
    That keeps email security scanners that pre-fetch links from burning
    the token, and keeps the link host on the brand's own domain.

    Anything else (the default): GoTrue's own action_link, exactly as
    before. If confirm_page mode is on but GoTrue's response lacks the
    fields it needs, fall back to the classic link rather than fail the
    signup or reset."""
    if config.AUTH_LINK_MODE == "confirm_page":
        props = link_response.get("properties") or {}
        token_hash = props.get("hashed_token") or link_response.get("hashed_token")
        link_type = props.get("verification_type") or link_response.get("verification_type")
        if token_hash and link_type in ("magiclink", "recovery"):
            return f"{frontend_url.rstrip('/')}/auth/confirm?{urlencode({'token_hash': token_hash, 'type': link_type})}"
        print("[auth_email] AUTH_LINK_MODE=confirm_page but GoTrue returned no hashed_token; using the classic link", flush=True)
    return _action_link(link_response)


_cap_alert_sent_at = 0.0


async def _budget_allows() -> bool:
    """Counts one outgoing auth email against the global hourly cap
    (rate_limit.auth_email_budget_allows). When the cap is reached the
    caller skips the send and still gives its normal generic response, and
    ADMIN_ALERT_EMAIL (if set) is told once per hour."""
    global _cap_alert_sent_at
    if rate_limit.auth_email_budget_allows():
        return True
    print("[auth_email] hourly auth-email cap reached; not sending", flush=True)
    now = time.time()
    if config.ADMIN_ALERT_EMAIL and now - _cap_alert_sent_at > 60 * 60:
        _cap_alert_sent_at = now
        try:
            tpl = email_templates.admin_email_cap_reached(config.AUTH_EMAIL_HOURLY_CAP)
            await email_service.send_email(
                to=config.ADMIN_ALERT_EMAIL, subject=tpl.subject, html=tpl.html,
                tags={"category": "ops", "template": "admin_email_cap_reached"},
            )
        except Exception as e:  # never let the alert break the request
            print(f"[auth_email] cap alert email failed: {type(e).__name__}", flush=True)
    return False


async def _send(tpl, to: str, template: str, category: str) -> None:
    """One place that sends a rendered template with Resend tags."""
    await email_service.send_email(
        to=to, subject=tpl.subject, html=tpl.html,
        tags={"category": category, "template": template},
    )


def _validate_email(email: str | None) -> str:
    if not isinstance(email, str) or not email or "@" not in email or " " in email:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "A valid email is required.", "type": "invalid_request_error", "param": "email"}},
        )
    return email.strip().lower()


def _validate_signup_email(email: str | None) -> str:
    """Stricter than _validate_email: also rejects the "+" alias
    pattern (e.g. name+tag@domain.com) and obviously malformed domains,
    mirroring LoginPage.tsx's client-side checks. That frontend
    validation is easy to bypass (anyone can call this endpoint
    directly), so the rule is enforced here too rather than being
    purely cosmetic.

    forgot_password() intentionally keeps using the looser
    _validate_email instead of this — it only looks up an existing
    account to email a recovery link to, and shouldn't start rejecting
    lookups for any account that happened to predate this rule."""
    email = _validate_email(email)
    local_part, _, domain = email.partition("@")
    if "+" in local_part:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "Email aliases (e.g. name+tag@domain.com) aren't accepted. Please use your primary email address.", "type": "invalid_request_error", "param": "email"}},
        )
    if not domain or "." not in domain or domain.startswith(".") or domain.endswith(".") or ".." in email:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "A valid email is required.", "type": "invalid_request_error", "param": "email"}},
        )
    return email


async def signup(
    email: str | None,
    password: str | None,
    name: str | None,
    terms_accepted: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """POST /api/auth/signup. Four cases, all ending in the same
    generic response:
      - Existing ADMIN account -> never touched; a security notice is
        sent instead (see module docstring's "Admin accounts are never
        touched" section).
      - New email -> create an unconfirmed user, email a confirmation
        link.
      - Existing but UNCONFIRMED account (an earlier incomplete signup)
        -> update its password to whatever was just submitted (in case
        they forgot it) and resend a fresh confirmation link.
      - Existing, CONFIRMED account -> don't touch it or send a
        confirmation; instead email the real owner a heads-up that
        someone tried to sign up with their address.

    terms_accepted is enforced server-side, not just trusted from the
    frontend's checkbox state — a request with it false or missing is
    rejected outright, the same way a too-short password already is.
    On the two branches that actually create/touch an account (new
    signup, and existing-unconfirmed retry), a durable acceptance
    record is written via supabase_client.record_legal_acceptance
    (see supabase/migrations/0007_legal_acceptances.sql) — that record,
    not this checkbox, is the actual source of truth for "did this
    person agree to the Terms/Privacy," going forward."""
    email = _validate_signup_email(email)
    name = _validate_name(name)
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "Password must be at least 8 characters.", "type": "invalid_request_error", "param": "password"}},
        )
    if not terms_accepted:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "You must accept the Terms of Service and Privacy Policy to create an account.", "type": "invalid_request_error", "param": "terms_accepted"}},
        )
    frontend_url = _require_frontend_url()

    existing = await supabase_client.find_auth_user_by_email(email)

    if existing and supabase_client.is_admin_user(existing):
        # Never create/recreate, never touch the password — see this
        # module's docstring ("Admin accounts are never touched by
        # either flow"). Same generic response either way; best-effort
        # notice only, never fails the request over it.
        if await _budget_allows():
            try:
                await _send(email_templates.admin_account_touched("tried to sign up"), email, "admin_account_touched", "security")
            except HTTPException:
                pass  # best-effort; email_service already logged why
        return {"message": GENERIC_SIGNUP_MESSAGE}

    if existing and existing.get("email_confirmed_at"):
        if await _budget_allows():
            try:
                await _send(email_templates.already_registered(), email, "already_registered", "security")
            except HTTPException:
                pass  # best-effort notice only; never fail the signup response over it
        return {"message": GENERIC_SIGNUP_MESSAGE}

    # Global ceiling on auth emails (rate_limit.auth_email_budget_allows).
    # Checked BEFORE an account is created or touched so that, once the
    # ceiling is hit, the public endpoint stops creating junk accounts too.
    if not await _budget_allows():
        return {"message": GENERIC_SIGNUP_MESSAGE}

    account_user_id: str | None = None

    if existing:
        # Unconfirmed account from an earlier incomplete signup.
        await supabase_client.update_user_password(existing["id"], password)
        account_user_id = existing["id"]
    else:
        try:
            created = await supabase_client.create_auth_user(email, password, name)
            account_user_id = created.get("id")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 422):
                # Lost a race with a concurrent signup for the same
                # email — fall through to resending confirmation for
                # whichever account won.
                existing = await supabase_client.find_auth_user_by_email(email)
                if existing and existing.get("email_confirmed_at"):
                    return {"message": GENERIC_SIGNUP_MESSAGE}
                account_user_id = existing["id"] if existing else None
            else:
                raise HTTPException(status_code=500, detail={"error": {"message": "Could not create account.", "type": "server_error"}})

    if account_user_id:
        # Best-effort (see record_legal_acceptance's docstring) — never
        # blocks the confirmation email over a logging write.
        await supabase_client.record_legal_acceptance(
            account_user_id,
            ["terms", "privacy"],
            method="signup_form",
            ip_address=ip_address,
            user_agent=user_agent,
        )

    link_response = await supabase_client.generate_action_link("magiclink", email, redirect_to=frontend_url)
    action_link = _auth_link(link_response, frontend_url)
    if not action_link:
        raise HTTPException(status_code=500, detail={"error": {"message": "Could not generate a confirmation link.", "type": "server_error"}})

    await _send(email_templates.confirm_signup(action_link, name), email, "confirm_signup", "auth")
    return {"message": GENERIC_SIGNUP_MESSAGE}


async def resend_confirmation(email: str | None) -> dict:
    """POST /api/auth/resend-confirmation. For someone whose signup is
    waiting on the confirmation link ("I never got the email", or the link
    expired): emails a FRESH confirmation link to an existing, UNCONFIRMED,
    non-admin account — without touching its password or any other field
    (unlike re-submitting the signup form, which also overwrites the
    password; see signup()). Everything else — no such account, an
    already-confirmed account, an admin account — gets the same generic
    response and no email, and a failed send is swallowed too (the cause is
    already logged by email_service), so the response never reveals which
    case applied. The route's rate limit (main.py) is the same per-IP /
    per-email limit the other two auth routes use."""
    email = _validate_email(email)
    frontend_url = _require_frontend_url()

    existing = await supabase_client.find_auth_user_by_email(email)
    if (
        existing
        and not existing.get("email_confirmed_at")
        and not supabase_client.is_admin_user(existing)
        and await _budget_allows()
    ):
        try:
            link_response = await supabase_client.generate_action_link("magiclink", email, redirect_to=frontend_url)
            action_link = _auth_link(link_response, frontend_url)
            if action_link:
                meta = existing.get("user_metadata") or {}
                name = meta.get("full_name") or meta.get("name")
                await _send(email_templates.confirm_signup(action_link, name), email, "confirm_signup", "auth")
        except (HTTPException, httpx.HTTPError) as e:
            print(f"[auth_email] resend_confirmation failed: {type(e).__name__}", flush=True)
    return {"message": GENERIC_RESEND_MESSAGE}


async def forgot_password(email: str | None) -> dict:
    """POST /api/auth/forgot-password. Only sends a real recovery email
    for an existing, confirmed, NON-admin account. Unconfirmed or
    nonexistent emails get the same generic response with no email sent
    (see module docstring on enumeration); an admin account gets the
    same generic response too, but a security notice instead of a
    recovery link (see module docstring's "Admin accounts are never
    touched" section) — admin passwords are only resettable directly in
    Supabase."""
    email = _validate_email(email)
    frontend_url = _require_frontend_url()

    existing = await supabase_client.find_auth_user_by_email(email)

    if existing and supabase_client.is_admin_user(existing):
        if await _budget_allows():
            try:
                await _send(email_templates.admin_account_touched("requested a password reset"), email, "admin_account_touched", "security")
            except HTTPException:
                pass  # best-effort; email_service already logged why
        return {"message": GENERIC_RESET_MESSAGE}

    if existing and existing.get("email_confirmed_at") and await _budget_allows():
        link_response = await supabase_client.generate_action_link("recovery", email, redirect_to=frontend_url)
        action_link = _auth_link(link_response, frontend_url)
        if action_link:
            await _send(email_templates.reset_password(action_link), email, "reset_password", "auth")

    return {"message": GENERIC_RESET_MESSAGE}
