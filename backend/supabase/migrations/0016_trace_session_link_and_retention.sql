-- Playground diagnostic records (chat_debug_traces) are deleted with the
-- conversation they belong to, and every diagnostic record is deleted when it
-- is 30 days old (owner decision, 2026-10-13; see the Privacy Policy, "Data
-- Retention", and LEGAL_UPDATES.md).
--
-- Why: a Playground request writes one diagnostic row that keeps short
-- excerpts of the user's last message and of Kael's answer (last_user_message,
-- content_preview, draft_content_preview). Until now that row had no link to
-- the conversation, so deleting a conversation left the excerpts behind, and
-- the row's user_id is ON DELETE SET NULL, so deleting an account left them
-- behind too, with no owner and no expiry.
--
-- What this does:
--   1. chat_debug_traces.session_id, nullable, references chat_sessions with
--      ON DELETE CASCADE. New Playground requests set it (app/main.py puts the
--      conversation id on the requestor; two_pass_pipeline passes it to
--      start_chat_trace). API requests never have one (no conversation).
--   2. purge_expired_chat_traces(retention): deletes every diagnostic row older
--      than the retention (default 30 days) and returns how many. The backend
--      calls it once a day from app/scheduled_checks.py. Executable by the
--      service role only, like deduct_balance / credit_balance.
--
-- Safe to run more than once. Old backend code keeps working after this (it
-- never sends session_id; the column is nullable). Rows written before this
-- migration have no session_id: they are removed by the 30-day purge, not by
-- deleting a conversation. The new backend code needs this migration applied
-- first (an insert that names an unknown column fails, and a failed trace
-- insert only loses that diagnostic row, never the request).

begin;

alter table public.chat_debug_traces
  add column if not exists session_id uuid
  references public.chat_sessions(id) on delete cascade;

comment on column public.chat_debug_traces.session_id is
  'The Playground conversation this diagnostic row belongs to (migration 0016). Deleting the conversation deletes the row. NULL for API requests and for rows written before 0016.';

create index if not exists chat_debug_traces_session_id_idx
  on public.chat_debug_traces (session_id)
  where session_id is not null;

create or replace function public.purge_expired_chat_traces(p_retention interval default interval '30 days')
returns integer
language plpgsql
set search_path = ''
as $$
declare
  v_deleted integer;
begin
  if p_retention is null or p_retention < interval '1 day' then
    raise exception 'purge_expired_chat_traces: retention must be at least 1 day';
  end if;
  delete from public.chat_debug_traces
    where created_at < now() - p_retention;
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

revoke all on function public.purge_expired_chat_traces(interval) from public, anon, authenticated;
grant execute on function public.purge_expired_chat_traces(interval) to service_role;

commit;

-- Verify afterwards:
--   select column_name from information_schema.columns
--   where table_schema = 'public' and table_name = 'chat_debug_traces' and column_name = 'session_id';
--   select has_function_privilege('anon', 'public.purge_expired_chat_traces(interval)', 'execute');  -- false
--   select has_function_privilege('service_role', 'public.purge_expired_chat_traces(interval)', 'execute');  -- true
