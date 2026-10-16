# HISTORY — dated changelog of renames, removals and reversals

Read this to understand why the code looks the way it does. Current
behavior is in `README.md`; do not learn current behavior from here. Dates
are `YYYY-MM-DD`. Detailed reasoning for any change lives in code
comments at the relevant file and in git history.

## Products and names
- **2026-08-19** "Quan Pro" renamed to **Kael Beta** (customer-facing slug,
  label, tagline, system identity only). The internal key stayed `"pro"`
  and the API key prefix stayed `sk-quan-`, because live rows and issued
  keys depend on them. Old model names `quan-pro` and `quan-4` stayed as
  aliases. The "Flash" tier was deleted outright the same day.
- **2026-08-20** Folders and files renamed: `models/quan_pro/` to
  `models/kael/`, `proxy.py` to `kael_pipeline.py`, `critic/pro.py` to
  `critic/kael.py`. Pure rename.
- **2026-08-30** System identity now says "Quancis" (from Quán, "whole",
  plus CIS, Composite Intelligence System). "CAIS" wording retired.
- **2026-08-19 to 2026-09-08** A second product, **Aura Beta** ("ultra",
  OpenAI draft plus DeepSeek critic), existed. **Removed 2026-09-08**:
  folder, pipeline, critic prompt, routes, config and env vars. Its old DB
  rows were left untouched; a few read-only display paths still label
  `"ultra"`.

- **2026-10-08** **Kael Beta split into two models: Kael Beta and Kael Pro
  Beta.** Kael Pro Beta (`kael-pro-beta`) is what the `z-low` / `z-high`
  tiers always were, now a model of its own at its own price ($8.00 input /
  $1.60 cached / $25.00 output per 1M tokens; Kael Beta stays $3.00 / $0.60 /
  $10.00). Each model accepts only its own tiers. This is the first time the
  z tiers were billed at a z price: before, they ran on Kael Beta and billed
  at Kael Beta's. The two models share one `_SHARED` settings block in
  `models/kael/config.py`; only identity, tiers and price differ.
- **2026-10-08** **The internal key `"pro"` was renamed, reversing the
  2026-08-19 decision to keep it.** A model's key is now its public slug
  (`kael-beta`, `kael-pro-beta`). The 2026-08-19 reason (live rows depended on
  the key) no longer held: the owner confirmed everything in the database was
  test data. Migration `0012_kael_beta_split.sql` renamed every stored
  `pro` / `quan-pro` value to `kael-beta` in `usage_logs`, `billing_ledger`,
  `chat_debug_traces` and `chat_sessions.model`, and reset `api_keys.scopes`.
  The aliases `quan-pro` and `quan-4` were **removed**, not just unused: a
  request naming either now returns `400 model_not_found`. The `/pro/v1/*`
  routes were **removed** (they are replaced by `/kael-beta/v1/*` and
  `/kael-pro-beta/v1/*`), so a caller still on `/pro/v1` gets a `404`.
- **2026-10-08** Retired the direct-DeepSeek playground option: migration
  `0012` deleted the 11 conversations (25 messages) that were created on
  `deepseek-v4-flash`. They could be read but not continued, and the app no
  longer offers that model.

## Architecture changes
- **2026-10-08** Per-key thinking level. Agents such as Cursor cannot send
  `reasoning_effort`, so each API key can pin a tier from the dashboard
  (`api_keys.thinking_level`, migration `0013`, `PATCH /api/keys/{id}`). NULL =
  "SDK" = the request decides (unchanged for every existing key). A pinned
  tier overrides the request and the request's value is not validated.
  Added alongside the model split, so a pinned tier applies only on the model
  that offers it (`low`/`high`/`max` on Kael Beta, `z-low`/`z-high` on Kael
  Pro Beta); on the other model the key behaves as "SDK".
  `z-low`/`z-high` are pinnable too. The API Keys page's "Last used" column was
  replaced by this setting (last used is still in View Details). Tests:
  `backend/test_key_thinking_level.py`.
- **2026-10-08** Customer-facing text no longer explains how Kael works.
  The docs page "How Kael works" became "About Kael" (`/docs/about`;
  `/docs/how-it-works` redirects) and keeps only what to expect, when to
  choose Kael and safety screening; the draft/review wording was removed from
  the other docs pages and the console. The stream's filler titles were
  reworded (`app/thinking_fillers.py`, `lib/thinkingFillers.ts`); the old
  wording is still recognised as filler so saved chats clean up the same way.
  The public Pricing page and docs now show two rates (low/high/max at
  $3 / $0.60 / $10, z-low/z-high at $8 / $1.60 / $25) instead of "one price".
  Billing still charges every tier at the standard rate.
- **2026-10-08** Thinking tiers and the fusor. (1) `reasoning_effort` is now a
  **tier name** with its own per-pass efforts, from one table
  (`reasoning_tiers` in `models/kael/config.py`): `low` = draft high + critic
  low; `high` = high + high; `max` = max + max. **Behavior change:** before,
  one effort applied to both passes, so the default `low` drafted at low; it
  now drafts at high, which is slower on the default path (measure P90).
  `draft_reasoning_effort` was replaced by `default_reasoning_tier`. (2) New
  tiers `z-low` / `z-high`: three concurrent drafts, a **fusor**
  (`app/fusor/`) that merges them into one new answer, then the unchanged
  critic. Five calls; billing rule unchanged (first call's input, last call's
  output), so the extra calls are absorbed cost and the docs' higher z price
  is **not** implemented yet. (3) There is no `off`; the frontend docs that
  listed it were corrected. (4) Thinking titles gained a "fusing" phase.
  Tests: `backend/test_z_tiers.py`. The in-app Playground still sends only
  low/high/max.
- **2026-10-08** Thinking-title summarizer moved off the draft pass's model
  and speed-first routing onto its own cheap-first list: Ling 3.0 Flash,
  then DeepSeek V4.1 Flash as the last resort (OpenRouter `models` fallback
  array, `provider.sort: "price"`, soft latency preference at p50). Ling 3.1
  Flash was considered and left out (free launch promotion). Reason: one
  heavy request had made 222 upstream calls (2 real passes plus ~220 title
  calls) for about $0.30 of cost against $0.51 billed, and most of the title
  calls' cost was input tokens. Config: `summarizer_models` and
  `summarizer_provider_routing` in `app/models/kael/config.py`.
- **2026-10-06** Privacy and naming. (1) API prompts, drafts and answers are no
  longer written to `chat_debug_traces`; only `app_chat` (Playground and Chat)
  keeps text. Before, every request stored the last user message and 1,500-char
  previews whatever its source. Rows already stored are erased by
  `supabase/migrations/0010_api_prompts_never_stored.sql`.
  (2) The dashboard's request table showed the stored upstream model ids
  (`<draft>+<critic>`, including older GLM rows); it now always says
  `kael-beta`. (3) Upstream error bodies were passed to callers as-is, leaking
  host names, model ids and account links, and an upstream 401/402 looked like
  the caller's own bad key or empty balance; they are now fixed generic bodies
  and a 401/402/403 becomes a 503 (not retried on the backup host). Upstream
  error text is also no longer stored or logged, since it can quote the
  caller's prompt; only status, code, type and host name are. (4) A failed balance deduction was silent
  and invisible to reconcile; it now logs `CHARGE_FAILED`. (5) Non-streaming
  Chat Completions dropped text written next to a tool call. (6) A non-string
  `model` or non-object `reasoning` returned 500; now 400. (7) A delivery had
  silently restored the 19:04 `models/kael/config.py`, its README and the
  `kael_pipeline.py` docstring over the 22:52 versions, putting the draft back
  on GLM; the 22:52 versions (DeepSeek V4.1 Flash for both passes) are restored.
- **2026-10-06** Thinking-title stream fixes. Titles now also read OpenRouter's
  `reasoning` / `reasoning_details` fields (only `reasoning_content` was read);
  the summarizer sends its own `session_id`, retries once on transient errors
  and can no longer raise through `stop()`. `ThinkingRelay.stop()` used to wait
  up to 20 s (plus one more summarizer call) before every terminal event; it is
  now quick, never raises, and the stream-end and rate-limit cleanup always
  run. Summarizer calls take turns (they used to overlap, reordering titles and
  repeating context) and stop when the client disconnects. A critic failure
  after the critic had started answering used to append the whole draft after
  the partial answer (the check read the draft pass's flag, always false); it
  now sends an error. Reasoning text and titles go through `identity_guard`.
  Filler words are no longer saved or counted as steps, and the in-app chat
  saves the titles the relay actually sent (the last ones could be missing
  because the save ran before the stream consumer caught up). Titles end with
  a blank line on the wire; Anthropic thinking blocks close with a
  `signature_delta`. The draft/critic passes still run to completion after a
  client disconnect (they are billed; cancelling would hand out free compute).
  The live "Thinking · N steps" count in the in-app chat also skips filler words
  (frontend/src/lib/thinkingFillers.ts mirrors backend/app/thinking_fillers.py).
- **2026-10-05** The draft model changed from `z-ai/glm-5.3-flash` to
  `deepseek/deepseek-v4.1-flash`; GLM 5.3 Flash was removed from the Kael
  config and docs, so draft and critic are now the same model. Both passes
  keep speed-first routing (`sort: throughput`, soft p90 2 s latency
  preference), and the draft's `max_price` ceiling moved to $0.30 / $1.20
  per 1M tokens to match. The 480 s generation hard ceiling is unchanged.
- **2026-10-04** In-app chat persistence changed (`app/main.py`,
  `app/chat_history.py`, `supabase_client.py`). Before: the user message was
  saved first, so any failed send left it orphaned and the next turn sent two
  user messages in a row; the history read had no limit, so past 1,000 rows
  the newest messages dropped out, and a failed read looked like "no
  messages"; no size caps; a failed lookup was reported as 404. After:
  user message and reply are saved together on success, history is windowed,
  reads fail loudly (503), sends are one-at-a-time per chat. Existing
  orphaned rows are left in place; the history builder merges them.
- **2026-08-19** Backend became JSON-only. The Jinja2 dashboard and an
  internal admin chatbot were deleted; the frontend became a separate
  project. `GET /api/config` was added for frontend bootstrap.
- **2026-08-19** An Anthropic proxy was deleted (no need then).
  **2026-09-09** Anthropic Messages support was added back as a new module
  (`anthropic_api.py`) on the shared architecture. Any doc saying "no
  Messages format" predates this.
- **2026-08-20** Kael rebuilt on the Responses-shaped internal
  architecture. `response_api.py` and `two_pass_pipeline.py` were lifted
  out of two divergent per-product pipelines, so a bug is fixed once.
  Responses API support added for callers.
- **2026-08-20** Tool-call drafts are now reviewed by the critic (before,
  a tool-call draft skipped it). The `usage` shown to callers was changed to
  equal the billed figure.
- **2026-08-20 to 2026-08-26** Raw reasoning was streamed to callers, then
  reverted (no real client reads it). Replaced by transport-level SSE
  keep-alives.
- **2026-08-23** Real admin backend added (`admin.py`, `require_admin`),
  replacing a fully mocked admin page with a fake "grant admin" button.
- **2026-08-24** Layered identity: caller system prompts are tagged
  `<caller_system_prompt>`, and the real date is injected.
- **2026-08-31** Upstream switched to **OpenRouter** for both passes
  (draft `z-ai/glm-5.3-flash`, critic `deepseek/deepseek-v4-flash-0731`,
  pinned to Relace). Before that Kael called its providers directly. (DeepSeek's
  own 2026-08-16 move to peak/off-peak pricing stopped mattering after
  this switch.)
- **2026-09-09** Thinking-title summarizer added (`thinking_summarizer.py`).
- **2026-10-05** Provider routing made **speed-first**: the Relace pin
  (`order: ["relace"]`) is gone; both passes now sort by throughput under a
  hard price ceiling with a 2 s p90 latency preference, and every upstream
  call carries a `session_id` for prompt-cache stickiness. Critic model
  moved from `deepseek-v4-flash-0731` to `deepseek-v4.1-flash`. See
  `app/provider_routing.py`.
- **2026-10-09** `provider.ignore: ["relace"]` was added to the draft, critic
  and fusor routing in `models/kael/config.py` (`_SHARED` since the model
  split), so the Relace host is never used. The reason was not recorded when it
  was added. It is a standing exclusion, not a pin: `order` and `only` are still
  banned. Whether `ignore` affects OpenRouter's sticky cache routing is not
  documented; check the cached-token share in the traces if the bill rises.
- **2026-10-09** Silent failover for mid-stream upstream failures. A pass
  that ends with `finish_reason: "error"` before anything reached the caller
  is re-run once with the failed host in `provider.ignore`; the caller hears
  only if the re-run fails too. The `error` object's code / error_type / host
  are now captured (they were thrown away, so traces only said "content-level
  failure"). Each attempt has its own 480 s ceiling. Failure trace rows now
  record `chunks_from_upstream` and `reasoning_char_count`. Also: a non-stream
  response with an `error` object is now a failed pass instead of an empty one.
- **2026-10-05** Backup host added (owner's choice: Baseten). When OpenRouter
  refuses a pass with a no-provider status (404/503), the pass is retried
  once pinned to `baseten` with the same `max_price`; the price ceiling is
  never relaxed. A second refusal gives the caller the clean 503 as before.
- **2026-10-01** Thinking titles reworked: chunking is now size-driven
  (was time-only, so chunk size varied with provider speed); the draft pass's
  answer text now also produces titles (it used to produce only filler
  words); fillers follow the phase; the relay goes quiet once the critic's
  answer starts (before, a late title or filler could be emitted in the middle
  of the answer); summarizer request reordered for prompt caching.
- **2026-09-13** Difficulty router added (EASY skips the critic). Per-user
  rate limits and a concurrency cap added for product endpoints.
- **2026-10-03** Per-user product limits set to 150 requests/min and 30
  concurrent (were 30/min and 3).
- **2026-10-03** The 2026-10-01 thinking-title rework was only half wired:
  the relay and its tests existed but the streaming pipeline never fed it the
  draft's text, never stripped the routing tag from it, and never told it the
  answer had started. Wired now (including on a critic tool call).
- **2026-10-03** Responses endpoint: typed input items and the top-level
  `instructions` field were passed through raw / ignored. Now converted by
  `responses_input_to_messages()`.
- **2026-10-03** Anthropic streaming: `message_delta` now carries the billed
  `input_tokens` (`message_start` is sent before the draft reports its usage,
  so it could only say 0).
- **2026-09-15** Hardening pass: pre-auth IP throttle, `config.validate()`
  at startup, connect-only retry logic on upstream calls (plus error
  translation for streamed failures), identity-leak regex backstop, PII
  scrubbed from the repo (admin email and project refs removed because the
  repo is shared with contractors), dead `critic_reasoning_effort` field
  removed, stale "default effort is max" comments fixed (default is `low`,
  reverted from `max` for latency).
- **2026-09-15 / 2026-09-18** Cron-style job scripts written
  (`reconcile_billing`, `low_balance_alerts`); neither is scheduled.
- **2026-09-21** `app/scheduled_checks.py` added as a stopgap: a daily
  in-process billing reconciliation started from `main.py`'s `lifespan`,
  plus `POST /api/admin/reconcile`. `low_balance_alerts.py` was split into
  `run_once()` and `main()` so the loop can reuse it (command-line behavior
  unchanged). To be removed once a Render Cron Job runs the jobs.

## Billing and data
- **2026-10-08** Kael Beta repriced in code to $3.00 in / $10.00 out /
  $0.60 cached-in per 1M tokens (owner decision), from $2.00 / $6.00 /
  $0.40. Cached is still exactly 20% of input. Reason: aim for roughly 80%
  gross margin and compete on reliability, not on being the cheapest. The
  public docs also quote the planned `z-low` / `z-high` levels at $8.00 in /
  $25.00 out ($1.60 cached), changed from $6 / $15 the same day; the code
  has no z levels or z billing yet. `billing_ledger` rows keep what was
  actually charged, but the Usage page recomputes costs at the current
  price, so past requests show at the new price.
- **2026-10-03** Output price in code corrected to $6.00 (it still read
  $4.00 after the 2026-09-28 decision, so output was under-billed).
- **2026-10-03** Billed and shown input now excludes Kael's injected prompt
  text (estimated, see README "Billing"). `usage_logs` rows now record
  billed token counts instead of both calls' summed usage, so the Usage page
  matches charges; unbilled failed requests log zero tokens. Raw upstream
  spend is no longer stored (the upstream provider's dashboard has it).
- **2026-08-15** Billing tables and functions (`deduct_balance`,
  `credit_balance`) created.
- **2026-09-02** The automatic $5 signup credit was removed; new accounts
  start at $0. (Two pre-existing accounts still hold that credit; see
  `../STATUS.md`.)
- **2026-09-08** Deposit-match promo (100% match) ended by its own date
  constant. Intentional; kept as a record.
- **2026-09-20** Column defaults fixed: `api_keys.scopes` default dropped
  the removed product; `billing_accounts.balance_usd` default synced to $0.
- **2026-09-21** Kael Beta repriced in code to $2.00 in / $4.00 out /
  $0.40 cached-in per 1M tokens (decided 2026-09-20), from $1.00 / $3.00 /
  $0.20. Earlier: 2026-09-01 $1.50 / $4.00 / $0.15 became $1.00 / $3.00 /
  $0.20, when cached input was fixed to exactly 20% of input to match the
  billing math. `billing_ledger` rows keep what was actually charged, but
  the Usage page's cost figures are recomputed from token counts at the
  current price (see `supabase_client.fetch_stats`), so past requests show
  at the new price after a repricing.
- **2026-09-28** Output price raised $4.00 -> $6.00 per 1M tokens (owner
  decision). Input $2.00 and cached input $0.40 unchanged, so cached is still
  exactly 20% of input. Reasoning: worst-case upstream cost is $0.65 in /
  $1.65 out, so $2/$6 is about 3.1x / 3.6x that.

## Frontend
- **2026-09-28** Removed all "free" framing (owner decision: the 100%
  deposit-match promo is over for good, not just paused). Every "Try Kael
  Beta For Free" CTA (HomePage hero, price card, closing section; both on
  `/pricing`) now reads "Create An Account". Deleted the "100% deposit
  match... while Quancis is in beta" banner from HomePage's price card
  outright. Terms of Service Section 7 rewritten to say no promotion is
  currently active, instead of describing the ended one as current.
- **2026-09-28** Added a public `/pricing` page (price card plus a comparison
  table against GPT-6 Astra/Sol, Claude Opus 5.5, Claude Fable 5.1, Kimi K3),
  a "Pricing" nav link, and a sitemap entry.
- **2026-09-21** Added `sitemap.ts` and `robots.ts`. The Admin page gained
  a "Run check" button for the billing reconciliation.
- **2026-09-21, reverted 2026-09-24** `src/data/mockData.ts` and its
  `ModelBenchmark` type were deleted, then restored: the mobile sync flow
  doesn't delete files absent from a zip, so the file silently survived in
  production with its type gone, breaking the Vercel build (`TS2305`) from
  2026-09-22 until this was caught and reverted. See `PLAN.md`'s B3 for the
  full account.
- **Undated, before 2026-09-20 (four rounds)** Full visual redesign to a new design system,
  a Three.js hero, restyled console pages, then a bug sweep. Details are
  now in `../frontend/README.md`.

## Playground conversations
- **2026-10-06** Playground conversations: fixed replies with thinking
  titles failing to save (`PGRST102`, bulk-insert rows had different keys;
  seen in Render logs 2026-10-05 20:04 and 21:21 UTC), with a retry that drops
  the thinking titles. Product wording is now "conversation" (UI, errors,
  default title "New conversation"); routes and tables keep their old names.
  Empty conversations left by a failed first send are hidden and purged after
  7 days. The live reply stream sends no-buffering headers, `HEAD /api/health`
  is accepted, and the frontend batches streamed tokens and resets playground
  state on sign-out. Optional migration `0011` sets the new default title in
  the database; nothing depends on it.

## z-tier fallbacks
- **2026-10-10** z-low / z-high: the EASY shortcut now needs all three drafts
  back, whole, rated EASY and alike (before: only the survivors had to say
  EASY, so one lone EASY draft, or three EASY drafts that disagreed, was served
  unreviewed). A lone survivor is always reviewed. When the fusor fails the
  critic gets the consensus draft instead of the first one, and cut-off drafts
  are never chosen over whole ones. A draft or fusor that fails fast with a 429
  or 502 is tried once more (a z-only exception to "never retry a received
  response"; `Z_RETRY_STATUSES`). "z DEGRADED" log lines. Tests in
  `test_z_tiers.py`.

- **2026-10-11** z-low / z-high, round two. A third draft that is far behind
  is cancelled once two drafts are back whole (grace: half the second draft's
  time, 15 to 90 s; no deadline with fewer than two whole drafts). The thinking
  titles move to the draft furthest along when the leading draft ends, instead
  of going quiet until the fusor starts (`ThinkingRelay.source_changed()`). A
  plain bug in one draft no longer fails the request when another draft
  succeeded. The trace's `draft_status` now ends in `_x<took part>of<fired>`.
  The public docs and the www site had said a request gets 8 minutes: 480 s is
  per stage, and a request has two or three, so both now recommend a 30 minute
  client timeout instead (`timeoutMinutes` became `clientTimeoutMinutes`).
  Deliberately NOT done: encoding the drafts as diffs for the fusor, an
  overflow guard, skipping fusion for identical drafts, per-request cost
  tracking.

## Pictures and admin self-credit
- **2026-10-12** The Playground and Chat accept pictures (up to 4 per message,
  20 per conversation), and an admin can add any amount to their own balance.
  Pictures go to the model as `image_url` parts; stored in the new table
  `chat_message_images` (migration `0015`, applied 2026-10-12), fetched
  lazily through `GET /api/chat/sessions/{id}/images/{image_id}`. Kept in
  Postgres rather than Storage for one table and automatic cleanup. A hard
  per-conversation cap keeps the prompt prefix stable for the provider's prefix
  cache. Admin credit now allows the caller's own account: labelled "Admin
  self-credit" in the ledger and kept out of the deposit-match promo. Tests in
  `test_chat_images.py`.

## Attached text files and voice typing
- **2026-10-14** (frontend, plus one prompt paragraph) **PDF and Word (.docx)
  attachments**, read entirely in the browser with no library
  (`frontend/src/lib/docs/`): a forgiving PDF reader (scans for objects instead of
  trusting the xref table, object streams, Flate/ASCII85/RunLength filters,
  font encodings and ToUnicode maps, text positions, columns, rotated pages,
  repeated headers and page numbers dropped, `[Page N]` markers) and a Word reader
  (headings, nested lists, tables, links). Scanned and password-protected PDFs
  are refused with a reason. A document longer than one attachment (60,000
  characters) is cut at a page or paragraph boundary and the cut is named in the
  block (`report.pdf (pages 1-18 of 300)`). Nothing is uploaded and the backend is
  unchanged except the paragraph in `system_identity` (cache miss once again on
  deploy). Also: unsent attachments are dropped when another chat is opened;
  a divider in the chat shows where Kael's view starts once a conversation passes
  the history budget (`lib/historyWindow.ts`, mirrors `build_model_messages`,
  cross-checked on 400 random conversations); the settings panel lost its
  explanatory paragraphs. Tests: `npx tsx scripts/test-docs.ts` from `frontend/`.
- **2026-10-14** (frontend only) HTML code blocks in Kael's replies have a
  Preview button (`frontend/src/lib/htmlPreview.ts`, `HtmlPreviewModal` in
  `PlaygroundPage.tsx`): sandboxed iframe, scripts allowed but no same-origin,
  and a CSP that blocks network requests and forms. HTML only.
- **2026-10-14** The Playground accepts text and code files and has a
  microphone button. **Files:** the browser reads the file and puts its text in
  the message as `<attached_file name="...">` blocks, typed text last; no
  database change, no new route (`app/chat_files.py` checks and measures the
  blocks, `frontend/src/lib/textFiles.ts` writes and reads them). Limits: 3
  files per message, 60,000 characters per file, 80,000 per message, 240,000 per
  conversation (attached text is resent every turn). A file cannot close its own
  block (the browser rewrites literal tags, the server refuses tags that do not
  pair up) and `system_identity` says block contents are data, never
  instructions; editing it changes the prompt prefix once, so the first request
  after a deploy misses the upstream cache. Titles ignore the blocks.
  **Voice:** `POST /api/chat/transcribe` takes the raw recording, sends it to
  OpenRouter's `/api/v1/audio/transcriptions` (`TRANSCRIPTION_MODEL`, default
  `openai/whisper-large-v3`) and returns `{text}`; the page puts the text in the
  message box to edit and send. The audio is not sent to Kael, not stored and
  not logged. Text is in the language spoken (no translation). Quancis absorbs
  the cost (priced per second of audio, about $0.11 per hour on OpenRouter's page
  on this date); it needs a signed-in account with a balance and is limited to
  20 clips per 10 minutes per user. Clips are capped at 2 minutes and 5 MB
  (OpenRouter's providers time out at 60 s). Tests: `test_chat_files.py`,
  `test_transcription.py`. Not run against the real upstream or on an iPhone.

## Legal rewrite, retention and credit expiry (2026-10-13)
- **2026-10-13** The Terms of Service and Privacy Policy were rewritten in full
  for the Lemon Squeezy application, and the code was changed so that what they
  say is true. Owner decisions, in the order they were taken:
  - **Promo code removed.** The deposit-match promotion ended 2026-09-08; its
    code (`DEPOSIT_MATCH_*`, `deposit_match_bonus`, the `PROMO_MATCH_ENABLED`
    switch, the `is_deposit` flag of `billing.admin_credit_account`) is gone.
    Ledger rows it wrote stay as history. The Terms no longer have a Promotions
    section.
  - **Credits expire after 12 months, and it is enforced.** `app/credit_expiry.py`
    replays the ledger first-in-first-out once a day (`scheduled_checks.py`) and
    records expiries through the `expire_credits` database function (migration
    `0017`). The owner knows South African consumer law (CPA section 63) has a
    longer rule for prepaid credits and chose 12 months anyway, on condition the
    Terms are clear that credits are not currency. Kill switch:
    `CREDIT_EXPIRY_ENABLED`. Admin dry run: `POST /api/admin/expire-credits`.
  - **Diagnostic records are deleted with the conversation and at 30 days.**
    `chat_debug_traces.session_id` (cascade) and `purge_expired_chat_traces()`
    (migration `0016`). Before this, deleting a conversation or an account left
    the truncated message and answer excerpts behind, with no expiry.
  - **Account deletion exists:** `DELETE /api/account` (`app/account.py`) and a
    section on the Account page. It removes the rows that survive deleting the
    auth user (`chat_debug_traces`, `usage_logs`, both `ON DELETE SET NULL`).
  - **Upstream providers must not keep or train on prompts:** every upstream
    request carries `provider.data_collection = "deny"` (`models/kael/config.py`),
    including the backup-host pin. Fails closed. `UPSTREAM_REQUIRE_NO_DATA_COLLECTION`
    switches it off for diagnosing an outage.
  - **Content-free errors and ledger text.** `usage_logs.error_message` and trace
    errors are cut to 500 characters and built from status codes and the
    exception class only (`provider_routing.safe_exception_summary`). Ledger
    descriptions no longer carry an email address: admin credits read "Admin
    credit adjustment" or "Admin self-credit". Three older ledger rows in the live
    database still hold the owner's address; they are historic and were not
    rewritten.
  - **The "15 minutes" claim was removed.** No code ever deleted anything after 15
    minutes: API text is never stored, and the provider-side cache is not ours.
  - **Safety screening is described as existing.** The owner is building it and
    asked for the documents to describe it as it will be at launch. No code for it
    is in this repo yet (PLAN D3).
  - Contact details use `support@quancis.space` and `response@quancis.space`; no
    personal Gmail address remains in the documents.

## Merge of the email/Playground work and the legal work (2026-10-15)
- **2026-10-15** Two branches that grew from the deployed code were joined into one
  tree: the email system, Playground attachments and voice typing on one side, the
  Terms/Privacy rewrite, account deletion, retention and credit expiry on the other.
  Three places needed a decision, all resolved in favour of keeping both features:
  - Account deletion's confirmation email now goes through
    `account_emails.notify_account_deleted` (it had its own inline HTML); the template
    copy carries the legal wording (credits forfeited, payment-provider and tax
    records, `response@quancis.space`). The other three deletion emails stay unwired.
  - The admin credit receipt email (`account_emails.notify_credits_added`) is kept, but
    the deposit-match promotion is gone, so there is no `is_deposit` flag and never a
    bonus line, and the ledger description still never contains an email address.
  - The daily loop in `scheduled_checks.py` runs credit expiry, billing reconciliation,
    the 30-day diagnostic purge and the low-balance emails (on by default).
