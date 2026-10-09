-- 0012_llm_provider_presets.sql
-- BYOK provider presets: widen llm_credentials.provider so the popular
-- OpenAI-compatible endpoints (Groq, Together, Fireworks, DeepSeek, Mistral, xAI,
-- Cerebras) are first-class providers instead of "custom + hand-typed base URL".
--
-- Why a first-class value rather than `custom` + a stored base_url: litellm already
-- knows each of these providers' base URL and quirks under its own model-string
-- prefix (groq/, together_ai/, ...). Routing through that prefix means no URL is
-- stored or can go stale, and the UI can show "Groq" rather than "custom".
--
-- The list here MUST match backend/app/services/provider_catalog.py (PROVIDER_IDS)
-- and backend/app/models/schemas.py (LlmProvider) — tests/test_provider_catalog.py
-- reads this file and fails if they drift.
--
-- Purely additive: the new CHECK accepts a strict superset of the old one
-- ('anthropic','openai','google','openrouter','custom'), so every existing row stays
-- valid and no data changes. No new columns, no RLS changes (the existing
-- llm_credentials_owner_all policy is untouched).

begin;

alter table llm_credentials drop constraint llm_credentials_provider_check;

alter table llm_credentials add constraint llm_credentials_provider_check
    check (provider in (
        'openrouter','anthropic','openai','google',
        'groq','together','fireworks','deepseek','mistral','xai','cerebras',
        'custom'
    ));

commit;
