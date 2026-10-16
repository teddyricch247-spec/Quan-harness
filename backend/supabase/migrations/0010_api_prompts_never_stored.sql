-- Rule (owner, 2026-10-06): text sent through the Kael API is never stored.
-- Only the in-app Playground and Chat (source = 'app_chat') keep prompt and
-- answer text. API traffic keeps counts, timings and status only.
--
-- The application stopped writing API text in the same change
-- (supabase_client.py: CONTENT_TRACE_SOURCES, default-deny). This file does
-- the two things code cannot:
--
--   1. ERASE text that earlier API requests already left in chat_debug_traces.
--   2. Make the database itself refuse such text from now on, so the rule
--      holds even if a future code change forgets it.
--
-- Safe to run more than once. Step 1 is irreversible by design. In-app chat history (chat_messages) is untouched.

begin;

-- 1. Erase stored API text. Historical sources ('chatbot_direct',
--    'chatbot_console') came from the deleted admin console, not customers;
--    they are included because the rule below is "app_chat or nothing".
update public.chat_debug_traces
set last_user_message     = null,
    content_preview       = null,
    draft_content_preview = null
where source <> 'app_chat'
  and (last_user_message is not null
       or content_preview is not null
       or draft_content_preview is not null);

-- 2. Database-level guarantee. If this ever blocks an insert, the app just
--    skips that trace row (trace writes are best-effort) — requests are
--    never affected. Drop the constraint if you ever want to relax the rule.
alter table public.chat_debug_traces
  drop constraint if exists chat_debug_traces_api_text_never_stored;

alter table public.chat_debug_traces
  add constraint chat_debug_traces_api_text_never_stored
  check (
    source = 'app_chat'
    or (last_user_message is null
        and content_preview is null
        and draft_content_preview is null)
  );

commit;

-- Verify afterwards (expect 0):
--   select count(*) from public.chat_debug_traces
--   where source <> 'app_chat'
--     and (last_user_message is not null or content_preview is not null
--          or draft_content_preview is not null);
