# Session summary: Terms, Privacy and the code behind them (2026-10-12 to 2026-10-15)

Goal: make the Terms of Service and Privacy Policy match what the app does, for the Lemon Squeezy application and before the lawyers read them.

## What was done

**Legal documents**
- Terms of Service rewritten in full (24 sections) and Privacy Policy rewritten in full (17 sections). "Last updated: October 13, 2026". No "whop", no "15 minutes", no personal Gmail, no placeholder markers.
- Lemon Squeezy is the Merchant of Record. Refunds: unused credits within 14 days, billing errors always corrected.
- Credits are described as not money: no cash value, not withdrawable, not transferable, Quancis only, expire 12 months after they are added (oldest first).
- Prices: Kael Beta $3 in / $10 out / $0.60 cached; Kael Pro Beta $8 in / $25 out / $1.60 cached.
- Playground conversations are stored; API text is never stored; no training on your content.
- Safety screening is described as existing (as the owner asked). **No screening code exists yet.**

**Code**
- Account deletion: `DELETE /api/account` and a Delete Account card on the Account page (two-step confirmation).
- Playground diagnostic records are deleted with their conversation and after 30 days (daily purge).
- Credit expiry after 12 months, applied by a daily job; admin dry run at `POST /api/admin/expire-credits`; kill switch `CREDIT_EXPIRY_ENABLED`.
- Requests go only to AI providers that do not store or train on prompts (`data_collection: "deny"`); the request fails with a 503 if none qualifies.
- Dormant promo code removed. Error text capped at 500 characters. Ledger descriptions no longer contain email addresses.
- Usage page top-up text says credits are not money. Docs page "Data and privacy" rewritten.
- Terms/Privacy version constants set to "2026-10-13".

**Live database (project quan-ai), 2026-10-15**
- Migration 0016 applied (session_id column with cascade, index, `purge_expired_chat_traces()`), migration 0017 applied (`expire_credits()`). Applied as plain statements, so they are not in the `list_migrations` history.
- 3 old ledger rows that held the owner's email now read "Admin credit adjustment".

## Files

**New**
- `backend/app/account.py`
- `backend/app/credit_expiry.py`
- `backend/supabase/migrations/0016_trace_session_link_and_retention.sql`
- `backend/supabase/migrations/0017_expire_credits.sql`
- `backend/test_account_retention.py`
- `backend/test_credit_expiry.py`
- `SESSION_CHANGES_2026-10-13.md` (this file)

**Changed, backend**
- `backend/app/main.py`, `supabase_client.py`, `two_pass_pipeline.py`, `provider_routing.py`, `billing.py`, `config.py`, `admin.py`, `scheduled_checks.py`, `models/kael/config.py`
- `backend/backend.env.example`
- Tests: `test_chat_images.py`, `test_pipeline_integration.py`, `test_provider_routing.py`, `test_z_tiers.py`

**Changed, frontend**
- `frontend/src/components/pages/TermsPage.tsx`, `PrivacyPage.tsx` (rewritten)
- `frontend/src/components/pages/AccountPage.tsx`, `UsagePage.tsx`, `AdminPage.tsx`
- `frontend/src/components/docs/pages/platform.tsx`
- `frontend/src/context/AppContext.tsx`, `frontend/src/lib/api.ts`

**Changed, docs**
- `AGENTS.md`, `README.md`, `PLAN.md`, `STATUS.md`, `LEGAL_UPDATES.md` (decisions, 15 lawyer questions, launch checklist), `DOCS_REWRITE_NOTES.md`
- `backend/README.md`, `backend/HISTORY.md`, `backend/supabase/README.md`

## Still open
- Build the automated safety screening (the documents already describe it).
- Build checkout, webhook and refund handling (`PLAN.md` D1).
- Sync the zip (a sync is a deploy), then smoke-test a Playground message, an API request on each model, and deleting a throw-away account.
- Check how long Render, Vercel and Supabase keep logs (Privacy section 8 says "days to a few weeks").
- Lawyers: CPA section 63 (12-month expiry), "credits are not money" wording, refund and cooling-off rules, POPIA Information Officer registration (see `LEGAL_UPDATES.md`).
- On publish day: change "Last updated" on both pages and `TERMS_VERSION` / `PRIVACY_VERSION` together, email users, edit the www.quancis.space pages (/legal, /kael, /about).
