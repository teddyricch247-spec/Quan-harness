# Quancis backend

A JSON-only FastAPI service. It sells two models, **Kael Beta** and
**Kael Pro Beta**, through three wire formats, bills them prepaid per token
(each at its own price), and also serves the account API used by the separate
Next.js frontend. There are no
templates, static files or server-rendered pages here.

Read `../AGENTS.md` first (ground rules and traps). This file explains how
the code works today. Dated history of renames and removals is in
`HISTORY.md`. Live deployment facts are in `../STATUS.md`.

## Endpoints

All in `app/main.py`.

**Product API** (auth: `Authorization: Bearer sk-quan-...`, any active key)

| Route | Format |
|---|---|
| `POST /v1/chat/completions`, `POST /<model>/v1/chat/completions` | OpenAI Chat Completions |
| `POST /v1/responses`, `POST /<model>/v1/responses` | OpenAI Responses |
| `POST /v1/messages`, `POST /<model>/v1/messages` | Anthropic Messages |
| `GET /v1/models`, `GET /<model>/v1/models` | model list |

`<model>` is `kael-beta` or `kael-pro-beta`. `/v1/*` resolves the model from
the body's `model` field (`config.MODEL_TO_PRODUCT`); `/<model>/v1/*` fixes it
from the path and never reads the body's `model`. The per-model routes are
registered in a loop over `config.PRODUCTS` (`_register_model_routes()`), so a
new model gets them automatically. Accepted model names are exactly the two
slugs. Anything else, including the removed `quan-pro` and `quan-4`, is a
`400 model_not_found` that lists the valid ones. There are no `/pro/v1/*`
routes any more (removed 2026-10-08; see `HISTORY.md`).

**Public**
- `GET /api/health` returns `{"status":"ok"}` (Render's health check).
- `GET /api/config` returns the Supabase URL and anon key, plus the public
  product catalog (slug, label, tagline, limits, customer price).
- `POST /api/auth/signup`, `POST /api/auth/forgot-password`,
  `POST /api/auth/resend-confirmation`: unauthenticated, rate limited, always
  return a generic message (no account enumeration). Resend-confirmation
  emails a fresh link to an unconfirmed account and never touches its password.

**Signed-in account API** (auth: Supabase session JWT, `require_login`)
- `GET /api/me`, `PATCH /api/theme`, `GET /api/stats`, `GET /api/billing`
- `DELETE /api/account` with `{"confirm": "<the account email>"}`: permanently deletes the
  account and everything stored against it (see "Account deletion and retention")
- `GET/POST /api/keys`, `PATCH /api/keys/{id}` (the key's thinking level), `DELETE /api/keys/{id}`
- `POST /api/auth/record-oauth-consent`
- Playground conversations: `POST/GET /api/chat/sessions`,
  `GET/PATCH/DELETE /api/chat/sessions/{id}`,
  `POST /api/chat/sessions/{id}/messages`,
  `GET /api/chat/sessions/{id}/images/{image_id}` (a picture's bytes)
- Voice typing: `POST /api/chat/transcribe` (raw audio in, `{"text"}` out; see
  `app/transcription.py`). Text and code files attached in the Playground are
  not a route: they travel inside the message text (`app/chat_files.py`).

**Admin** (`require_admin`): `GET /api/admin/stats`, `GET /api/admin/users`,
`POST /api/admin/users/{id}/credit` (an admin may credit their own account, see
Billing), `.../suspend`, `.../activate`,
`POST /api/admin/reconcile` (runs the billing reconciliation now; read-only) and
`POST /api/admin/expire-credits` (runs the credit expiry now; a **dry run** unless the body is
`{"dry_run": false}`).

Sign-in itself has no backend route: the frontend calls Supabase Auth
directly with the anon key.

## Authentication

- **API keys:** created by signed-in users at `/api/keys`. Format
  `sk-quan-<random>`. Stored as a hash (SHA-256 with `API_KEY_PEPPER`); the
  full secret is shown once. A key works on every product route and on both
  models; scopes are stored but nothing gates on them. See `app/api_keys.py`, `app/auth.py`.
- **Per-key thinking level:** `api_keys.thinking_level` is NULL (shown as
  `"sdk"`: the request decides, as before) or a tier name from
  `reasoning_tiers` (of either model). Set at creation (`POST /api/keys {"name", "thinking_level"}`)
  or later (`PATCH /api/keys/{id} {"thinking_level"}`); invalid values are a
  `400`. A pinned tier **wins over the request**, and the request's own
  `reasoning_effort` / `reasoning` is then not validated (so a tool that sends
  `medium` still works). A tier belongs to one model, so a pin applies only on
  the model that offers it; on the other model the key behaves as `sdk` and the
  request decides (`_pinned_tier()` in `app/kael_pipeline.py`). `verify_api_key` reads it on every request, so a change
  applies on the key's next call. Unknown stored values act as `sdk`. The code
  works whether or not migration 0013 is applied (see `app/api_keys.py`).
  Tests: `backend/test_key_thinking_level.py`.
- **Login:** `require_login` verifies the Supabase JWT with a live call to
  Supabase Auth on each request, and rejects banned users immediately.
- **Admin:** `require_admin` = `require_login` + `app_metadata.role == "admin"`.
  `app_metadata` can only be written with the service-role key. There is no
  HTTP route to grant admin, on purpose. To promote an account, run in
  Supabase (SQL): `update auth.users set raw_app_meta_data =
  raw_app_meta_data || jsonb_build_object('role','admin') where email =
  '<the email>';` and check that one row matched.
- **Suspension** works in two layers: a Supabase ban (`banned_until`) plus
  revoking all the user's active API keys (`api_keys.revoke_all_active_keys`).
  Reactivating lifts the ban but does not restore revoked keys.

## How a request flows

```
caller -> route in main.py
       -> auth (api key or login) + pre-auth IP throttle + per-user rate limit
       -> kael_pipeline.py (resolves reasoning effort, builds two PassConfigs)
       -> two_pass_pipeline.run_pipeline()
            balance check
            PASS 1 draft   (with the difficulty-router message attached)
            EASY? -> serve the draft
            else PASS 2 critic (draft rendered into a review message)
            rebrand the response, bill, write usage_logs + chat_debug_traces
       -> response in the caller's own wire format
```

All formats are converted to one internal shape (the Responses shape) at
the edges: `response_api.py` (pure conversions, no I/O) and
`anthropic_api.py` (Anthropic ingress/egress). The engine does not know
which format the caller used. Both passes call OpenRouter's Chat
Completions endpoint. Responses `input` items (typed content parts,
`function_call` / `function_call_output`) and the top-level `instructions`
are converted to chat messages at the edge by
`response_api.responses_input_to_messages()`.

### Two passes, and when the critic is skipped

- **Draft and critic:** `deepseek/deepseek-v4.1-flash` (the same model).
  Both via OpenRouter with speed-first provider routing (fastest eligible
  host, hard price ceiling, no fixed provider). Settings live in
  `app/models/kael/config.py` (see its README).
- The critic reviews the draft (including a chosen tool call, rendered as
  text) and may affirm, correct, or replace it. Its output is the answer.
- **The critic is skipped when:** the draft is empty or filtered; or the
  difficulty router rated the request `EASY`. The router is an instruction
  attached to the draft pass only (`app/router/kael.py`): the draft model
  opens with a one-word `EASY`/`HARD` rating inside a per-request random
  tag. The tag is stripped before anything else reads the draft. Any
  missing, malformed or unexpected rating counts as `HARD` (fail safe).
- If the critic call fails or times out, the draft is served and billing
  treats the draft as both first and last call.

### Thinking tiers, and the z tiers (fusion)

| Tier | Model | Draft | Fusor | Critic | Calls |
|---|---|---|---|---|---|
| `low` (default) | `kael-beta` | high | none | low | 2 |
| `high` | `kael-beta` | high | none | high | 2 |
| `max` | `kael-beta` | max | none | max | 2 |
| `z-low` (default) | `kael-pro-beta` | 3x high, concurrent | high | high | 5 |
| `z-high` | `kael-pro-beta` | 3x max, concurrent | max | max | 5 |

The tier definitions live in `app/models/kael/config.py`
(`_TIER_DEFINITIONS`); each model lists the ones it accepts in its own
`reasoning_tiers`. Every pass uses the same speed-first routing. A model
accepts only its own tiers: a tier of the other model is a `400` that names the
model offering it. On a z tier the three drafts run at
the same time, then the **fusor** (`app/fusor/kael.py`) reads the surviving
drafts and writes one new answer, then the unchanged critic reviews that.

- One draft failing does not fail the request; only all three failing does.
  One survivor goes straight to the critic (no fusor call). A draft or the
  fusor that fails fast with a 429 or 502 is tried once more first. A plain
  bug in one draft drops that draft too (logged); it is re-raised only when no
  draft succeeded.
- Once two drafts are back whole, the third gets half the second one's time
  (at least 15 s, at most 90 s: `Z_STRAGGLER_*`) and is then cancelled, so one
  slow draft cannot hold the request until the 480 s ceiling. With fewer than
  two whole drafts nothing is cut.
- The EASY shortcut (skip fusor and critic) needs all three drafts back, whole,
  rated EASY and alike (`Z_EASY_MIN_AGREEMENT`); anything less, including a lone
  EASY survivor, gets the review. One HARD (or unparseable) keeps it too. Empty
  drafts follow the usual empty path.
- If the fusor fails, the critic reviews the consensus draft (a whole one, the
  one most like the others). If the critic then fails, the fused answer (or that
  draft) is served. The log says `z DEGRADED` when fewer drafts than the tier
  promises took part.
- Billing is unchanged: first call's input (one draft's), last call's output.
  The other drafts, the fusor and the critic's input are upstream cost
  Quancis absorbs.
- The fusor's draft tags use a token generated for the fusion step only.
- Streaming: only the critic's text is relayed; thinking titles follow one
  draft at a time (when it ends they move to the draft furthest along), then a
  "fusing" phase, then the review.
- The trace's `draft_status` on a z request ends in `_x<took part>of<fired>`,
  for example `ok_text_x2of3`.
- Upstream connection failures (only connect errors and connect timeouts,
  never read timeouts or error responses) are retried up to 3 attempts,
  because retrying anything else could double-bill a generation.
- A hard ceiling of 480 seconds applies to each stage of a generation (per
  attempt), not to the request: Kael Beta has two stages, Kael Pro Beta three, so
  one request can run for about 16 and 24 minutes. Public docs recommend a client
  timeout of 30 minutes (`clientTimeoutMinutes` in the frontend docs `facts.ts`)
  and never say a request gets 8 minutes.

### What callers can and cannot control

The request body may contain any OpenAI-shaped fields, but upstream bodies
are built from a fixed set taken from Kael's config, never from the
incoming request. So `temperature`, `top_p`, `seed` etc. are ignored by
construction. Callers do control: the conversation, `tools`/`tool_choice`,
`stream`, `stream_options.include_usage`, `max_tokens` / `max_output_tokens`
(capped at the product ceiling), and **`reasoning_effort`**
(a tier of the model called: `low` | `high` | `max` for `kael-beta`, `z-low` |
`z-high` for `kael-pro-beta`, case-insensitive; Chat Completions and Anthropic
Messages: top-level `reasoning_effort`; Responses: `reasoning.effort`).
Default `low` on `kael-beta` and `z-low` on `kael-pro-beta`. There is no `off`:
Kael always thinks. Each tier sets the
effort of each pass (table below). An invalid value is a `400`, unless the
caller's API key has a thinking level set on the dashboard, which is used
instead (see Authentication).

### Streaming

- Draft output is never shown. Only the critic's (or, if the critic is
  skipped, the draft's) content is relayed as the answer.
- An invisible SSE comment is sent at least every ~1 second on any quiet
  stretch, so connections do not look dead.
- **Thinking titles** (`app/thinking_summarizer.py`): reasoning from both
  passes feeds a background summarizer that emits short human-readable
  titles on `delta.reasoning_content` (Chat Completions) or
  `response.reasoning_text.delta` (Responses). Raw reasoning is never
  relayed. A chunk becomes a title after ~0.9 s of quiet or 6 s of
  continuous reasoning; at most 3 titles per chunk; a filler word is shown if
  the summarizer is slow (every ~3.5 s); the last 8 titles are kept as
  context. The summarizer calls cost a little and are currently absorbed,
  not billed. They run on their own cheap-first model list with
  price-sorted routing (`summarizer_models` / `summarizer_provider_routing`
  in `app/models/kael/config.py`), not on the draft pass's model.
  - Reasoning is read from `delta.reasoning_content`, `delta.reasoning` or
    `delta.reasoning_details`, whichever the host sends. It, the draft text and
    every title go through `identity_guard` before they can reach a title.
  - Each title is its own delta and ends with a blank line (`\n\n`), so a
    caller that concatenates the deltas still sees separate lines. On the
    Anthropic shape the thinking block closes with a `signature_delta`
    (an opaque hash; nothing verifies it).
  - Summarizer calls run one at a time, in capture order, with their own
    `session_id` (`<conversation key>-titles`). One retry for a transport
    error, 429 or 5xx; otherwise a failed call just yields no title and the
    filler words cover the gap. The model list is OpenRouter's `models`
    fallback array: a later model is used only when the earlier one errors
    (not when it is merely slow), and the render logs show a `FALLBACK_MODEL`
    line (at most one a minute) when that happens.
  - Filler words are liveness only. They are never saved or counted as steps
    (`app/thinking_fillers.py`).
  - Before every terminal event the relay is stopped quickly (in-flight calls get
    about 1 s, none once the answer has started) and nothing is emitted after
    that. If the HTTP client disconnects, the relay stops calling the summarizer;
    the draft and critic passes still run to the end and are billed.
  - If the critic fails after it has started answering, the client gets an error
    event. The draft is only served in its place when the critic had sent nothing.
- Responses-shaped streaming callers get content deltas and a final
  completed event, not fine-grained per-item lifecycle events.

### Identity and caller system prompts

- Any caller `system`/`developer` message (string or content-part list) is
  wrapped in `<caller_system_prompt_{random}>` tags
  (`response_api.prepare_input_items()`), and a final system item — a
  `<kael_context_{random}>` block, built by
  `response_api.build_kael_context_message()` — states today's real date
  (and is where skills will go). Both are kept out of the static identity
  text so that text stays cacheable.
- Because the upstream API is flat Chat Completions, order is explicit:
  Kael's `system_identity` (the master prompt) goes FIRST and itself ranks
  the layers beneath it (Kael context > caller instructions > the
  conversation); then the caller's content; then the router instruction
  (pass 1) or critic prompt (pass 2) last. The master prompt is the one
  fully static block, so first position makes it the shared cacheable
  prefix.
- `system_identity` says: a calling application's own persona wins for
  naming; the platform never names or confirms an underlying vendor or
  model, whatever the caller says.
- `app/identity_guard.py` is a regex backstop over final output for
  self-identification phrasing ("I am DeepSeek", "powered by GLM"), applied to
  both non-streamed responses and the streamed relay (buffered so a leak
  split across chunks is still caught). It is a backstop, not a guarantee.

### Keeping upstream invisible

Response `model` becomes the called model's slug (`kael-beta` or
`kael-pro-beta`); upstream error text is replaced with
generic messages; raw reasoning is never shown. Upstream errors never reach
callers as-is: `provider_routing.client_error_for_upstream_status` maps them
to fixed bodies (an upstream 401/402/403 becomes a 503, since it describes
our account, is not retried on the backup host, and logs
`UPSTREAM_CREDENTIALS_OR_CREDIT` for the operator; an over-long request
gets the standard `context_length_exceeded` code with a fixed message). The
dashboard's request table (`/api/stats`) shows each row's own model slug
(from `usage_logs.product`) and never `usage_logs.model`, which holds the
upstream ids. Internal logs
(`usage_logs.error_message`) do name real providers, and never reach callers.

### Upstream data policy

Every upstream call (drafts, fusor, critic, thinking-title summariser) carries
`provider.data_collection = "deny"` (`models/kael/config.py`,
`_DATA_POLICY`), so the router only uses providers that do not store prompts or
train on them. The setting is copied into the one-off backup-host pin
(`provider_routing.fallback_routing`), so a failover never relaxes it. If no
such provider is available, OpenRouter answers with an error and the caller gets
a clean 503 (fail closed): a request is never sent to a provider that keeps data.
Switch: `UPSTREAM_REQUIRE_NO_DATA_COLLECTION` (default on); it exists for
diagnosing an outage and changes what the Privacy Policy says, so it is not left
off. `zdr` (zero data retention endpoints only) is deliberately **not** set: it
shrinks the provider pool a lot. The OpenRouter account's own privacy and logging
settings are separate and live in its dashboard, not here.

### Upstream failures mid-generation

When the serving host fails after tokens have started, OpenRouter ends the
stream with a chunk carrying a top-level `error` object and
`finish_reason: "error"`; it cannot re-route at that point, and it does not
charge for such a response. The engine (`consume_pass` / `_post_upstream` in
`two_pass_pipeline.py`) reads that object, keeping only its `code`,
`error_type` and the host name (`provider_routing.safe_error_fields`; the
free-text message can quote the prompt and is never stored), and:

1. If nothing of this pass has reached the caller yet (always true for a
   draft), re-runs the pass **once** with the failed host in
   `provider.ignore`. Sort, `allow_fallbacks` and the price ceiling are kept,
   so the re-run goes to the next-best host under the ceiling. If the failed
   host is unknown it is pinned to the backup host instead; a pass with no
   price ceiling is never re-run. The caller is not told about the first
   failure.
2. Reports the failure only if the re-run fails too (a draft: the usual
   error; a critic: the draft is served, as before). The trace
   `error_message` then names both failures (finish reason, code, error type,
   host).

Each attempt gets its own `GENERATION_HARD_CEILING_SECONDS`. Not re-run:
`content_filter` (a verdict on the content), timeouts, plain connection
drops, and a critic whose answer has already started streaming. Failure
rows in `chat_debug_traces` now also record `chunks_from_upstream` and
`reasoning_char_count`.

## Billing

Code: `app/billing.py` (read its docstring before touching the math).

- **Metering:** billed input = the first call's prompt tokens (including
  cache-hit tokens at the cached rate); billed output = the last call's
  completion tokens. The `usage` object callers see equals what they are
  billed. `usage_logs` rows record the same billed figures (not both calls'
  summed usage), so pricing a row equals what was charged.
- **Injected prompt overhead is not billed:** the first call also carries
  text Kael adds itself (master prompt, `<kael_context>` block, caller-prompt
  wrapper tags, the difficulty-router instruction). Its tokens are estimated
  from its character count (`response_api.INJECTED_TOKENS_PER_CHAR`,
  calibrated on real tiny requests) and subtracted from billed and shown
  input; the cache hit loses only what covered the master prompt, which sits
  first in the request. Re-measure the rate with a tiny request after big
  edits to the master or router prompt.
- **Price:** `customer_price_per_million` in `app/models/kael/config.py`
  (`input`, `output`, `cached_input`). A product with that key is billed.
  Cached input is set to exactly 20% of input.
- **Balance and ledger:** `billing_accounts.balance_usd` is changed only by
  the Postgres functions `deduct_balance` and `credit_balance`, each also
  writing an append-only `billing_ledger` row (`kind` = `usage`, `deposit`
  or `adjustment`). New accounts start at $0 (`DEFAULT_STARTING_BALANCE`).
  A request is refused with HTTP 402 when the balance is at or below $0
  at the start; a request that starts positive may finish slightly
  negative by design.
- **Admin credit:** `POST /api/admin/users/{id}/credit` is the only way
  money is added today. There is no payment processor. An amount is above $0,
  at most $999,999,999 and at least $0.00001 (a smaller one would round to
  nothing). **An admin can credit their own account** by any amount (the user id
  in the route is their own). The backend recognises this itself (it compares the
  id with the caller's), so a client cannot mark it: the ledger line reads "Admin self-credit"
  (other credits read "Admin credit adjustment") and the response carries
  `self_credit: true`. Ledger descriptions never contain an email address,
  because customers read their own ledger through `GET /api/billing`. The Admin
  page's Overview tab has an "Add to my balance" card for it.
- **Credits expire 12 months after they are added** (`app/credit_expiry.py`).
  The Terms of Service say so, and say credits are a prepaid service allowance:
  no cash value, not withdrawable, transferable or exchangeable, and usable only on
  Quancis. The ledger is the only record, so the expiry is a first-in-first-out
  replay of it: each deposit (or positive adjustment) is a lot; usage and negative
  adjustments use the oldest lots first; a negative balance is paid off by the next
  credit added. Once a day `scheduled_checks.run_cycle` records what has expired as
  one `adjustment` ledger row (negative, description starting "Expired credits"),
  through the `expire_credits` Postgres function (migration 0017), which locks the
  account row and refuses to write if the account's ledger has changed since it was
  read (the next run recomputes). Until the daily run records it, a credit past its
  12 months stays usable (lenient on purpose; the ledger is the truth). Guards: the
  replayed balance must equal `billing_accounts.balance_usd`, and any expiry row
  already in the ledger must match what the rules remove, or the account is skipped
  and logged for a human. `CREDIT_EXPIRY_ENABLED=false` stops the writes;
  `POST /api/admin/expire-credits` reports what would expire (dry run by default).
  No credit can expire before late 2027, because none was added earlier than
  2026-08. Note for lawyers: South African consumer law (CPA s63) has a longer rule
  for prepaid vouchers; the owner chose 12 months knowingly.
- **Usage-page costs are estimates:** `GET /api/stats` recomputes each
  request's cost from its token counts at the *current* price
  (`supabase_client.fetch_stats`; `usage_logs` stores no cost, only the billed
  token counts). After a repricing, past requests show at the new price.
  Rows written before 2026-10-03 hold both calls' summed raw usage and so
  overstate tokens and cost. `billing_ledger` holds the
  real charges.
- **Reconciliation:** `billing.reconcile_all_accounts()` compares each
  balance to `DEFAULT_STARTING_BALANCE + sum(ledger)` and reports drift.
  It never corrects anything. It is run three ways: by hand or a cron job via
  `app/jobs/reconcile_billing.py`, daily by the in-process loop in
  `app/scheduled_checks.py`, and on demand by `POST /api/admin/reconcile`
  (the Admin page's "Run check" button).

## Rate limiting (`app/rate_limit.py`, in memory, per process)

- Signup, forgot-password and resend-confirmation: limited by IP and by target
  email. The email key is canonicalised (Gmail dots, `+tags` and `googlemail.com`
  collapse to one mailbox) so variants can't each claim a fresh budget.
- A global ceiling on auth emails (`AUTH_EMAIL_HOURLY_CAP`, default 200 per
  hour): once reached, the public endpoints answer normally, send nothing and
  create no accounts, and `ADMIN_ALERT_EMAIL` is told once an hour.
- The IP comes from the left-most `X-Forwarded-For` value, which a client can
  set itself, so the per-IP limit is weak on its own. Deliberately unchanged
  until the real proxy chain in front of Render is verified.
- Product endpoints, per user: 150 requests per 60 s and at most 30
  concurrent requests (owner-set 2026-10-03).
- Pre-authentication IP throttle on product endpoints: 300 requests per
  60 s, checked before the API key is looked up.
- The numbers are reasoned, not tuned on real traffic. State is lost on
  restart and not shared between instances.

## Playground conversations

`/api/chat/sessions...` gives signed-in users playground conversations (the
frontend Playground). "Playground conversation" is the product term; the
routes and tables keep their historical names (`/api/chat/sessions`,
`chat_sessions`, `chat_messages`) because renaming them would break the
Render/Vercel deploy ordering. It calls the same Kael pipeline as the public
API with `key_id=None` and `source="app_chat"`, and is billed to the user's
balance like an API call.

Titles and empty conversations (2026-10-06): new rows are written with the
title "New conversation"; older rows titled "New chat" are displayed as "New
conversation" without a migration (`chat_history.display_title`). A
conversation that never received a message (a first send that failed) is left
out of `GET /api/chat/sessions` and deleted once it is 7 days old
(`_without_empty_conversations`); the check is confirmed against
`chat_messages` and fails open. The first line(s) of the first message become
the title, skipping code fences and markdown markers (`chat_history.auto_title`).

Saving a turn (`supabase_client.insert_chat_exchange`): both rows of the bulk
insert must carry the same keys, otherwise PostgREST answers 400 `PGRST102`
("All object keys must match"). That mismatch lost every reply that had
thinking titles between 2026-10-05 and 2026-10-06. A failed insert with
thinking titles is retried once without them, so a reply is never lost to the
optional titles.

How a send works (`send_chat_message`, helpers in `app/chat_history.py`):

- The session id must be a UUID (anything else is a 404 with no database
  call), the message must be non-blank and at most 100,000 characters.
- **Nothing is saved until the reply succeeds.** The user message and the
  reply are then written together (`insert_chat_exchange`). A failed send
  (402, 429, upstream error, empty reply) leaves no orphaned user message, so
  the client just resends. The title is set from the first successful
  message: single line, 60 characters.
- The history sent to the model is the newest 300 stored rows, merged where
  two same-role messages are adjacent, then trimmed from the oldest end to at
  most 200 messages and 400,000 characters. The newest turn is always kept.
  The model forgets the oldest turns of a very long chat; the stored chat is
  untouched.
- `reasoning_effort` (optional) in the message body is passed straight through
  as the same top-level field the public API takes. It must be a tier of the
  conversation's model (`low` | `high` | `max` for Kael Beta, `z-low` | `z-high`
  for Kael Pro Beta); anything else is a 400 that lists them. Left out, the
  model uses its own default. There is no "off".
- **A conversation is locked to the model it started with.** `POST
  /api/chat/sessions {"product": "kael-beta" | "kael-pro-beta"}` creates it, the
  value is stored in `chat_sessions.model`, and the new session's
  `reasoning_effort` starts at that model's default tier. A stored model that
  is not a current model (`config.MODEL_TO_PRODUCT`) makes the conversation
  read-only (`resumable: false`).
- **Replies are detached from the browser.** While a reply runs, an in-memory
  `GenerationJob` (`app/chat_history.py`) records the user's message, the
  thinking titles streamed so far, the answer so far and the outcome. A pump
  task in `main.py` keeps reading the pipeline's stream even if the browser
  disconnects, so going offline or reloading mid-reply neither stops the reply
  nor releases the chat's lock. `GET /api/chat/sessions/{id}` returns it as
  `pending` (`status` `running` or `error`, `content`, `thinking`, `answer`,
  `error`) until the exchange is saved; a failed reply stays visible for 10
  minutes so a reload can show it. The job is dropped once the reply is saved.
- One reply at a time per chat: a second send while one is generating gets
  **409** `session_busy`, including after the browser that sent it has gone.
  In memory and per process (single instance, like `rate_limit.py`), so a
  backend restart loses a reply that was still running.
- The thinking titles Kael streamed are saved on the assistant message
  (the list the pipeline's relay actually sent, without filler words;
  `chat_messages.thinking`, jsonb array, migration `0009`) and returned as
  `thinking` on each assistant message by the detail route. If the column does
  not exist, chats still save and load without it (the code detects the
  database's "unknown column" error and skips the column for 5 minutes).
- If the chat tables cannot be read the routes answer **503**
  `storage_unavailable`. A failed lookup is no longer reported as "not found"
  or "no messages", and the model is never called with a history that failed
  to load.
- `GET /api/chat/sessions` and `GET /api/chat/sessions/{id}` include
  `resumable` per session: `false` for a legacy session (a `model` value this
  app no longer offers). Continuing one is **409** `session_not_resumable`.
  The detail route returns the newest 1,000 messages.
- **Pictures.** A message may carry up to 4 pictures (`images`:
  `[{"mime", "data"}]`, base64 without the `data:` prefix; JPEG, PNG, WebP or
  GIF, sniffed from the bytes, not trusted from `mime`), at most 3 MB each and
  8 MB per message, and a conversation holds at most 20 and 24 MB in all
  (checked from the stored sizes before any picture is read into memory). Text may be empty when
  there are pictures. Bad input is 400 `invalid_images`; more than the cap is 400
  `too_many_images`; a model with `supports_images: false` (config) is 400
  `images_not_supported`. The page shrinks every picture to a JPEG of at most
  1568 px first, so real uploads are far under the limits. They are sent to the
  model as Chat Completions `image_url` content parts, so every later turn of
  the conversation still includes the earlier pictures; the pipeline's
  caching, sticky routing key (`provider_routing.first_user_text`, which falls
  back to a hash of the first picture) and billing are unchanged (a picture is
  billed as input tokens). Pictures are stored in `chat_message_images`
  (migration `0015`), one row each, saved with the exchange. `GET
  /api/chat/sessions/{id}` returns `images: [{id, mime}]` on a user message, never
  the bytes; `GET /api/chat/sessions/{id}/images/{image_id}` returns them to the
  owner only (`Cache-Control: private`, `nosniff`). If the table does not exist
  yet the message is still answered but the pictures are not kept, so they are
  missing after a reload and from later turns (same detect-and-skip pattern as
  `thinking`). If the stored pictures cannot be read the send is a 503 rather
  than an answer that ignores them. Pictures live in Postgres; if volume grows,
  move `data` to a private Storage bucket.
- Mid-stream failures arrive as an SSE frame `data: {"error": {...}}` (the
  response has already started with a 200).

## Admin API (`app/admin.py`)

Real numbers only. Revenue is actual usage charges in a stated window (not
deposits). The aggregate reads sum rows client-side up to
`ADMIN_AGGREGATE_ROW_CAP` (50,000) because PostgREST has no server-side
sums; revisit if one 30-day window approaches that. There is no database
browser (use the Supabase dashboard).

`POST /api/admin/reconcile` returns `{status: "ok" | "drift", checked_at,
drift_count, drifts: [{user_id, expected_balance_usd, actual_balance_usd,
drift_usd}], error: null}`. If the check itself cannot run (for example
Supabase is unreachable) it answers **502**, never a 200 that could be read
as "clean". A manual run does not send the alert email.

## Emails

Transactional email only, through Resend (`quancis.space`, sender
`noreply@quancis.space`). Four small modules, each with one job:

| Module | Job |
|---|---|
| `app/email_layout.py` | The one visual shell. Design tokens copied from the platform (`globals.css`, `BrandMark.tsx`): ink/line/surface colours, Inter and JetBrains Mono (requested from Google Fonts where the mail client allows, with safe fallbacks), pill buttons, the brand mark built from table cells (so it needs no image) with the "uancis" wordmark, a 20px-radius card, dark mode, a preheader. Pure: no I/O. **Every value is HTML-escaped by default**; templates pass plain text to block classes and never write markup. Also builds the plain-text part. |
| `app/email_templates.py` | One function per email: confirm signup, reset password, already registered, admin notice, low balance, balance depleted, password changed, account suspended / reactivated, new API key, credits added, plus the billing-check alerts. Seven more (welcome, price change, legal update, and the four account-deletion emails) render but are not sent by anything yet; see the module docstring for why. |
| `app/email_service.py` | Delivery: `send_email(to, subject, html)` to Resend, with a derived plain-text part, optional Reply-To (`RESEND_REPLY_TO`), tags, an idempotency key, a retry on 429/5xx, and Resend's real error in the log (never the recipient). |
| `app/account_emails.py` | When account events send email: suspension and reactivation (the Terms promise notice), a new API key, credits added by an admin, and "your password was changed" (the frontend calls `POST /api/auth/password-changed` after a successful change; best-effort, 3 per user per hour). Also holds the four account-deletion email functions, which nothing calls yet because account deletion itself does not exist: see `EMAIL_ACCOUNT_DELETION.md`. A failed email never fails the action. |
| `app/balance_alerts.py` | Balance emails, fired when a charge crosses the line: the low-balance alert a user turns on in Account -> Notifications, and a "balance has run out" notice for every user whose balance reaches $0. Called from `billing.charge_for_request` with the new balance the `deduct_balance` function returns, as a background task that can never delay or fail a charge. The daily scan in `app/jobs/low_balance_alerts.py` is the safety net. Master switch: `LOW_BALANCE_ALERTS_ENABLED` (default on). |

`app/auth_email.py` decides who gets which auth email: signup confirmation,
password reset, resend-confirmation, and the already-registered and admin
notices. Links come from Supabase's admin link API. With
`AUTH_LINK_MODE=confirm_page` they point at the frontend's `/auth/confirm`
page instead of Supabase's verify URL. Signup validates the display name (at
most 80 characters, no `<` or `>`). Responses never reveal whether an email is
registered. Signup records Terms/Privacy acceptance in `legal_acceptances`
(append-only); OAuth sign-ins record it through `/api/auth/record-oauth-consent`.

To look at every email without sending anything, run
`python render_email_previews.py [--png]` and open `email_previews/index.html`.
Adding an email: build it from the layout blocks in `email_templates.py`, add
it to `SAMPLES` in `render_email_previews.py`, and `test_email_system.py` checks
the rest (a template missing from `SAMPLES` fails the test).

Not built, and why: a send log, notification-preference table and delivery
webhook need a migration; a welcome email needs a "sent" record so it goes
out once; price-change and legal-update broadcasts need the send log to be
safely re-runnable. The password-changed notice only covers changes made
through the app (the browser tells the backend); a Supabase-side security
notification is the complete answer for anything else.

## Debug tracing

Every product request writes a row to `chat_debug_traces` as it happens
(status, token and chunk counts, timings), not just on success. `source` is
`api` or `app_chat`.

**Text is stored only for the in-app Playground and Chat (`app_chat`).** For
API requests the row holds counts, timings and status only: no prompt, no
draft, no answer. This is enforced in one place, `supabase_client.py`
(`CONTENT_TRACE_SOURCES`, default-deny, so a new source or a forgotten call
site stores no text), and by a database check constraint
(`supabase/migrations/0010_api_prompts_never_stored.sql`). `error_message` holds only the HTTP status, error code/type and the serving
host's name for upstream failures. Upstream free text is never kept, because
it can quote the caller's prompt (`provider_routing.safe_upstream_summary`).

**Retention.** A Playground row is linked to its conversation
(`chat_debug_traces.session_id`, migration 0016, `ON DELETE CASCADE`), so
deleting a conversation deletes its diagnostic row too. Whatever happens, a row
is deleted when it is 30 days old: `supabase_client.purge_expired_chat_traces()`
calls the `purge_expired_chat_traces()` database function once a day from the
loop in `scheduled_checks.py`. The backend also works before migration 0016 is
applied (rows are saved without the link, and the purge logs an error until
the function exists), so deploy order does not matter. API rows carry no
`session_id` and no text.

## Account deletion and retention

`DELETE /api/account` (`app/account.py`) permanently deletes the signed-in
user's account. The caller must send their account email as `confirm` (case and
surrounding spaces ignored; the word `DELETE` for the rare account with no email).
Steps, in this order: revoke every active API key; delete the user's
`chat_debug_traces` and `usage_logs` rows (both reference the user
`ON DELETE SET NULL`, so deleting the auth user alone would leave them behind,
ownerless); delete the Supabase Auth user (hard delete), which cascades
conversations, messages and pictures, API keys, the billing account and ledger,
and `legal_acceptances`; send a confirmation email (best effort). Admin accounts
are refused (403). A failure in any step before the last answers 502 and leaves
the account in place, and every step is safe to repeat. Credits left on the account are
forfeited. Nothing in this database is a payment record: payments are taken by the
Merchant of Record, which keeps its own records.

Retention rules the Privacy Policy states, and where they live:

| Data | Kept | Where |
|---|---|---|
| Playground conversations, messages, pictures | until the user deletes the conversation or the account | `delete_chat_session`, `account.py` |
| Playground diagnostic rows (`chat_debug_traces`) | deleted with the conversation, else at 30 days | migration 0016, `purge_expired_chat_traces()` |
| API request text | never stored | `CONTENT_TRACE_SOURCES`, check constraint `0010` |
| API usage records (counts, model, status, time) | until the account is deleted | `usage_logs`, `account.py` |
| Billing ledger | until the account is deleted | cascade from the auth user |

## Data model

Public tables (all RLS-enabled, no policies, service-role access only):
`usage_logs`, `api_keys`, `chat_debug_traces`, `chat_sessions`,
`chat_messages`, `billing_accounts`, `billing_ledger`, `legal_acceptances`.
Functions: `deduct_balance`, `credit_balance`, `expire_credits` (0017) and
`purge_expired_chat_traces` (0016); all four are executable by the service role
only. Read the live schema with
Supabase tools; see `supabase/README.md`.

## Configuration

Environment variables are listed in `../README.md`. `app/config.py`
defines them, holds the model registry (`PRODUCTS`, `MODEL_TO_PRODUCT`,
`BILLED_PRODUCTS`) and `validate()`, which runs at import in `main.py`.
CORS is limited to `ALLOWED_ORIGINS` plus `*.vercel.app` previews.

## Scheduled jobs

`app/jobs/` holds two one-shot scripts (`python -m app.jobs.<name>`); see
`app/jobs/README.md`. The scripts do not schedule themselves.

`app/scheduled_checks.py` is a **stopgap** that runs the daily jobs from
inside the web service: the credit expiry (`app/credit_expiry.py`), then the
billing reconciliation, then the 30-day purge of Playground diagnostic rows,
then (if enabled) the low-balance emails. A crash in one step never skips
the others. `main.py` passes its `lifespan`
to FastAPI; that starts one background task which waits 5 minutes after boot,
then runs every 24 hours. Each run logs one line
(`[scheduled_checks] RECONCILE ok` / `RECONCILE drift <n> account(s)` /
`RECONCILE failed: <reason>`) and, on drift or failure, emails
`ADMIN_ALERT_EMAIL` (if unset it only logs). Unless `LOW_BALANCE_ALERTS_ENABLED` is
false (default true) the same cycle also runs the low-balance customer
emails, as a safety net behind the event-driven alerts in `app/balance_alerts.py`. Nothing in it can crash the API: every run is guarded, a failing
alert email is swallowed, and shutdown cancels the task cleanly.

Limits, accepted for a stopgap: the timer restarts on every deploy; it only
runs while the instance is awake (an idle free-plan instance sleeps); with
more than one instance each runs its own loop, so alerts duplicate; and
because it emails on every run that finds drift, known-but-unresolved drift
re-alerts each day. A Render Cron Job running the `app/jobs/` scripts
replaces it; delete the module and the `lifespan=` argument in `main.py`
then.

## Tests

Plain scripts, run from this folder after `pip install -r requirements.txt`.
Each makes no network calls and prints `ALL CHECKS PASSED` (or `all passed`).

| Script | Covers |
|---|---|
| `test_pipeline_logic.py` | pure wire-format logic (`response_api.py`) |
| `test_pipeline_integration.py` | orchestration with a stubbed network, plus the billing math and price, reconciliation, the scheduled-check loop and the low-balance job |
| `test_z_tiers.py` | each model's tier table, tier validation and the cross-model 400s, the fusor pass, the three entry points |
| `test_two_models.py` | the two-model registry, retired names, per-model billing, the routes registered per model, the generic routers, `GET /api/config` |
| `test_key_thinking_level.py` | the per-key thinking level and its precedence, per model |
| `test_chat_history.py` | the pure chat helpers (stdlib only) |
| `test_chat_routes.py` | the real chat routes against an in-memory fake of `supabase_client` and a fake model call, including per-model tier validation |
| `test_chat_thinking_column.py` | the `chat_messages.thinking` fallback |
| `test_chat_images.py` | pictures in the Playground and the admin credit rules (descriptions carry no email) |
| `test_api_privacy.py` | privacy and public-naming rules, and the dashboard's model labels |
| `test_kael_robustness.py` | robustness fixes in the pipeline entry points |
| `test_main_routes_input.py` | malformed `model` values on the public routes are a clean 400 |
| `test_provider_routing.py` | the speed-first provider routing, the data-collection "deny" rule and its carry-over to the backup host |
| `test_email_system.py` | the email layout and every template (escaping, structure, plain text), `send_email` against a fake HTTP client, the signup / forgot-password / resend flows, the rate-limit additions, and the account-event emails |
| `test_credit_expiry.py` | the 12-month credit expiry: the first-in-first-out replay and a whole run against an in-memory stand-in for Supabase |
| `test_account_retention.py` | account deletion (order, refusals, failures), the 30-day purge call, the trace's conversation link |

`test_chat_routes.py`, `test_chat_thinking_column.py`, `test_chat_images.py` and `test_email_system.py` import the real
`fastapi` and `httpx`, so they need `pip install -r requirements.txt` first. The
others stub those two packages themselves and run in a bare Python environment.

## Deploy

Render web service "Quan AI": repo `BCR-MVP`, branch `main`, root
directory `backend`, build `pip install -r requirements.txt`, start
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check
`/api/health`, auto-deploy on commit.
