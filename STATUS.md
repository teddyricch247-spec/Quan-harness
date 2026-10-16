# STATUS — verified snapshot of live systems

**Snapshot date: 2026-09-24; the Deploys table was re-checked 2026-10-07** (the Supabase MCP returned `FGA Authentication Error. Unauthorized` that day, so the sections below were not re-verified). Every line says which tool produced it.
Anything older than a day or two: re-check with the commands in
`AGENTS.md` section 1, then update this file. This file holds facts about
live systems only. Tasks live in `PLAN.md`.

## Deploys

| System | State | Source |
|---|---|---|
| Backend (Render web service "Quan AI") | Live, commit `e150fda` ("Last Sync: 2026-10-06 09:20"), re-checked 2026-10-07. Plan: **free**. Auto-deploy on `main`, root dir `backend`, health check `/api/health` | Render MCP `list_services`, `list_deploys`, `get_deploy` |
| Frontend (Vercel project "quancis") | Live and healthy on commit `e150fda`, re-checked 2026-10-07 (the 2026-09-22/24 build failures described below are resolved). Team plan: **Hobby** | Vercel MCP `get_git_deployment_context`, `list_deployments`, `list_deployment_events` |
| Render cron jobs | **None exist.** The two job scripts in `backend/app/jobs/` are not scheduled anywhere. The daily reconcile loop *inside* the web service (`app/scheduled_checks.py`, delivered 2026-09-21) is live as of the `75356db` deploy above; it is not a cron job | Render MCP `list_services` |

Notes:
- **2026-09-22 sync failed:** a git merge conflict was committed unresolved
  into `frontend/src/components/three/HeroCanvas.tsx` (literal
  `<<<<<<<`/`=======`/`>>>>>>> FETCH_HEAD` markers in the file), breaking
  the Turbopack parse. This was never explicitly fixed — a later sync's
  full-content overwrite of that file silently carried it forward past the
  conflict. Confirmed only from the Vercel build log (`list_deployment_events`
  on `dpl_6Pbdii6tBdRJKVbgExDEcwfUkAGW`); worth asking the owner what their
  mobile git client did there, since it can recur.
- **2026-09-24 sync failed:** `frontend/src/data/mockData.ts` (deleted from
  the 2026-09-21 zip, but never actually removed from the live repo — see
  `AGENTS.md` section 3b) still imports the `ModelBenchmark` type, which the
  same zip removed from `types.ts` since nothing else used it. Vercel's
  `next build` failed with `error TS2305: Module '"../types"' has no
  exported member 'ModelBenchmark'`. Confirmed from the Vercel build log
  (`list_deployment_events` on `dpl_714zGcyAq2VJugUmwZgTD9znzDWT`). Fixed in
  the 2026-09-24 zip by restoring both the file and the type, byte-for-byte.
  Not yet confirmed live — re-run `list_deployments` after the owner syncs.
- Deploys of the 2026-09-18 and 2026-09-19 08:48 syncs ended `update_failed`;
  the 12:51 UTC sync on 2026-09-20 went live. The earlier owner notes
  attribute the failures to a missing `OPENROUTER_API_KEY` (set that day).
  The cause was not independently verified.
- Render redeploys `Quan AI` only when files under `backend/` change: the
  2026-09-19 14:40 and 20:28 syncs built on Vercel but produced no Render
  deploy.
- The Render and Vercel accounts also hold projects from **other repos**, not part of this codebase. Confirmed by the owner: **Quan Harness** is a separate coding-agent product (its Render service `Quan-harness`, Vercel project `quan-harness` and the `Quan-MCP` adapter come from the `Quan-harness` repo). Also present: `The-Edit-App-backend` and several unrelated apps. Only "Quan AI" (Render) and "quancis" (Vercel) belong to this repo.
- Env var values cannot be read through any tool. Last reported by the
  owner (not re-verifiable): `OPENROUTER_API_KEY` and `RESEND_FROM_EMAIL`
  set on 2026-09-20.
- The email-logo fix (`auth_email.py`) is in the deployed commit, judging
  by timestamps. **Not yet confirmed by receiving a real email** (PLAN A3).

## Database (Supabase project "quan-ai")

Source: Supabase MCP `list_migrations`, `execute_sql` (read-only), `get_advisors`.

- **2026-10-15 (Supabase MCP `execute_sql`): `0016` and `0017` are both fully applied.** (`purge_expired_chat_traces()` was created last, by the owner in the SQL editor at about 04:45 SAST, after the MCP calls for it timed out or were cancelled; verified afterwards: exists, executable by `service_role` only, 88 trace rows untouched.) `chat_debug_traces.session_id` (cascade FK to `chat_sessions`), its partial index and the column comment exist; `expire_credits(uuid, numeric, text, integer)` exists and is executable by `service_role` only (anon and authenticated: false). Creating `purge_expired_chat_traces` (a plpgsql function containing a `delete`) through the MCP timed out or was cancelled, so it was run by hand. The migrations were applied as plain statements, so `list_migrations` does not show `0016`/`0017`. The 3 ledger rows that held the owner's email now read "Admin credit adjustment" (amounts unchanged; 0 rows match `%@%`). Counts on 2026-10-14: chat_debug_traces 88, billing_ledger 83, billing_accounts 3, chat_sessions 28, usage_logs 86.

- **2026-10-08 (Supabase MCP `list_migrations`, `execute_sql`, `apply_migration`): 17 migrations are applied, three newer than the 14 listed in the next bullet.** All three have a repo file with the same content.
  (1) `kael_beta_split`, version 20261008195400 (repo file `0012`): applied by `apply_migration` in the session that split the one model into Kael Beta and Kael Pro Beta. Renamed `product`/`model` values `pro` and `quan-pro` to `kael-beta` in `chat_sessions`, `usage_logs`, `billing_ledger` and `chat_debug_traces`; deleted the 11 `chat_sessions` rows with model `deepseek-v4-flash` (their 25 `chat_messages` went with them by cascade); set `api_keys.scopes` and its default to `['kael-beta','kael-pro-beta']`; commented `chat_sessions.model`. Checked before and after: the ledger sum ($104.26041, 23 rows), the balances sum ($114.26001), usage tokens (508,334 over 22 rows) and the trace count (23) were identical; sessions went 33 to 22 and messages 72 to 47, with no orphan messages.
  (2) `api_key_thinking_level`, version 20261008195949 (repo file `0013`): adds `api_keys.thinking_level` text, nullable (NULL = "SDK"). Applied by another session the same day. As of the check below no key has a level set.
  (3) `api_key_thinking_level_comment` (repo file `0014`): comment-only; rewrites the column comment on `api_keys.thinking_level` to say a level applies to its own model only.
  Read-only check run after all three: 0 rows in `usage_logs`, `billing_ledger`, `chat_debug_traces` or `chat_sessions` carry a product/model other than `kael-beta` or `kael-pro-beta`. **The live backend and frontend still run the code from before the split until the owner syncs the new zip**, so until then new rows are still written with the old `"pro"` key, and the dashboard cannot price rows it does not recognise.
- **14 migrations applied** (this bullet re-verified 2026-10-07 with `list_migrations` and `execute_sql`; the rest of this file is still the 2026-09-24 snapshot): `create_usage_logs`, `api_keys_and_user_scoping`,
  `chat_debug_traces`, `chat_sessions_and_messages`, `billing`,
  `billing_pin_function_search_path`, `kael_aura_rename_cleanup`,
  `legal_acceptances`, `remove_signup_bonus`, `scopes_default_drop_ultra`,
  `balance_default_sync`, `chat_message_thinking` (repo file `0009`; added
  `chat_messages.thinking` jsonb, nullable, applied 2026-10-05 with
  `apply_migration`), `api_prompts_never_stored` (repo file `0010`; erased
  non-`app_chat` text from `chat_debug_traces` (0 rows had any) and added the
  check constraint `chat_debug_traces_api_text_never_stored`, applied
  2026-10-07), `playground_conversation_default_title` (repo file `0011`;
  `chat_sessions.title` default is now 'New conversation' and 4 legacy
  titles were renamed, applied 2026-10-07). (`remove_signup_bonus` and
  `balance_default_sync` set the same default; harmless.) The repo's migration folder does not
  match this list one-to-one; see `backend/supabase/README.md`.
- **Row counts** (re-checked 2026-10-08 with `execute_sql`): auth users 3,
  billing_accounts 3, billing_ledger 23, api_keys 3, chat_sessions 22,
  chat_messages 47, usage_logs 22, chat_debug_traces 23. (The 2026-09-24
  snapshot said usage_logs and chat_debug_traces were empty; that is no longer
  true.) All of it is test data, by the owner's own statement.
- **Balances vs ledger:** this bullet is from the 2026-09-24 snapshot and
  was not redone. On 2026-10-08 the ledger holds 23 rows summing to $104.26041
  and the three balances sum to $114.26001. Run the reconcile check
  (`POST /api/admin/reconcile`, admin only) for per-account drift rather than reading it
  from these two numbers (PLAN C2).
- **Money functions:** `credit_balance` and `deduct_balance` are SECURITY
  INVOKER and executable by `service_role` only (not `anon`/`authenticated`).
- **Security advisors:** (1) leaked-password protection disabled (WARN;
  needs the Pro plan, not possible on the current plan); (2) 8 tables with
  RLS on and no policies (INFO; intentional, see `AGENTS.md`). Tables:
  api_keys, billing_accounts, billing_ledger, chat_debug_traces,
  chat_messages, chat_sessions, legal_acceptances, usage_logs.

## Email (Resend)

Domain `quancis.space`: verified, sending enabled, receiving disabled,
open and click tracking off. Source: Resend MCP `list-domains`.

## Code vs decisions (things that are true right now)

This section was edited on 2026-09-21 from the delivery zip's contents, not
from a fresh live check; the live facts above are still the 2026-09-20
snapshot.

- **Price:** the live charge was $1.00 input / $0.20 cached / $3.00 output as
  of the 2026-09-20 snapshot (commit `6486a27`). The 2026-09-21 zip raised it
  to $2.00 / $0.40 / $4.00 and Render's later deploys (`75356db` on 09-24,
  `9b0369f` on 09-25) are live, so that price is very likely in effect now;
  **not re-verified** against the live `GET /api/config`. The 2026-09-28 zip
  raises output only, to **$6.00** (input and cached unchanged); it takes
  effect when the owner syncs it. The live `/docs` still quotes the old
  $1.00 / $3.00 until the rewrite (PLAN A8, done 2026-10-06 in the zip, not
  yet synced) goes live; it quotes $2.00 / $0.40 / $6.00. The 2026-10-08 zip
  raises everything again to **$3.00 / $0.60 / $10.00** (code, site and
  docs); not live until the owner syncs it.
- **`/pricing` page** (2026-09-28 zip) is not live until synced. It includes
  competitor prices dated 2026-09-28; see PLAN B7 for how each was checked.
- **No payment processor exists.** No code for any processor anywhere.
  "Add Prepaid Credits" on the Usage page is a "Coming Soon" stub, so
  nobody can pay.
- **Terms of Service and Privacy Policy** were rewritten in full in the
  2026-10-13 zip (Lemon Squeezy, refunds, credits-not-money, retention,
  deletion, prices, contact addresses). **Not live until the owner syncs it.**
  The text describes behavior that needs the 2026-10-13 backend code, the two
  migrations above, and (not built yet) the safety screening. See `PLAN.md`
  D3 and `LEGAL_UPDATES.md`.
- *(older, kept for history)* The Terms of Service (live as of the 2026-09-24 snapshot) describe a deposit-match
  promo "through September 8, 2026" (ended) and the old price. The
  2026-09-21 zip already fixed the price line; the 2026-09-28 zip fixes the
  promo text too (PLAN D3) — not live until synced. The owner confirmed on
  2026-09-28 that the 100% match will not return.
- **Google and GitHub sign-in:** code is done for both; whether each
  provider is enabled in the Supabase dashboard is unverified (PLAN A4).
- **PLAN B1 to B5** (price change, sitemap/robots, `mockData.ts` removal,
  the daily billing check with its Admin button, comment cleanups) are new in
  the 2026-09-21 delivery zip and are **not deployed** until the owner syncs
  it. **B6** (hero pointer fix, `HeroCanvas.tsx`) was already in the
  2026-09-20 zip; whether it has been deployed was not re-verified.
  `npm run lint` / `npm run build` have not been run on any of it.
- **Daily billing check env vars:** `ADMIN_ALERT_EMAIL` and
  `LOW_BALANCE_ALERTS_ENABLED` are new and optional. Their values cannot be
  read through any tool. Once the check is live, the two legacy balances
  above will show as drift in the logs on every run until PLAN C2 is done.
- **PDF and Word attachments, the history divider and the chat-switch fix** (2026-10-14) are new and have
  only been tested with generated files and a command-line reference tool, never in a browser or on a phone.
  Open question: a PDF that is a scan (no text) is refused; there is no OCR.
- **Attached text files and voice typing** (2026-10-14 delivery) are new and
  **not deployed or tested live**. Backend unit tests pass
  (`test_chat_files.py`, `test_transcription.py`); `main.py` was only
  compile-checked and the new `POST /api/chat/transcribe` route has never run.
  The frontend was only syntax-checked; `npm run lint` / `npm run build` have
  not been run. Not tried against the real transcription upstream, on an
  iPhone, or with Zulu, Sotho or Tswana speech. Optional env var
  `TRANSCRIPTION_MODEL`. Legal wording still owed: `LEGAL_UPDATES.md` section 14.
- **Email system update** (delivered 2026-10-14, merged with the voice/files delivery) is new and
  **not deployed or tested live**. `test_email_system.py` (410 checks) and the other backend test
  scripts pass, but only in an environment with stand-ins for FastAPI/httpx (no packages could be
  installed); nothing has been run against real FastAPI, a real Resend account or the Supabase
  confirm-link flow, and `npm run lint` / `npm run build` have not been run. New optional env vars:
  `RESEND_REPLY_TO`, `AUTH_LINK_MODE` (deploy the frontend `/auth/confirm` route before setting it to
  `confirm_page`), `AUTH_EMAIL_HOURLY_CAP`. **Behaviour change on deploy:** `LOW_BALANCE_ALERTS_ENABLED`
  now defaults ON (set it to `false` to keep the balance emails off); real customers can be emailed as
  soon as this is live. New emails are also sent on suspend/reactivate, new API key, admin credit and
  password change. Not verified: DMARC and the `support@` mailbox, Supabase Auth dashboard settings,
  Resend plan limits, rendering in real mail clients. Account deletion emails exist but no deletion
  backend does (`backend/EMAIL_ACCOUNT_DELETION.md`).
