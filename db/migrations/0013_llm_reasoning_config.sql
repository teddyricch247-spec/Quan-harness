-- 0013_llm_reasoning_config.sql
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
-- NUMBERING NOTE: this repo's 0012 is llm_provider_presets, but the live Supabase project
-- also has a migration recorded as 0012_workspace_fingerprint (Oct 3) plus session_attachments,
-- rls_cross_reference_checks, rls_audit and phase6_advisor_fixes (Oct 8) whose .sql files are
-- not in this repo. The recorded names/versions on the live project are authoritative; this
-- file is idempotent (IF NOT EXISTS / guarded constraint) so applying it twice, or after those
-- land in the repo, is harmless.

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
