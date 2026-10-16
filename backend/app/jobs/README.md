# app/jobs/

One-shot scripts, not HTTP routes. Each runs once and exits
(`python -m app.jobs.<name>`, run from `backend/`). Nothing in this folder
schedules them. Two things can run them: a Render Cron Job (the intended
long-term home, see `../../../PLAN.md`), or the interim in-process loop in
`app/scheduled_checks.py` (see the last section).

## Why scripts and not routes

A cron process does not go through the FastAPI app, so it needs no route,
no `require_account_key` / `require_login`, and is unreachable from the
public URL. That lets it use `SUPABASE_SERVICE_ROLE_KEY` directly without
that power sitting near a request handler. Jobs reuse the real modules
(`app.billing`, `app.supabase_client`, `app.config`, `app.email_service`)
rather than reimplementing anything.

## The two jobs

### `reconcile_billing.py`
Read-only check that money is recorded consistently. For each user it
compares `billing_accounts.balance_usd` with
`DEFAULT_STARTING_BALANCE + sum(billing_ledger.amount_usd)` and reports
drift. Never writes or corrects anything: a drift is a signal to
investigate, not something to auto-fix. The comparison logic is
`billing.reconcile_all_accounts()`, which reads every ledger row with its
own paginated fetch (the admin-dashboard helpers cap rows and filter by
kind, which would be wrong here).
- Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Exit codes: `0` clean, `1` drift found, `2` could not run.

### `low_balance_alerts.py`
Emails users whose balance is at or below the threshold they set in
Account, Notifications (`low_balance_alert_enabled`,
`low_balance_alert_threshold_usd` in Supabase Auth `user_metadata`).
- Sends at most once per dip: a `low_balance_alert_sent_at` timestamp is
  stored in `user_metadata` (service-role only, so users cannot clear it),
  and cleared when the balance rises back above the threshold.
- Skips suspended accounts. Never touches money tables.
- The email's "Add credits" button links to the Usage page. Do not
  schedule this job before real payments exist.
- The logic is `run_once()`, which returns `LowBalanceResult(sent, cleared,
  errors)` and raises `LowBalanceRunError` if it cannot load its inputs.
  `main()` wraps it for the command line; the in-process loop calls it too.
- Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`,
  plus `RESEND_FROM_EMAIL` and `FRONTEND_URL` for correct sender and link.
- Exit codes: `0` ok, `1` at least one user's send/update failed (the rest
  still ran), `2` could not run.

## Running one by hand

Set the env vars above in your shell, then from `backend/`:
`python -m app.jobs.reconcile_billing`.

## Adding a job

1. New file here with a plain `if __name__ == "__main__":` entry; no
   FastAPI.
2. Reuse existing modules; keep the file thin.
3. Return a meaningful exit code (nonzero = the scheduler shows a failure).
4. To schedule on Render: a separate Cron Job resource on the same repo
   and branch, root directory `backend`, start command
   `python -m app.jobs.<name>`. Cron jobs do not inherit the web service's
   env vars; set their own.

## Interim in-process scheduling (`app/scheduled_checks.py`)

A stopgap until Render Cron Jobs exist. `main.py` passes the module's
`lifespan` to FastAPI, which starts one background task: first run 5 minutes
after boot, then every 24 hours.

- **Reconciliation, always.** Calls `billing.reconcile_all_accounts()` and
  logs one line per run. On drift or failure it emails `ADMIN_ALERT_EMAIL`
  (env; optional, if unset it only logs).
- **Low-balance emails, unless `LOW_BALANCE_ALERTS_ENABLED=false`** (env;
  default true since 2026-10-13). A safety net: the primary trigger is
  `app/balance_alerts.py`, which emails the moment a charge crosses the user's
  threshold; this daily scan catches anything it missed.
- **On demand.** `POST /api/admin/reconcile` (Admin page, "Run check") runs the
  same reconciliation and returns the result; it does not send the alert email.
- **Do not also run the same job from a cron job against the same database
  without thinking.** The low-balance dedupe flag makes a double run harmless
  in the steady state, but two simultaneous runs can both send.
- **Limits:** the timer restarts on every deploy; it only runs while the
  instance is awake; several instances each run their own loop. Because it
  emails on every scheduled run that finds drift, a known-but-unresolved
  drift re-alerts daily.

When a real Render Cron Job runs `python -m app.jobs.reconcile_billing`,
delete `scheduled_checks.py` and the `lifespan=` argument in `main.py`.
