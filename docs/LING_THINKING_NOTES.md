# Ling 3.1 Flash quick-connect + native thinking controls (2026-10-08)

## What it does

- **One-tap connect.** LLM Providers → Connect a credential → "Ling 3.1 Flash (free)". Provider
  (OpenRouter) and model (`inclusionai/ling-3.1-flash`) are preset; the person pastes only their
  OpenRouter key. Source of truth: `QUICK_MODELS` in `backend/app/services/provider_catalog.py`,
  served by `GET /connections/llm-credentials/quick-models`.
- **Native thinking levels.** `ReasoningProfile` (same file) records which levels a model
  natively accepts. Ling 3.1 Flash: Off, Low, Medium, High, Max (`xhigh`), or a raw thinking-token
  budget. Any other OpenRouter model gets a conservative generic profile (Low/Medium/High, no Off).
- **Toggles**, stored per credential in `llm_credentials.reasoning` (jsonb, migration 0013):
  `effort` (a level; `none` = thinking off) **or** `max_tokens` (budget), and `show` (false asks the
  provider not to return the thinking text). `{}` = the model's own default; nothing is sent.
  Editable after connecting via the "Thinking" button on a saved credential (PATCH `reasoning`).
- **How it reaches the model.** `llm_client.call_llm` sends OpenRouter's unified object as
  `extra_body={"reasoning": {...}}` (litellm's pass-through). Thinking on also raises `max_tokens`
  from 8192 so the thinking can't starve the answer/tool call (Ling's cap is 32,768, thinking included).
- **Fallback.** If the provider answers 400/422 mentioning reasoning/effort/thinking, the call is
  retried once immediately with the effort/budget removed (model default thinking) instead of
  failing the turn. It is logged as a warning.

## Migration

`db/migrations/0013_llm_reasoning_config.sql` — adds `llm_credentials.reasoning jsonb not null default '{}'`
plus an is-object CHECK. Additive and idempotent. The backend only writes the column when a thinking
config is actually set, so credentials left at the model default work even before the column exists.

**Numbering collision (needs a human decision):** this repo's `0012` is `llm_provider_presets`, but the
live Supabase project's migration history also contains `0012_workspace_fingerprint` (2026-10-03),
`session_attachments`, `rls_cross_reference_checks`, `rls_audit` and `phase6_advisor_fixes`
(2026-10-08) whose `.sql` files are **not in this repo**. Whatever produced them has code that is not
here either. Don't re-run anything from this repo against the live DB without comparing to
`list_migrations` first.

## NOT verified (no network / no real key where this was built)

1. That OpenRouter + the upstream provider accept every level for Ling (`xhigh` especially). Sources
   disagreed: one lists none/low/medium/high, another none through xhigh. The fallback above is the
   safety net; the level list is `MODEL_REASONING` in `provider_catalog.py` — trim it if `xhigh` 400s.
2. That the pinned `litellm==1.55.4` forwards `extra_body` to OpenRouter and surfaces the response's
   `reasoning` field. If thinking text comes back empty, bump litellm and re-test.
3. The frontend was syntax-checked with `tsc` only (dependencies weren't installable), not built.
4. Ling's free pricing was announced as running until **Oct 13, 2026, 9:00 AM PT**; after that the same
   model id is billed at whatever OpenRouter lists.

## Not done: showing the thinking in a session

`llm_client.LlmResponse.reasoning` now carries the thinking text, but `agent_loop.py` does not store
it, and this repo's frontend has no session chat view to show it in. To store it, add the thinking to
the agent `message` event in the three `_append(session_id, "agent", "message", ...)` sites
(`{"text": ..., "step": ..., "reasoning": response.reasoning}`), allow a text-less message when
only `reasoning` exists, and make `message_builder` render an empty-text step as `content=None`
(Anthropic rejects empty text blocks) and skip an empty message with no tool calls. Never replay the
thinking text to the model.
