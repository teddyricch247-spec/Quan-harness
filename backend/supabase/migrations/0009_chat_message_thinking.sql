-- Playground: keep the thinking Kael streamed for each reply, so it can be
-- expanded after the reply is done and still be there after a reload.
--
-- chat_messages.thinking is a jsonb array of strings (the thinking titles Kael
-- streamed, in order). NULL for user messages and for every reply saved before
-- this migration. Nothing is rewritten; existing rows are untouched.
--
-- The backend works with or without this column (app/supabase_client.py falls
-- back to saving/reading chats without thinking if the database reports the
-- column missing), so deploy order does not matter. Until it is applied,
-- replies simply have no saved thinking.

alter table public.chat_messages
  add column if not exists thinking jsonb;

comment on column public.chat_messages.thinking is
  'Thinking titles Kael streamed for this assistant reply (jsonb array of strings, in order). NULL for user messages and for replies saved before migration 0009.';
