-- Real conversation persistence for the admin chatbot: sessions the user
-- can switch between, each locked to the model it was started with
-- ("Quan Pro", "DeepSeek V4 Flash", or "DeepSeek V4 Pro") — matching the
-- product's own request that a session not be re-pointed at a different
-- AI mid-conversation. chat_debug_traces (separate table, separate
-- migration 0002) remains the diagnostic log; this is the actual source
-- of truth the UI reads from to restore a conversation after a refresh
-- or a session switch.
--
-- Already applied directly to the live Supabase project (ref redacted — see internal ops notes) via
-- the Supabase MCP tool. This file exists so the change is versioned in
-- the repo and reproducible on a fresh project if you ever need one.

create table if not exists public.chat_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  model text not null,               -- internal product key ('pro'/'ultra') for every session
                                      -- created via the in-app chat feature (app/main.py's
                                      -- POST /api/chat/sessions, added 2026-08-20). Column name
                                      -- predates that feature and stayed as-is rather than
                                      -- renaming a live column for a naming preference; existing
                                      -- rows from the deleted admin console may still say
                                      -- 'deepseek-v4-flash' (direct-DeepSeek, no proxy — no
                                      -- longer resumable, see main.py's _resolve_session_product())
                                      -- or 'quan-pro' (resolves to 'pro' via config.MODEL_TO_PRODUCT)
  title text not null default 'New chat',
  thinking_enabled boolean not null default false,
  reasoning_effort text,
  created_at timestamptz not null default now(),
  last_message_at timestamptz not null default now()
);

create index if not exists chat_sessions_user_id_idx on public.chat_sessions (user_id, last_message_at desc);

alter table public.chat_sessions enable row level security;
-- Closed by default, same as every other table in this app — only the
-- backend (service_role) reads/writes; a signed-in user only ever sees
-- their own sessions through /chatbot/api/sessions, scoped server-side.

create table if not exists public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.chat_sessions(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists chat_messages_session_id_idx on public.chat_messages (session_id, created_at);

alter table public.chat_messages enable row level security;
-- Same closed-by-default pattern — ownership is enforced by joining
-- through chat_sessions.user_id server-side, not by a direct policy on
-- this table.
