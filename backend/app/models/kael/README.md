# Kael (Kael Beta and Kael Pro Beta)

Two public models, both defined in `config.py` in this folder:

| | Kael Beta | Kael Pro Beta |
|---|---|---|
| Key, slug and API `model` id | `kael-beta` | `kael-pro-beta` |
| Python name | `KAEL_BETA` | `KAEL_PRO_BETA` |
| Thinking tiers | `low` (default), `high`, `max` | `z-low` (default), `z-high` |
| Model calls per request | 2 | 5 |
| Price | its own `customer_price_per_million` | its own, higher |

A model's **key is its public slug**: it is the dict key in `config.PRODUCTS`,
the URL prefix, and the value stored in the database's `product` and `model`
columns. There is no separate internal name. (Until 2026-10-08 the one model
was keyed `"pro"` with aliases `quan-pro` and `quan-4`; those names no longer
exist anywhere. See `../../../HISTORY.md` and migration
`0012_kael_beta_split.sql`.)

`config.py` is the source of truth for everything below. This README explains
what the fields mean; it deliberately does not repeat values that can change
(prices, token limits, provider preferences). Open the file for those.

## What it is

Not a bigger model, and not a single call. Both models run on the same
upstream model and share one set of settings, `_SHARED` in `config.py`: the
upstream model ids, the provider routing, the master prompt (`system_identity`),
the thinking-title summarizer and the cost-tracking figures. Each of the two
model dicts spreads `_SHARED` and adds only what differs: its identity, the
tiers it accepts, and its price. To change something for one model only, set it
on that model's dict (it overrides the shared value). Do not copy a shared value
into both dicts.

What differs is the tier. Each request runs one or more **draft** calls and
then usually a **critic** call that reviews the answer.

```
caller -> /v1/{chat/completions | responses | messages}      (model in the body)
       or /<model>/v1/{...}                                  (model in the path)
       -> auth + rate limits (main.py, auth.py, rate_limit.py)
       -> kael_pipeline.py: pick the key's pinned tier or resolve reasoning
          effort for THIS model, build the PassConfigs
       -> two_pass_pipeline.run_pipeline(product=<model key>)
          kael-beta      PASS 1 draft  (+ difficulty-router message)
                         EASY?  -> the draft is served
                         PASS 2 critic (draft appended as a review message)
          kael-pro-beta  PASS 1 three drafts at once (+ router message each)
                         all three EASY, whole and alike?  -> one draft is served
                         PASS 2 fusor  merges the survivors into one answer
                         PASS 3 critic reviews the fused answer
       -> rebrand model to the called model's slug, bill, log, respond in the
          caller's format
```

The critic is skipped when the draft is empty/filtered or the router rated the
request `EASY`; if the critic call fails, the draft is served. On Kael Pro Beta,
fusion is skipped when only one draft survives, a draft that is far behind two
whole ones is cancelled after a grace period, and if the fusor fails the
consensus draft goes to the critic instead. The EASY shortcut applies only when
all three drafts came back, whole, rated EASY and alike. Details: `../../../README.md`,
section "Two passes, and when the critic is skipped", and the docstring of
`app/two_pass_pipeline.py`.

## Upstream

- Both passes go through **OpenRouter's Chat Completions** endpoint
  (`OPENROUTER_BASE_URL`, `OPENROUTER_API_KEY`). No provider is pinned:
  routing is **speed-first**. Each pass sends `provider.sort: "throughput"`
  (fastest tokens/sec first), a hard `max_price` ceiling ($0.30 in /
  $1.20 out per 1M tokens, same for both passes), a soft
  `preferred_max_latency` of 2 s at p90, and `allow_fallbacks: True`. The
  numbers are in `draft_provider_routing` / `critic_provider_routing`.
- If no provider is at or under a pass's price ceiling, OpenRouter refuses
  the request. The engine logs `NO_ELIGIBLE_PROVIDER` and returns the caller
  a generic 503 (`upstream_unavailable`); a critic-pass failure still serves
  the draft.
- If a host dies mid-generation, OpenRouter ends the stream with
  `finish_reason: "error"` and cannot re-route (it only falls back before
  tokens flow). The engine then re-runs that pass once, silently, with the
  failed host in `provider.ignore` (everything else in the routing, including
  the price ceiling, is kept), so it lands on the next-fastest host. The
  caller is told only if the re-run fails too. Not retried: `content_filter`,
  a timeout, and any pass whose answer has already started reaching the
  caller. Logs: `MIDSTREAM_FAILOVER` / `MIDSTREAM_FAILOVER_EXHAUSTED`.
- Every upstream call carries a `session_id`
  (`provider_routing.derive_session_id`: a hash of the account and the
  conversation's first user message) so OpenRouter's prompt-cache sticky
  routing keeps follow-up turns on the same host. Each finished pass logs
  `[routing] ... served_by=<host> prompt_tokens=N cached_tokens=N`.
- `draft_model` and `critic_model`: both `deepseek/deepseek-v4.1-flash`.
- The thinking-title summarizer is NOT on that model. It has its own list,
  `summarizer_models` (Ling 3.0 Flash, then DeepSeek V4.1 Flash as the last
  resort), sent as OpenRouter's `models` fallback array: the second model is
  tried only when the first errors. Its `summarizer_provider_routing` sorts
  by **price** (not throughput), with a hard `max_price` of $0.15 in / $0.60
  out per 1M tokens, a loose, soft `preferred_max_latency` of 2 s at **p50**
  (a guide, never a cut-off), and `allow_fallbacks: True`. Reason: roughly
  85-90% of the summarizer's cost is input tokens, so cheap input matters,
  while a title still has to arrive quickly. Ling 3.1 Flash is deliberately
  not in the list (free launch promotion, slow tail).
- Chat Completions has no separate high-priority instructions field, so the
  ordering is explicit: `system_identity` (the master prompt, which ranks
  every other layer itself) first; then the caller's content, ending with
  the `<kael_context_...>` message (real date; skills later); then the
  difficulty-router instruction on pass 1 or the critic prompt on pass 2.
  (Before 2026-10-01 `system_identity` went last, closest to generation.)
- Streaming usage is reliable: OpenRouter ends every stream with a chunk
  carrying full `usage`.
- Streamed tool calls relay incrementally to Chat Completions callers.
  Responses-shaped callers get the complete tool call in the final event.
  Anthropic-shaped callers are served by `app/anthropic_api.py`.

## Reasoning effort (caller-tunable)

The upstream model exposes three real efforts: `low`, `high`, `max` (no
`medium`). What a caller sends is a **tier**, and `_TIER_DEFINITIONS` in
`config.py` says what each tier runs. Each model's `reasoning_tiers` is the
subset of that table it accepts (built with `_pick_tiers`):

| Tier | Model | Draft | Fusor | Critic | Calls |
|---|---|---|---|---|---|
| `low` (default) | `kael-beta` | high | none | low | 2 |
| `high` | `kael-beta` | high | none | high | 2 |
| `max` | `kael-beta` | max | none | max | 2 |
| `z-low` (default) | `kael-pro-beta` | 3x high, concurrent | high | high | 5 |
| `z-high` | `kael-pro-beta` | 3x max, concurrent | max | max | 5 |

- Chat Completions and Anthropic Messages: top-level `"reasoning_effort": "high"`
- Responses: `"reasoning": {"effort": "high"}`
- Default when unset: the model's own `default_reasoning_tier` (`low` for
  `kael-beta`, `z-low` for `kael-pro-beta`).
- A model accepts only its own tiers. Sending the other model's tier is a `400`
  with `param: "reasoning_effort"` whose message names the model that offers it
  (for example, `z-low` sent to `kael-beta` says to use `kael-pro-beta`). Any
  other value is a `400` that lists the called model's own tiers. There is no
  `off`, and nothing is silently run at a different tier.
- **Per-key pin.** An API key can pin a tier (`api_keys.thinking_level`, set on
  the dashboard). The pin wins over the request, and the request's own value is
  then not validated. A tier belongs to one model, so a pin applies only on that
  model: a key pinned to `z-low` is pinned on `kael-pro-beta` and acts as "SDK"
  (the request decides) on `kael-beta`. See `_pinned_tier()` in
  `app/kael_pipeline.py`.
- The z tiers add a fusion pass: `app/fusor/kael.py` is its prompt. See
  `../../../README.md`, section "Thinking tiers, and the z tiers".

This is the only caller-tunable model setting; sampling parameters are ignored
by design.

## Config fields (`config.py`)

On each model dict (`KAEL_BETA`, `KAEL_PRO_BETA`):

| Field | Meaning |
|---|---|
| `key` | The model's key in `config.PRODUCTS`. Equal to `slug`. Stored in the database |
| `slug`, `label`, `tagline`, `best_for` | Customer-facing identity (public catalog) |
| `aliases` | Accepted `model` names. Only the model's own slug |
| `reasoning_tiers` | The tiers this model accepts: per tier, draft/fusor/critic effort and the number of concurrent drafts |
| `default_reasoning_tier` | Tier used when a caller sends none (and no key pin applies) |
| `customer_price_per_million` | What customers pay (`input`, `output`, `cached_input`). Its presence makes the model billed. One per model |
| `public` | Whether it appears in `GET /api/config` and `GET /v1/models` |

In `_SHARED`, so identical for both models:

| Field | Meaning |
|---|---|
| `draft_model`, `critic_model`, `fusor_model` | Upstream model IDs (never shown to customers) |
| `draft_provider_routing`, `critic_provider_routing`, `fusor_provider_routing` | OpenRouter `provider` object sent verbatim |
| `summarizer_models`, `summarizer_provider_routing` | Thinking-title summarizer's own model fallback list and `provider` object (never shown to customers) |
| `draft_max_output_tokens`, `max_output` | Output ceiling (conservative shared value) |
| `context_window` | Advertised context size |
| `system_identity` | Fixed identity instruction; also forbids naming any underlying vendor |
| `upstream_cost_per_million` | Internal margin tracking only, never shown to customers |
| `thinking_enabled` | Carried over from the original config. Nothing reads it: the engine always passes `thinking_enabled=True`. Do not rely on it |
| `supports_images` | Whether the Playground may attach pictures to a message for this model. Both models run the same image-capable upstream model, so it is `True` in `_SHARED`. The public API is not gated by it (it has always passed `image_url` parts through). Set it to `False` before pointing a pass at a text-only model |

## Billing

Charged by `app/billing.py`, at the price of the model that was called: first
call's input (minus the text Kael injects itself), last call's output; see
`../../../README.md`, section "Billing". Cached input is priced at exactly 20%
of input, for both models. On Kael Pro Beta the first call is the first draft
and the last call is the fusor (or the critic, when it finishes), so the extra
drafts are absorbed by the company, not billed.

## Endpoints

```
POST /kael-beta/v1/chat/completions       POST /kael-pro-beta/v1/chat/completions
POST /kael-beta/v1/responses              POST /kael-pro-beta/v1/responses
POST /kael-beta/v1/messages               POST /kael-pro-beta/v1/messages
GET  /kael-beta/v1/models                 GET  /kael-pro-beta/v1/models
Authorization: Bearer <any active sk-quan- key>
```

The path fixes the model, and the body's `model` field is not read on these
routes. They are registered in a loop over `config.PRODUCTS` by
`_register_model_routes()` in `app/main.py`, so a third model gets its own
routes without any new route code. The generic `/v1/*` routes resolve the model
from the request's `model` field instead; an unknown name is a `400` that lists
every valid one. A key is not tied to a model: any active key works on both.

## Adding a model

1. Add a dict in `config.py` that spreads `_SHARED`. Give it a unique `key`
   (also its `slug`), `reasoning_tiers`, `default_reasoning_tier`, aliases and
   `customer_price_per_million`.
2. Add it to `ALL_MODELS` in `../__init__.py`.
3. Add its key to the prompt registries in `app/router/__init__.py` and
   `app/critic/__init__.py` (and `app/fusor/__init__.py` if it has fusion
   tiers). A missing entry is a `KeyError` at request time.
4. Add it to `MODELS` in `frontend/src/lib/api.ts` and to
   `frontend/src/components/docs/facts.ts`, then update the docs pages.
5. A migration is needed only if a database column constrains the key. None
   does today, but the stored `product` and `model` values use the key, so do
   not rename one later without migrating the rows.
