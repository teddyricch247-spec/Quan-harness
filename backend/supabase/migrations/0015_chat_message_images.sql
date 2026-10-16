-- Playground: pictures attached to a user message.
--
-- One row per picture. The picture itself is the base64 text of the bytes the
-- browser sent (already shrunk to a JPEG of at most ~1568 px by the page, so a
-- row is typically 100-500 KB). `message_id` points at the user's row in
-- chat_messages; deleting the message or the conversation deletes its pictures
-- (chat_messages already cascades from chat_sessions).
--
-- The list endpoint never reads `data`: GET /api/chat/sessions/{id} returns only
-- {id, mime} per picture, and the page fetches each picture's bytes from
-- GET /api/chat/sessions/{id}/images/{image_id} when it is shown. `data` is read
-- in bulk only to rebuild the history sent to the model on the next turn.
--
-- The backend works with or without this table (app/supabase_client.py): until
-- it exists, a message with pictures is still answered, but the pictures are not
-- kept, so they are missing after a reload and from later turns of the
-- conversation. Deploy order does not matter.
--
-- Storage note: pictures live in Postgres, not in Supabase Storage, to keep the
-- feature to one table with automatic cleanup. At the 20-picture-per-conversation
-- cap this is at most a few MB per conversation. If picture volume grows,
-- move `data` to a private Storage bucket and keep the rest of this table.

create table if not exists public.chat_message_images (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.chat_sessions(id) on delete cascade,
  message_id uuid not null references public.chat_messages(id) on delete cascade,
  position smallint not null default 0,          -- order within the message
  mime text not null check (mime in ('image/jpeg', 'image/png', 'image/webp', 'image/gif')),
  data text not null,                            -- base64, no data: prefix
  byte_size integer not null,                    -- decoded size
  created_at timestamptz not null default now()
);

create index if not exists chat_message_images_session_idx
  on public.chat_message_images (session_id, created_at, position);
create index if not exists chat_message_images_message_idx
  on public.chat_message_images (message_id);

alter table public.chat_message_images enable row level security;
-- Zero policies, like every other table in this app: only the backend
-- (service role) reads or writes it, and it scopes every read to the signed-in
-- user through chat_sessions.user_id.

comment on table public.chat_message_images is
  'Pictures attached to playground user messages (migration 0015). data = base64 of the image bytes.';
