"""Interim in-process scheduled checks (PLAN.md, phase B4).

WHY THIS EXISTS. billing.reconcile_all_accounts() is the only thing that
notices a balance that no longer matches its ledger, and nothing was running
it: app/jobs/README.md describes it as a Render Cron Job, but no cron job
exists. This module is a stopgap that runs the same check from inside the web
service, so drift is noticed without anyone remembering to look. It is NOT a
replacement for a real scheduler.

WHAT IT DOES. main.py passes `lifespan` (below) to FastAPI. On startup that
creates one background task that:
  1. waits INITIAL_DELAY_SECONDS (5 min) so it never slows startup, then
  2. every INTERVAL_SECONDS (24 h), runs:
       a. the 12-month credit expiry (app/credit_expiry.py), unless
          config.CREDIT_EXPIRY_ENABLED is off. It writes: one ledger row per
          account that has credits past their 12 months.
       b. the billing reconciliation. One log line per run:
            [scheduled_checks] RECONCILE ok
            [scheduled_checks] RECONCILE drift <n> account(s)
            [scheduled_checks] RECONCILE failed: <reason>
          On drift or failure it also emails config.ADMIN_ALERT_EMAIL (if
          set; if unset it only logs).
       c. the 30-day clean-up of diagnostic records (chat_debug_traces), via
          the purge_expired_chat_traces() database function. A failure emails
          ADMIN_ALERT_EMAIL.
       d. the low-balance customer emails, ONLY if
          config.LOW_BALANCE_ALERTS_ENABLED is true (default true since
          2026-10-13; the primary trigger is app/balance_alerts.py).
The same reconciliation can be triggered by hand with
POST /api/admin/reconcile (admin.run_reconcile_check); a manual run returns
its result and logs it, but does not send the alert email.

MONEY. The reconciliation is read-only: it never writes or "fixes" a balance
(see billing.reconcile_all_accounts()'s docstring for why). The credit expiry is
the one step here that changes balances, and only through the expire_credits
database function, which writes the matching ledger row in the same
transaction. The low-balance step writes only a dedupe flag into a user's auth
metadata, exactly as the command-line job does.

SAFETY. Nothing here may take the API down:
  - every run is wrapped so an exception is logged, never raised into the
    loop, and the loop itself survives a crashing cycle;
  - a failing alert email is logged and swallowed;
  - task cancellation (app shutdown) is left alone, so shutdown is clean.

KNOWN LIMITS (accepted for a stopgap):
  - The timer restarts on every deploy/restart, so a frequently redeployed
    service may re-run the check more than once a day.
  - It only runs while the instance is awake. On Render's free plan the
    instance sleeps after inactivity, so checks (and alerts) pause with it.
  - If the service ever runs more than one instance, each runs its own loop:
    duplicate alert emails, and (if enabled) duplicate low-balance emails.
  - Because reconcile emails on EVERY scheduled run that finds drift, a drift
    that is known but not yet resolved will re-alert each run. Set
    ADMIN_ALERT_EMAIL after known drift is explained, not before.
A real external scheduler (Render Cron Job running app/jobs/*) supersedes
this module; delete it and the `lifespan=` argument in main.py at that point.
"""

import asyncio
import datetime
import html
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from . import billing, config, credit_expiry, email_service, email_templates, supabase_client
from .jobs import low_balance_alerts

INITIAL_DELAY_SECONDS = 5 * 60
INTERVAL_SECONDS = 24 * 60 * 60

# Keep error text short in logs, emails and API responses; an httpx error's
# message can be long (it embeds the full request URL).
_MAX_ERROR_CHARS = 300


def _log(message: str) -> None:
    # print(), not logging: the rest of this codebase prints "[tag] ..." to
    # stdout (which Render captures), and Python's logging.info() is dropped
    # under uvicorn unless configured. flush so the line is not held in a buffer.
    print(f"[scheduled_checks] {message}", flush=True)


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".rstrip(": ")
    return text if len(text) <= _MAX_ERROR_CHARS else text[: _MAX_ERROR_CHARS - 1] + "…"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class ReconcileOutcome:
    """Result of one reconciliation run.

    status: "ok" (every account matches its ledger), "drift" (at least one
    does not; see `drifts`), or "error" (the check itself could not run; see
    `error`)."""

    status: str
    checked_at: str
    drifts: list = field(default_factory=list)  # list[billing.AccountDrift]
    error: str | None = None

    def to_dict(self) -> dict:
        """JSON-safe shape used by POST /api/admin/reconcile. Money is a
        string (Decimal), matching how admin.py reports balances."""
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "drift_count": len(self.drifts),
            "drifts": [
                {
                    "user_id": d.user_id,
                    "expected_balance_usd": str(d.expected_balance),
                    "actual_balance_usd": str(d.actual_balance),
                    "drift_usd": str(d.drift),
                }
                for d in self.drifts
            ],
            "error": self.error,
        }


async def _send_admin_alert(subject: str, body_html: str) -> bool:
    """Email the owner. Never raises. Returns True only if an email was sent;
    False if ADMIN_ALERT_EMAIL is unset (log-only mode) or sending failed."""
    to = config.ADMIN_ALERT_EMAIL
    if not to:
        return False
    try:
        await email_service.send_email(to=to, subject=subject, html=body_html)
        return True
    except Exception as e:  # HTTPException from send_email, network errors, ...
        _log(f"alert email failed: {_describe(e)}")
        return False


def _drift_email_html(drifts: list) -> str:
    return email_templates.admin_drift(
        [
            (d.user_id, billing.format_usd(d.expected_balance), billing.format_usd(d.actual_balance), billing.format_usd(d.drift))
            for d in drifts
        ]
    ).html


def _failure_email_html(error: str) -> str:
    return email_templates.admin_check_failed(error).html


async def run_reconcile(trigger: str = "scheduled") -> ReconcileOutcome:
    """Run the billing reconciliation once. Never raises (other than
    cancellation): a failure becomes status="error".

    trigger="scheduled" (the loop) emails ADMIN_ALERT_EMAIL on drift/error.
    trigger="manual" (the admin route) does not: the admin is looking at the
    response already, and emailing them their own click is noise."""
    checked_at = _now_iso()
    if not billing._enabled():
        outcome = ReconcileOutcome(
            status="error",
            checked_at=checked_at,
            error="SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured — nothing to reconcile against.",
        )
    else:
        try:
            drifts = await billing.reconcile_all_accounts()
        except Exception as e:
            outcome = ReconcileOutcome(status="error", checked_at=checked_at, error=_describe(e))
        else:
            outcome = ReconcileOutcome(
                status="drift" if drifts else "ok", checked_at=checked_at, drifts=list(drifts)
            )

    suffix = " (manual)" if trigger == "manual" else ""
    if outcome.status == "ok":
        _log(f"RECONCILE ok{suffix}")
    elif outcome.status == "drift":
        _log(f"RECONCILE drift {len(outcome.drifts)} account(s){suffix}")
    else:
        _log(f"RECONCILE failed: {outcome.error}{suffix}")

    if trigger == "scheduled":
        if outcome.status == "drift":
            await _send_admin_alert(
                f"Quancis billing check: drift in {len(outcome.drifts)} account(s)",
                _drift_email_html(outcome.drifts),
            )
        elif outcome.status == "error":
            await _send_admin_alert(
                "Quancis billing check could not run",
                _failure_email_html(outcome.error or "unknown error"),
            )
    return outcome


async def run_low_balance_alerts() -> None:
    """The low-balance customer emails, if LOW_BALANCE_ALERTS_ENABLED. Never
    raises (other than cancellation). Logs one line per run."""
    if not config.LOW_BALANCE_ALERTS_ENABLED:
        return
    try:
        result = await low_balance_alerts.run_once()
    except Exception as e:  # includes low_balance_alerts.LowBalanceRunError
        _log(f"LOW_BALANCE failed: {_describe(e)}")
        return
    _log(f"LOW_BALANCE sent={result.sent} cleared={result.cleared} errors={result.errors}")


async def run_trace_purge() -> int | None:
    """Deletes Playground and API diagnostic records (chat_debug_traces) older
    than supabase_client.TRACE_RETENTION_DAYS (30), through the database
    function from migration 0016. Never raises (other than cancellation).
    Returns how many rows were deleted, or None if the purge failed, in which
    case it also emails ADMIN_ALERT_EMAIL: a purge that silently stops working
    would break the retention promise in the Privacy Policy unnoticed."""
    try:
        deleted = await supabase_client.purge_expired_chat_traces()
    except Exception as e:  # includes: migration 0016 not applied yet
        _log(f"TRACE_PURGE failed: {_describe(e)}")
        await _send_admin_alert(
            "Quancis: diagnostic-record clean-up failed",
            "<p>The daily clean-up of diagnostic records older than "
            f"{supabase_client.TRACE_RETENTION_DAYS} days could not run, so they are piling up.</p>"
            f"<p><code>{html.escape(_describe(e))}</code></p>"
            "<p>The most likely cause is that migration 0016 has not been applied to the database.</p>",
        )
        return None
    _log(f"TRACE_PURGE deleted={deleted}")
    return deleted


async def run_credit_expiry(trigger: str = "scheduled") -> "credit_expiry.ExpiryOutcome":
    """The 12-month credit expiry (app/credit_expiry.py). Never raises (other
    than cancellation). A scheduled run emails ADMIN_ALERT_EMAIL when an account
    had to be skipped because it needs a human (drift, or an expiry row that
    does not match the rules) or when the run could not start."""
    outcome = await credit_expiry.run_expiry(dry_run=False)
    if trigger == "scheduled" and (outcome.status == "error" or outcome.has_problems):
        problems = "".join(
            f"<li><code>{html.escape(s['user_id'])}</code>: {html.escape(s['reason'])}</li>"
            for s in outcome.skipped
            if s["reason"] != credit_expiry.SKIP_STALE
        )
        await _send_admin_alert(
            "Quancis credit expiry: needs a look",
            (f"<p>The credit expiry run could not start: <code>{html.escape(outcome.error or '')}</code></p>" if outcome.status == "error" else "")
            + (f"<p>Accounts skipped by the credit expiry run:</p><ul>{problems}</ul>" if problems else "")
            + "<p>Nothing was changed for those accounts. Run the billing check from the Admin page (Overview tab) to see their drift.</p>",
        )
    return outcome


async def run_cycle() -> None:
    """One scheduled pass. The steps are independent: one crashing does not
    skip the others. Credit expiry runs before the reconcile check so the check
    sees the balances as they are after it."""
    try:
        await run_credit_expiry("scheduled")
    except Exception as e:  # defensive: run_credit_expiry already handles its own errors
        _log(f"CREDIT_EXPIRY crashed: {_describe(e)}")
    try:
        await run_reconcile("scheduled")
    except Exception as e:  # defensive: run_reconcile already handles its own errors
        _log(f"RECONCILE crashed: {_describe(e)}")
    try:
        await run_trace_purge()
    except Exception as e:  # defensive, same reason
        _log(f"TRACE_PURGE crashed: {_describe(e)}")
    try:
        await run_low_balance_alerts()
    except Exception as e:  # defensive, same reason
        _log(f"LOW_BALANCE crashed: {_describe(e)}")


async def _loop(initial_delay: float, interval: float) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await run_cycle()
        except Exception as e:  # never let one bad cycle end the loop
            _log(f"cycle crashed: {_describe(e)}")
        await asyncio.sleep(interval)


def start(initial_delay: float = INITIAL_DELAY_SECONDS, interval: float = INTERVAL_SECONDS) -> "asyncio.Task":
    """Start the background loop. Must be called from a running event loop."""
    return asyncio.create_task(_loop(initial_delay, interval), name="scheduled_checks")


async def stop(task: "asyncio.Task") -> None:
    """Cancel the loop and wait for it to finish. Never raises."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:  # the loop already died on its own; nothing to clean up
        _log(f"loop had already stopped with an error: {_describe(e)}")


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: start the loop at startup, cancel it at shutdown."""
    task = start()
    try:
        yield
    finally:
        await stop(task)
