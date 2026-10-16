-- Small consistency fixes found while rewriting the backend for the
-- Kael/Aura rename and Responses-API rebuild (2026-08-20). No table
-- shape changes, no data changes — comments and one stale column
-- default only. Already applied directly to the live project
-- (ref redacted — see internal ops notes) via the Supabase MCP tool; this file exists so
-- the change is versioned in the repo and reproducible on a fresh
-- project if you ever need one.

-- api_keys.scopes defaulted to {flash, pro, ultra} — 'flash' has named
-- nothing since the Flash tier was deleted entirely on 2026-08-19 (see
-- app/models/__init__.py's docstring). This column isn't actually read
-- anywhere in the app today (see app/api_keys.py: "any active key works
-- against any endpoint" — nothing gates on scopes), so this was inert
-- rather than actively wrong, but a fresh row's default listing a
-- product that can't exist is worth fixing while touching this area.
alter table public.api_keys
  alter column scopes set default array['pro', 'ultra']::text[];

comment on column public.chat_sessions.model is
  'internal product key (''pro''/''ultra'') for every session created via the in-app chat feature (app/main.py POST /api/chat/sessions, added 2026-08-20). Existing rows from the deleted admin console may still say ''deepseek-v4-flash'' (no longer resumable) or ''quan-pro'' (resolves to ''pro'').';

comment on column public.chat_debug_traces.source is
  '''app_chat'' (in-app chat feature) | ''api'' (real product-key traffic) | ''chatbot_direct''/''chatbot_console'' (historical only — admin console deleted 2026-08-19, no request can produce these anymore)';
