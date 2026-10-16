-- Playground conversations are called "conversations" in the product.
-- OPTIONAL and cosmetic: the backend already writes "New conversation" for new
-- rows and displays old "New chat" titles as "New conversation", so nothing
-- depends on this migration. Idempotent; safe to run more than once.
alter table public.chat_sessions alter column title set default 'New conversation';

update public.chat_sessions
   set title = 'New conversation'
 where lower(title) in ('new chat', 'untitled chat', 'new session');
