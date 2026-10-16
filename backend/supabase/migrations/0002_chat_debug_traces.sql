-- Per-request tracing for the chat pipeline (the in-app chat feature and
-- real API callers alike — both run through the exact same
-- app/two_pass_pipeline.py engine as of 2026-08-20, see app/main.py's
-- module docstring's "In-app chat feature" note), written AS the request
-- happens rather than only on success like usage_logs. Built so a request
-- that shows nothing in a UI can be diagnosed without guessing: if
-- content_preview ends up populated, the model answered and the backend
-- sent it out over SSE — a UI showing nothing after that is a frontend
-- bug, not a backend one. If content_preview is empty, the problem is
-- upstream of this server ever sending a byte back (and status/
-- error_message says why).
--
-- Already applied directly to the live Supabase project (ref redacted — see internal ops notes) via
-- the Supabase MCP tool. This file exists so the change is versioned in
-- the repo and reproducible on a fresh project if you ever need one.

create table if not exists public.chat_debug_traces (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  user_id uuid references auth.users(id) on delete set null,

  source text not null,                 -- 'app_chat' | 'api' | 'chatbot_direct' | 'chatbot_console'
                                         -- (the latter two are historical only — the admin console
                                         -- that produced them was deleted 2026-08-19 and no request
                                         -- can produce either value anymore; kept here as a note for
                                         -- reading old rows, not as live options)
  product text,                         -- pro / ultra — null only on pre-2026-08-19 rows from the
                                         -- deleted admin console's direct-DeepSeek (no-proxy) option;
                                         -- every current source value always sets this
  model text,                           -- upstream model(s) actually requested, e.g. "deepseek-v4-flash+deepseek-v4-flash"
  stream boolean not null default true,
  thinking_enabled boolean,
  reasoning_effort text,
  request_message_count int,
  last_user_message text,               -- last user turn, truncated — quick eyeball of what was asked

  status text not null default 'started',  -- started | upstream_error | critic_started | interrupted | timeout | done
  upstream_status_code int,

  draft_status text,                    -- ok_text / ok_tool_call / ok_text_and_tool_call / skipped_empty
                                         -- (skipped_empty is now the ONLY skip condition — see
                                         -- app/two_pass_pipeline.py's module docstring for the
                                         -- 2026-08-20 fix that removed "tool call" as a skip reason)
  draft_content_chars int,
  draft_content_preview text,
  draft_finish_reason text,

  chunks_from_upstream int not null default 0,
  chunks_sent_to_client int not null default 0,
  saw_content boolean not null default false,
  saw_reasoning boolean not null default false,
  finish_reason text,
  content_char_count int not null default 0,   -- chars actually streamed to the client in the final pass
  content_preview text,                        -- first ~1500 chars of what was actually sent to the client
  reasoning_char_count int not null default 0,

  error_message text,
  duration_ms int
);

create index if not exists chat_debug_traces_user_id_idx on public.chat_debug_traces (user_id);
create index if not exists chat_debug_traces_created_at_idx on public.chat_debug_traces (created_at desc);

alter table public.chat_debug_traces enable row level security;
-- Zero policies, intentionally — same closed-by-default pattern as
-- usage_logs / api_keys. Only the backend (service_role key) can read or
-- write this table directly; a signed-in user sees their own rows only
-- through the app's own /chatbot/api/traces endpoint, scoped server-side.
