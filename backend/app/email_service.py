"""Transactional email delivery via Resend's HTTP API — introduced
2026-08-27 alongside the email+password signup flow (see
app/auth_email.py). Deliberately NOT using Supabase's own built-in auth
email sender: GoTrue's built-in service is rate-limited to a handful of
sends/hour and explicitly documented as unfit for production, and this
app wants full control over the confirmation/reset email's branding
anyway.

This module owns nothing about WHAT gets sent (that is
app/email_templates.py, built on app/email_layout.py) — just the delivery
mechanism, so any feature (a welcome note, a billing receipt) can reuse
send_email() without depending on the auth flow.

What send_email does beyond a bare POST:
  * a plain-text alternative, derived from the HTML when the caller does
    not pass one (email_layout.html_to_text) — Resend's own auto-generated
    text part was poor (blank lines, "QUANCIS", the raw token URL);
  * an optional Reply-To (config.RESEND_REPLY_TO, or the `reply_to`
    argument);
  * a retry on Resend 429 / 5xx (and on network errors, but only when an
    idempotency key makes a repeat safe);
  * the real failure reason in the logs — Resend's error name and message,
    never the recipient address — because "status 403" alone cannot tell
    "domain not verified" from "bad API key";
  * the Resend email id as the return value, so a send can be matched to
    Resend's dashboard.

Existing callers (and the test fakes in test_pipeline_integration.py) use
the three-argument form send_email(to, subject, html); that still works
unchanged. The new parameters are keyword-only and optional.

Logging follows the repo convention (print with a [tag], flush=True):
logging.info() is dropped under uvicorn unless configured, the same reason
scheduled_checks.py gives for doing it this way."""

import asyncio

import httpx
from fastapi import HTTPException
from . import config
from .email_layout import html_to_text

RESEND_URL = "https://api.resend.com/emails"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (0.6, 1.8)  # seconds to wait before retry 1 and retry 2
_warned_sandbox_sender = False


def _log(message: str) -> None:
    print(f"[email] {message}", flush=True)


def _enabled() -> bool:
    return bool(config.RESEND_API_KEY)


def _error_summary(resp: "httpx.Response") -> str:
    """Resend's error name + message, e.g. "validation_error: The
    quancis.space domain is not verified". Never the request body, never
    the recipient."""
    try:
        body = resp.json()
        return f"{body.get('name', 'error')}: {str(body.get('message', ''))[:200]}"
    except Exception:
        return "unparseable response"


async def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    text: str | None = None,
    reply_to: str | None = None,
    tags: dict | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    """Sends one transactional email via Resend's REST API
    (POST https://api.resend.com/emails) and returns Resend's email id.

    Raises HTTPException(500) if RESEND_API_KEY isn't configured or Resend
    itself rejects the request — callers let this propagate as a real error
    rather than reporting signup/reset success when nothing was actually
    sent, which would strand the user with no way to finish. (Best-effort
    callers catch it; the reason is already in the logs.)

    tags: {"category": "auth"}-style pairs, shown in Resend's dashboard;
    keys and values may contain only letters, digits, underscores, dashes.
    idempotency_key: pass a stable string per logical email so a retry
    after a timeout cannot deliver twice."""
    global _warned_sandbox_sender
    if not _enabled():
        _log("not sent: RESEND_API_KEY is not configured")
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": "Email delivery is not configured (missing RESEND_API_KEY).", "type": "server_error"}},
        )
    if "resend.dev" in (config.RESEND_FROM_EMAIL or "") and not _warned_sandbox_sender:
        _warned_sandbox_sender = True
        _log(
            "WARNING: RESEND_FROM_EMAIL is still Resend's sandbox address, which only delivers to the "
            "Resend account owner. Set it to an address on the verified quancis.space domain."
        )

    payload: dict = {
        "from": config.RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text if text is not None else html_to_text(html),
    }
    reply = reply_to or config.RESEND_REPLY_TO
    if reply:
        payload["reply_to"] = reply
    if tags:
        payload["tags"] = [{"name": str(k), "value": str(v)} for k, v in tags.items()]

    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    resp = None
    attempts = 1 + len(_RETRY_DELAYS)
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(RESEND_URL, headers=headers, json=payload)
        except httpx.TransportError as e:
            # A timeout can mean "sent, but no answer": only repeat when an
            # idempotency key makes that safe.
            _log(f"network error talking to Resend (attempt {attempt + 1}/{attempts}): {type(e).__name__}")
            if not idempotency_key or attempt == attempts - 1:
                raise HTTPException(
                    status_code=500,
                    detail={"error": {"message": "Failed to send email via Resend (network error).", "type": "server_error"}},
                )
            await asyncio.sleep(_RETRY_DELAYS[attempt])
            continue
        if resp.status_code in _RETRY_STATUSES and attempt < attempts - 1:
            _log(f"Resend {resp.status_code} (attempt {attempt + 1}/{attempts}), retrying: {_error_summary(resp)}")
            await asyncio.sleep(_RETRY_DELAYS[attempt])
            continue
        break

    if resp.status_code >= 400:
        _log(f"Resend rejected the email (status {resp.status_code}): {_error_summary(resp)}")
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": f"Failed to send email via Resend (status {resp.status_code}).", "type": "server_error"}},
        )
    try:
        return resp.json().get("id")
    except Exception:
        return None
