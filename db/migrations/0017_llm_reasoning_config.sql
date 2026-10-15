-- 0017_llm_reasoning_config.sql  (applied to the live database as `llm_reasoning_config`, 2026-10-09)
-- Per-credential "thinking" settings for models that think (first user: OpenRouter's
-- inclusionai/ling-3.1-flash). One jsonb column on llm_credentials:
--
--   {}                                   -> the model's own default behaviour (nothing is sent)
--   {"effort": "high"}                   -> a native thinking level ("none" = thinking off)
--   {"max_tokens": 8000}                 -> a raw thinking-token budget (instead of a level)
--   {"show": false}                      -> ask the provider not to return the thinking text
--   (effort and max_tokens are mutually exclusive; the API validates, this only guards shape)
--
-- Purely additive: a new NOT NULL column with a constant default, so every existing row
-- becomes {} (= today's behaviour) and no data changes. No new policy — the existing
-- llm_credentials_owner_all RLS policy is row-level and already covers the new column.
--
-- Idempotent (IF NOT EXISTS / guarded constraint): applying it to a database that already has it is harmless.

begin;

alter table llm_credentials
    add column if not exists reasoning jsonb not null default '{}'::jsonb;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.llm_credentials'::regclass
          and conname = 'llm_credentials_reasoning_is_object'
    ) then
        alter table llm_credentials
            add constraint llm_credentials_reasoning_is_object
            check (jsonb_typeof(reasoning) = 'object');
    end if;
end
$$;

commit;
