# PLAN — what to do next

Detailed to-do list, agreed in planning on 2026-09-20. Live facts are in
`STATUS.md`; how the system works is in `backend/README.md`. When a task
is done, tick it. When a whole phase is done, delete it.

**Owner tags:** **[YOU]** = manual, dashboards or decisions. **[AI-CODE]** =
file changes an AI makes, delivered for you to sync (a sync deploys).
**[AI-DB]** = production database changes via the Supabase MCP tool; each
step waits for your explicit "go".

Done in code: **Phase B, B1 to B7**. B1 to B6, plus the later hero-touch and
glass-button changes, were synced and deployed (Vercel `READY` and Render live
on commit `9b0369f`, 2026-09-25); that Vercel run is also a real `next build`
and type check of that code. B7 and the $6.00 output price are in the
2026-09-28 zip and take effect when you sync it. Still open in Phase B: the
"verify on the live site" checks (B1, B2, B6, B7) and two decisions, one about
past Usage-page costs (B1) and one about the site's "free" wording (B7).
Nothing in phase C has been started.

---

## Decisions already made (do not re-ask)

- **New price (2026-10-08):** $3.00 input, $0.60 cached input (= 80% off,
  exactly 20% of input), **$10.00 output**, per million tokens. Owner
  decision: aim for roughly 80% gross margin and compete on reliability, not
  on being cheapest. (It was $2.00 / $0.40 / $6.00 from 2026-09-28; output
  was $4.00 before that.) **Kael Pro Beta** (the z levels, now a model of its own,
  2026-10-08) is $8.00 in / $1.60 cached / $25.00 out and bills at that price
  in the backend. Backend calculation and frontend text both changed (B1). The public **Docs were rewritten on
  2026-10-06** (A8) and read their price from `components/docs/facts.ts`.
- **Render Cron Jobs are a later step** (section "Later"). Until then, an
  interim in-app check is used (B4).
- **Render plan will be upgraded** by you before launch (A5).
- **Leaked-password protection** cannot be enabled on the current Supabase
  plan. Deferred (A7 covers a partial substitute).
- **RLS "no policy" warnings:** fix with explicit deny-all policies (C1),
  not per-user policies.
- **Applied SQL files get deleted** after a schema snapshot is saved (C3).
- **Low-balance alert emails wait until payments exist.** Today the email's
  "Add credits" button leads to a "Coming Soon" page.

---

## Phase A — You (manual, no AI needed)

### A1. Sync this delivery (docs + the hero fix)
- [ ] Use the delivered zip as the codebase. It already omits the three
      replaced files (`STATUS-2026-09-20.md`, `backend/AUDIT_2026-09-15.md`,
      `frontend/REDESIGN-NOTES.md`); if any linger in your copy, delete them.
- [ ] After the sync, confirm Vercel builds the new commit (frontend changed)
      and that Render also builds it (`backend/README.md` and friends changed;
      Render skips commits that touch nothing under `backend/`). Both should
      succeed; no backend code changed.
- [ ] Then do B6's checks on the live site.

### A2. Decide what to do with the two legacy balances
Two accounts hold $4.99960 and $55.00 but the ledger explains only a
$50.00 deposit. Most likely the removed $5 signup credit. The billing
reconcile check treats any such gap as drift. Choose one:
1. **Explain them with `adjustment` ledger rows** (recommended): history
   stays intact and matches the balances. Done in C2.
2. Reset both balances to ledger-consistent values ($0 and $50.00). Loses
   the test credit, leaves no ledger noise.
3. Leave as is. Not recommended: the first reconcile run will report two
   drifts and the alert becomes noise.

Also confirm both accounts are yours or test accounts.

### A3. Confirm the email logo is live
- [ ] Sign up with a fresh address (or use forgot-password) and open the
      email in Gmail and one other client.
- [ ] Check: brand mark renders as the 4x4 grid with the red cell, the
      button works, the footer shows Terms/Privacy links and the support
      address.

### A4. Google and GitHub sign-in
The login page offers both.
- [ ] Supabase dashboard, Authentication, Providers, **Google and GitHub**:
      each enabled, with client ID and secret set. Check the redirect URL
      Supabase shows is allowed in the Google Cloud console and in the GitHub
      OAuth app.
- [ ] In Authentication, URL configuration: site URL and redirect list
      include the production frontend URL.
- [ ] Test: the Google and GitHub buttons on the live login page, end to
      end. Then confirm a `legal_acceptances` row appears for each (this uses
      `POST /api/auth/record-oauth-consent`).

### A5. Upgrade the hosting plans
- [ ] **Vercel:** the team is on the **Hobby** plan, and Vercel's terms limit
      Hobby to non-commercial use. Check the current terms and move to Pro
      before you take payments.
- [ ] Move the Render "Quan AI" web service off the free plan. On free, idle
      services sleep, so the first request after a quiet period is slow.
- [ ] Keep **one instance**: rate limits are in-memory per process.
- [ ] Turn on Render's deploy-failure notifications.
- [ ] After upgrading, call the health endpoint and run one real API
      request (D2).
- The interim scheduled check (B4) only runs while the service is awake, so
  the upgrade matters for it too.

### A6. Choose a payment processor (the launch blocker)
Nothing exists in code yet. Evaluate against these, and verify current
availability yourself; I have not checked onboarding rules:
- Accepts a **South African unregistered sole proprietor**, and pays out to
  a South African bank account.
- **Merchant of record** (handles VAT/sales tax for you) vs direct
  processing (you handle tax).
- Charges in **USD** (balances and prices are USD) or converts fairly.
- Webhooks with signed payloads, refunds API, receipts, fee structure.
- Candidates to look at: Paddle, Lemon Squeezy, Polar (merchant-of-record
  style); Paystack, PayFast (South African); Stripe (check whether it is
  available for South African businesses).
- **Lemon Squeezy** is the processor the owner applied to (2026-10). The
  Terms of Service (sections 6 to 8) and the Privacy Policy were rewritten on
  2026-10-13 around it as Merchant of Record: it takes payment, collects tax,
  issues receipts and handles refunds and disputes. The 14-day refund policy,
  the "refund removes the refunded credits" rule and the chargeback wording
  are in the Terms, so the build in D1 has to match them. Whop is no longer
  mentioned anywhere.
- Output of this task: one processor chosen, account created, test-mode API
  keys ready. Then see D1 for the build.

### A7. Password strength (partial substitute for leaked-password check)
- [ ] Supabase dashboard, Authentication, password settings: set a sensible
      minimum length and character requirements. (Check what your plan
      allows; do not assume.)

### A8. Write the new Docs page content
- [x] Rewritten from scratch on 2026-10-06 as 22 pages (`/docs` plus
      `/docs/<slug>`), written from the backend code. The price now reads
      $3.00 / $0.60 / $10.00 (changed 2026-10-08; it was $2.00 / $0.40 /
      $6.00). Not deployed until the owner syncs it.
- [ ] **Before publishing (D4):** the docs were written for the product as
      the owner described it on 2026-10-06, which is ahead of the code in a
      few places. Make the product match, or the docs will be wrong:
      - **Thinking levels:** the docs list `low`, `high`, `max`, `z-low`,
        `z-high` (no `auto`, and no `off`: dropped by the owner 2026-10-08),
        with z-low/z-high at $8 in / $25 out per 1M (cached input $1.60, from
        the same 80% discount; was $6 / $15 until 2026-10-08). The API now
        accepts all five (`kael_pipeline.py`, tier table in
        `models/kael/config.py`, 2026-10-08). **Done 2026-10-08:** the z levels
        became their own model, **Kael Pro Beta** (`kael-pro-beta`), billed at
        its own $8 / $1.60 / $25 price, and the Playground has a model picker
        with each model's own levels. Not live until the owner syncs it.
      - **Adding credit:** the docs describe a working card top-up of
        $25 / $50 / $100 from the Usage page. The Usage page still shows
        "Coming Soon" there until the payment step is built.
      - **Credit expiry:** the docs say credit expires 12 months after it is
        added (that is what the Terms say). The Usage top-up window says
        credits "never expire". Fix whichever is wrong.
      - **Rate limits:** the docs publish 150 requests/min and 30 concurrent
        per account (decided: keep). If `rate_limit.py` changes, change
        `components/docs/facts.ts` too.
      - **Still following the code:** `response_format` and `tool_choice`
        are ignored, `max_tokens` is ignored, and Kael runs a draft plus an
        optional review. The business brief says otherwise in places.
      - **Contact details:** the Support page shows the two inboxes, the
        trading name and the region. No personal name, no street address
        (`CONTACT` in `components/docs/facts.ts`).

---

## Phase B — Code changes (AI-CODE, wait for your "go")

Tests for each: `cd backend && python test_pipeline_logic.py && python test_pipeline_integration.py`
(both must print `ALL CHECKS PASSED`), and `cd frontend && npm run lint`.
The tests do not hardcode customer prices, so the price change should not
break them.

### B1. Price change to $2.00 / $0.40 / $4.00 (output later raised to $6.00)
- [x] **2026-10-08 follow-up (owner decision):** price raised to $3.00 in /
      $0.60 cached / $10.00 out. Changed in `models/kael/config.py` (cached
      kept at exactly 20% of input), the `billing.py` docstring, the pinned
      test values (`$13.00` for 1M in + 1M out, `$0.60` for 1M cached, `$2.02`
      for the mixed example), `HomePage.tsx`, `PricingPage.tsx` (constants,
      the sentence quoting the price, and the hero line, which said "lowest
      output price" and now says "ties for the lowest output price" because
      GPT-6 Sol is $2 / $10 in the page's own table), `app/page.tsx` and
      `app/pricing/page.tsx` metadata, `TermsPage.tsx`, the `UsagePage.tsx`
      top-up constant, and `components/docs/facts.ts` plus the worked example
      in `docs/pages/platform.tsx` ($0.0294 for the 12,000-in / 1,500-out
      request). Not deployed until the owner syncs it.
- [ ] **Open after the 2026-10-08 change:** (1) the Terms promise
      "reasonable notice of material changes"; give notice and decide whether
      to grandfather existing balances before this goes live. (2) Kael Pro Beta bills at $8 / $25
      in the code from 2026-10-08, but not live until the owner syncs it. (3) The
      `/pricing` competitor rows are dated 2026-09-28; re-check them, and the
      hero line, before relying on the comparison at the new price.
- [ ] **Open after the 2026-10-08 model split** (Kael Beta + Kael Pro Beta):
      (1) **Terms of Service** (`TermsPage.tsx`) still states only Kael Beta's
      price, "$3 per 1,000,000 input tokens and $10 per 1,000,000 output tokens".
      It was left untouched on the owner's instruction. It needs a wording
      decision that covers Kael Pro Beta's $8 / $25, and the "reasonable
      notice of material changes" promise applies. (2) `/pro/v1/*` was
      removed rather than kept as an alias, so any caller still using it gets a
      404; decide whether a redirect is wanted. (3) Deploy the backend and the
      frontend together: the live database already uses the new names, and the
      deployed backend still writes `"pro"` until synced. (4) Nothing exercises
      a real Kael Pro Beta request end to end yet; run one with a real key after
      the deploy and check the ledger row's `product` and amount.
- [x] **2026-09-28 follow-up (owner decision):** output $4.00 -> $6.00, input
      and cached input unchanged. Changed in `models/kael/config.py`, the
      `billing.py` docstring, `app/page.tsx` metadata, the `HomePage.tsx` price
      card, `TermsPage.tsx`, the new `/pricing` page, and the pinned test
      values (`$8.00` for 1M in + 1M out, `$1.28` for the mixed example).
      `DocsPage.tsx` showed the old prices until it was rewritten (A8). Not
      deployed until the owner syncs the 2026-09-28 zip.
- [x] **Backend, one line:** `backend/app/models/kael/config.py`,
      `customer_price_per_million` -> `{"input": 2.0, "output": 4.0, "cached_input": 0.40}`.
      (Kept the `"standard"` nesting the real config has; the snippet here
      omitted it.) `billing.py`, stats, and `GET /api/config` all read from
      it. Cached is exactly 20% of input, and a new test enforces that.
- [x] Update the code comments that quote the old numbers (for example in
      `billing.py` near the "$1.00 in / $3.00 out" comment, and comments in
      the Kael `config.py`).
- [x] **Frontend text:**
      - `components/pages/HomePage.tsx` pricing card (input, cached, output)
      - `app/page.tsx` metadata description (`$1.00/M in, $3.00/M out`)
      - `components/pages/UsagePage.tsx` top-up estimate (hardcoded
        `selectedTopUpAmount / 1.00`, should divide by the input price)
      - `components/pages/TermsPage.tsx` line stating "$1 per 1,000,000
        input tokens and $3 per 1,000,000 output tokens"
      - The Usage page's "saved vs $5/$15 frontier pricing" comparison still
        holds; leave it.
      - `DocsPage.tsx` was left for A8 (done 2026-10-06).
- [ ] Better long-term: make the frontend read prices from `GET /api/config`
      so there is one source. Optional; not done (the top-up estimate now
      uses one named constant, `KAEL_INPUT_PRICE_PER_MILLION_USD`).
- [ ] **Decide (found while doing B1):** the Usage page's costs
      (`GET /api/stats`) are recomputed from token counts at the *current*
      price, because `usage_logs` stores no cost. After this deploys, past
      requests display at the new price even though they were charged at the
      old one. `billing_ledger` (the real charges) is unaffected. With only a
      few accounts this is cosmetic; the real fix is a stored cost column
      (an AI-DB change). Accept it, or add it to phase C.
- [ ] Existing balances are unaffected (they are dollars); they simply buy
      half as many tokens. Only 2 accounts exist, so no customer notice is
      needed now. Give proper notice once real users exist (Terms promise
      "reasonable notice").
- [ ] Verify after deploy: `GET /api/config` shows the new prices; a real
      request bills the expected amount (D2).

### B2. `sitemap.xml` and `robots.txt`
- [x] Add Next.js `src/app/sitemap.ts` and `src/app/robots.ts` for
      `https://platform.quancis.space`.
- [x] Sitemap: `/`, `/docs`, `/terms-of-service`, `/privacy-policy`, `/login`.
      Note: `/login` is also `noindex`, so Search Console may say "submitted
      URL marked noindex". Delete the `ROUTES.login` line in `sitemap.ts`
      if you would rather avoid that.
- [x] Robots: allow public pages; disallow `/dashboard`, `/keys`,
      `/playground`, `/usage`, `/account`, `/admin`, `/reset-password`; point
      to the sitemap. (`/login` is deliberately not disallowed, or crawlers
      could never see its `noindex`.)
- [ ] Verify by opening both URLs on the live site.

### B3. Delete dead code
- [ ] Delete `frontend/src/data/mockData.ts` (nothing imports it; only two
      comments mention it) and its `ModelBenchmark` type (only it used that).
      **Reverted 2026-09-24 — do not repeat this deletion via a synced zip.**
      Deleting the file broke production: the 2026-09-21 zip deleted the file
      and the type together, but the mobile "Last Sync" flow does not delete
      files that are absent from a synced zip — a file gone from the zip
      just never gets removed from the live repo. The file itself silently
      survived on the live repo with the type gone from under it, and the
      next Vercel build failed on `error TS2305: Module '"../types"' has no
      exported member 'ModelBenchmark'`. This sat broken in production from
      2026-09-22 (the first sync after that zip) until caught and reverted
      here. Both the file and the type are restored, byte-for-byte. To
      actually delete this file, it needs a manual delete in the GitHub repo
      (web UI or a real git client) — not a file simply left out of a zip.
      The two reworded comments (`lib/api.ts`, `context/AppContext.tsx`)
      stayed reworded; they're accurate either way.
- [ ] Run `npm run lint` and `npm run build` to confirm nothing referenced it.

### B4. Interim scheduled checks (instead of Render Cron, which is "Later")
Goal: get billing drift detection now, without new infrastructure. Simple,
knowingly less robust than real cron jobs.
- [x] In `backend/app/main.py`, start one background task at app startup
      (FastAPI lifespan; the code is in `backend/app/scheduled_checks.py`). It waits about 5 minutes after boot (so startup
      is not slowed), then every 24 hours calls the existing
      `billing.reconcile_all_accounts()` (read-only).
- [x] Wrap each run in try/except so a failure can never crash the app; log
      one line: `RECONCILE ok` or `RECONCILE drift <n accounts>`.
- [x] On drift or failure, email the owner using the existing Resend helper.
      New optional env var: `ADMIN_ALERT_EMAIL`. If unset, log only.
- [x] Add an admin-only manual trigger, `POST /api/admin/reconcile`, reusing
      `require_admin` and returning the same result (optional: a button on
      the Admin page). Done, including the button (Admin, Overview, "Run
      check"). A check that cannot run returns 502, not a 200.
- [x] Low-balance alerts: reuse the same loop but gate it behind env var
      `LOW_BALANCE_ALERTS_ENABLED`, **default false**. Turn it on only when
      payments exist (D1). (Superseded 2026-10-13: the email-system update
      made the balance emails default ON at the owner's request; set
      `LOW_BALANCE_ALERTS_ENABLED=false` to turn them off. See `app/config.py`.)
- [x] Add tests for the loop's error handling.
- **Cost: none extra.** It runs inside the existing "Quan AI" web service,
  so there is no new Render resource and no new monthly charge. It works on
  any plan, but on the **free** plan the service sleeps after about 15
  minutes without requests, so it only runs while the service happens to be
  awake (roughly once, about 5 minutes after each cold start) and is not a
  reliable daily check. After the A5 upgrade (an always-on instance) it
  behaves as designed. The manual `POST /api/admin/reconcile` works on any
  plan.
- **Known limits (accepted):** runs only while the web service is awake
  (see above); the timer resets on every deploy; assumes one
  instance (with two, reconcile runs twice, which is harmless, but alerts
  could double-send); failures appear in logs and email, not in Render's
  failed-job notifications.
- When real Render Cron Jobs go live (Later), delete this loop.

### B5. Small cleanups (comments, examples)
- [x] `frontend/src/lib/routes.ts`: the comment above `normalizePathname`
      says `trailingSlash: true` is set in `next.config.ts`. It is not. Fix
      the comment (keep the function).
- [x] `backend/backend.env.example`: `API_KEY_PEPPER` is described as
      optional, but `config.validate()` requires it. Fix the comment. (The
      same wrong claim in `backend/app/config.py` is fixed too.)
- [x] `backend/app/main.py`: the comment above the product routes says
      "There is no Anthropic Messages format support"; the routes below it
      exist. Fix the comment.
- [x] `backend/app/api_keys.py` docstring points at
      `migrations/0001_api_keys_and_user_scoping.sql`, which is not in the
      repo. Repoint to `backend/supabase/README.md`.
- [x] `frontend/src/components/pages/UsagePage.tsx` comment references the
      deleted `HANDOVER-real-data-migration.md`. Reword.
- [x] Optional: show `by_product` from `GET /api/stats` on the Usage page.
      Already implemented (the Usage page renders `usageByProduct`); this
      item was stale.

### B6. Hero boxes react to the pointer over the text — DONE, needs sync
Fixed in `frontend/src/components/three/HeroCanvas.tsx`. Cause: pointer
listeners were on the canvas wrapper, which sits behind the hero content, so
events over the headline, paragraph, buttons or nav never reached it. The
listeners are now on `window` with a bounds check against the hero. Nothing
calls `preventDefault`, so scrolling, clicks and text selection are
unchanged. Old behavior of ignoring links/buttons was dropped on purpose so
there are no dead spots.
- [ ] After the sync, verify on the live site:
      - Desktop: move the mouse slowly across the headline, the paragraph,
        the buttons and bare background. The lift follows everywhere.
      - Mouse out of the hero or out of the window: the lift fades away.
      - Phone: tap and start dragging on the text; boxes react. Then scroll
        the page with a finger that starts on the text; scrolling still works.
      - Buttons and links still click; text can still be selected.
      - Hero scrolled off screen: no reaction.
- [ ] `npm run lint` and `npm run build` (the edit was only syntax and
      DOM-type checked without `node_modules`; a real build was not run).

### B7. Dedicated `/pricing` page (2026-09-28, owner request)
- [x] `PricingPage.tsx`, `app/pricing/page.tsx`, `ROUTES.pricing`, sitemap
      entry, a "Pricing" nav link (logged-in and logged-out), and a link to
      it from the HomePage price card. Comparison table: Kael Beta vs GPT-6
      Astra, GPT-6 Sol, Claude Opus 5.5, Claude Fable 5.1, Kimi K3.
- [ ] Verify on the live site after the sync: `/pricing` loads, `/sitemap.xml`
      lists it, the nav link works, the table scrolls sideways on a phone.
- [ ] **Competitor prices go stale by themselves.** They are dated
      2026-09-28 in the page copy. Anthropic and OpenAI rows were read from
      their own pricing pages; Kimi K3 from trackers citing Moonshot's page
      (Moonshot's page was not opened). Re-check every few weeks, or whenever
      a provider reprices, and update the `COMPARISON` array and the date.
- [x] **2026-09-28, owner decision:** the "free" framing is gone. Every
      "Try Kael Beta For Free" CTA (hero, price card, closing section on
      HomePage; both on `/pricing`) now says "Create An Account". The
      deposit-match banner on HomePage's price card ("100% deposit match...
      while Quancis is in beta") is deleted outright — the owner confirmed the
      100% match is not coming back, not just paused. The still-true
      underlying fact (a new $0 account gets a 402 until it deposits, and
      there is no payment processor yet, A6) is unchanged; the copy no longer
      contradicts it.

---

## Phase C — Database (AI-DB via Supabase MCP; production writes, "go" per step)

Do these in order. After each, re-run `get_advisors` and note the result in
`STATUS.md`.

### C1. RLS deny-all policies (clears 8 advisor INFO notices)
Why safe: the frontend only calls `supabase.auth`; all table access is by
the backend's service-role key, which bypasses RLS. So a deny-all policy
for the browser roles changes nothing in practice; it only makes the
intent explicit.
- [ ] One migration, for each of: `api_keys`, `billing_accounts`,
      `billing_ledger`, `chat_debug_traces`, `chat_messages`, `chat_sessions`,
      `legal_acceptances`, `usage_logs`:
      `create policy "deny all client access" on public.<table> for all to anon, authenticated using (false) with check (false);`
- [ ] Do **not** add per-user policies. That would open the tables to
      browsers for no benefit.
- [ ] Optional second lock: revoke table privileges from `anon` and
      `authenticated` on these tables. Only after confirming nothing else
      relies on them.
- [ ] Verify: `get_advisors` (security) no longer lists the 8 INFO items;
      the leaked-password WARN remains. Smoke test: sign in on the live
      site, open the dashboard, send one Playground message.

### C2. Explain the legacy balances (depends on your answer to A2)
- [ ] If you chose option 1: insert one `adjustment` row per account into
      `billing_ledger` (columns: user_id, product = null, kind =
      'adjustment', amount_usd = the unexplained difference,
      balance_after_usd = the account's current balance, description =
      'Legacy $5 signup credit (removed 2026-09-02)'). Do not change
      `billing_accounts`; the balances are already correct. Confirm the
      table shape before running.
- [ ] Verify: run the reconcile check once (Admin page, Overview, "Run
      check", or by running `python -m app.jobs.reconcile_billing` somewhere
      with the env vars). Expect zero drift. Only after this is clean, set
      `ADMIN_ALERT_EMAIL` (B4), or the daily check re-alerts about the two
      legacy balances every run. This is also the first live test of the
      billing functions.

### C3. Schema snapshot, then delete applied migration files
The snapshot must exist before any file is deleted, because these files
are the only human-readable record of the schema.
- [ ] Generate `backend/supabase/schema.sql` from the live catalogs via
      `execute_sql` (tables, columns, constraints, indexes, RLS flags and
      policies, function bodies via `pg_get_functiondef`, triggers). There is
      no `pg_dump` through the MCP tool, so cross-check table and column
      counts against the live database. Header: generated on <date> from the
      live project.
- [ ] Delete every applied file in `backend/supabase/migrations/`
      (0002 through both 0008s), plus `0006_admin_bootstrap.sql` (a one-off
      data write; the pattern is kept in `backend/README.md`, "Admin").
      Git history keeps all of them and their explanatory comments.
- [ ] From then on: `migrations/` holds only **unapplied** files. After
      applying one, regenerate `schema.sql` and delete the file.
- [ ] Rewrite `backend/supabase/README.md` to describe that final convention.
- [ ] Update `AGENTS.md` (repo map) and `STATUS.md` to match.

---

## Phase D — Before launch (mix of owner and AI)

### D1. Payments (after A6)
Build (AI-CODE, plus your dashboard setup):
- [ ] Checkout flow from the Usage page top-up UI (replace the "Coming Soon"
      stub).
- [ ] A webhook route that **verifies the processor's signature**, then
      calls the existing `credit_balance()` function (it writes a `deposit`
      ledger row atomically).
- [ ] **Idempotency:** processors retry webhooks. The ledger has no unique
      external-payment reference today, so add one (migration) and reject
      duplicates, or a retry will credit twice.
- [ ] Refunds and disputes: write `adjustment` rows; decide the policy.
- [ ] Minimum and maximum top-up; receipts/invoices.
- [x] ~~Turn on `LOW_BALANCE_ALERTS_ENABLED` (B4) once this works.~~ Already on by default since 2026-10-13
      (email-system update); revisit only if the owner wants it off until payments exist.
- [ ] Test in the processor's test mode end to end: pay, webhook, balance,
      ledger, API request, deduction.

### D2. First real end-to-end test (the database shows zero logged requests)
- [ ] After each significant deploy: sign up, confirm the email, log in,
      create an API key, make one non-streaming and one streaming call to
      `/v1/chat/completions`, and one from the Playground.
- [ ] Check in the database: a `usage_logs` row, a `chat_debug_traces` row,
      a `billing_ledger` usage row, and a balance that dropped by the
      expected amount at the new price.
- [ ] Repeat once via `/v1/responses` and `/v1/messages` (Anthropic shape).

### D3. Legal text review (I am not a lawyer; have someone qualified check)
- [x] **2026-10-13: Terms of Service (24 sections) and Privacy Policy (17
      sections) rewritten in full** to match what the app does: Lemon Squeezy
      as Merchant of Record, a 14-day refund of unused credits, credits are
      not money (no cash value, not withdrawable or transferable, only usable
      on Quancis), 12-month expiry enforced in code (`app/credit_expiry.py`),
      Kael Beta and Kael Pro Beta prices, the Playground/API difference, the
      30-day diagnostic retention, account deletion by button, no personal
      Gmail, no "15 minutes" claim, no promo text. The pipeline that produced
      them is not in the repo; the pages are `TermsPage.tsx` and
      `PrivacyPage.tsx`.
- [ ] Have a South African lawyer read both documents, starting with
      `LEGAL_UPDATES.md` ("For your lawyers"), which lists the decisions
      taken by default and the points that need a professional view.
- [ ] **Safety screening must exist before launch.** The Terms and Privacy
      Policy describe it in the present tense (automated screening, flagged
      content kept until reviewed and up to 90 days after enforcement, account
      paused during review). There is no screening code in this repo, and
      `chat_debug_traces` refuses to store API text (migration 0010). Build it,
      including a place to keep flagged content, or change both documents.
- [ ] Re-read both documents against the code after any change to retention,
      deletion, expiry, providers or prices. Change `TERMS_VERSION` and
      `PRIVACY_VERSION` in `backend/app/config.py` and the "Last updated" date
      on both pages together on the day you publish.
- [ ] Refund wording must match what the build in D1 can do (refund removes the
      credits; late credits after a refund are removed).

### D3b. Roll out the 2026-10-13 changes (owner steps, in this order)
- [x] Migrations `0016` and `0017` were applied on 2026-10-15.
- [ ] Sync the zip (a sync is a deploy). Render rebuilds the backend because
      files under `backend/` changed.
- [ ] Run the smoke test (D2) with the new code: one Playground message, one API
      call. `data_collection: "deny"` can make a request fail with 503 if no
      provider for a model meets the rule; if that happens, read the router's
      error and either pick another provider list or turn the rule off briefly
      (`UPSTREAM_REQUIRE_NO_DATA_COLLECTION=false`) knowing the Privacy Policy
      then says something untrue.
- [ ] Check the router account's own privacy settings (no logging of prompts or
      answers).
- [ ] Make a throw-away account, add credit as admin, delete the account from the
      Account page, and confirm in Supabase that its rows are gone.
- [ ] Run `POST /api/admin/expire-credits` once (dry run) and read the result.
- [x] The three old ledger rows that held an email address were rewritten on
      2026-10-15.

### D4. Publish the new Docs (A8) and re-check them against the price.
The docs read price and limits from `components/docs/facts.ts`; compare it
with `models/kael/config.py` and `rate_limit.py` before publishing.

### D5. Final checks
- [ ] Render plan upgraded, notifications on, health check green (A5).
- [ ] `STATUS.md` re-verified the same day.
- [ ] Advisors: only the leaked-password WARN remains.

---

## Later (parked, not started)

### Render Cron Jobs (replaces the interim loop in B4)
When: after launch traffic exists, or when you want failure alerts through
Render itself.
- [ ] Create two Render cron jobs on the same repo: `BCR-MVP`, branch
      `main`, root directory `backend`, runtime Python, build
      `pip install -r requirements.txt`, region same as the web service.
      - `reconcile_billing`: start command
        `python -m app.jobs.reconcile_billing`, daily (for example
        `0 3 * * *`, 03:00 UTC). Exit code 0 = clean, 1 = drift, 2 = could
        not run; Render marks nonzero runs as failed and notifies you.
      - `low_balance_alerts`: start command
        `python -m app.jobs.low_balance_alerts`, daily (for example
        `0 7 * * *`). Only create this once payments exist.
- [ ] Env vars: cron jobs do **not** inherit the web service's variables.
      Copy in `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`; for alerts also
      `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `FRONTEND_URL`. An AI can create
      the jobs through the Render tool but cannot read secret values, so you
      paste the secrets in the Render dashboard.
- [ ] Cost: billed separately from the web service (I believe about $1 per
      month minimum each; check the plan shown when creating).
- [ ] Then remove the interim loop (B4) and update `backend/app/jobs/README.md`.

### Other parked items
- Shared rate-limit store, if the backend ever runs on more than one
  instance.
- Leaked-password protection, when the Supabase plan allows it.
- Move frontend pricing to `GET /api/config` (B1, optional).
