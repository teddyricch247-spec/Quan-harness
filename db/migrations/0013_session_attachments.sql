-- 0013_session_attachments.sql
-- Quan Harness — Phase 6.1 (step 19) — image input on user messages.
--
-- A picture the person attaches to a message (a screenshot of a visual bug, a design to match). The pixels live
-- HERE, not in `session_events`: the event log carries only metadata ({id, filename, media_type, width, height,
-- byte_size}) on the user's `message` / `user_interrupt` event — the same rule §14.9 already applies to the agent's
-- own browser screenshots, for the same reason (a database row per image in the transcript would be re-sent to every
-- client and counted into every token estimate). agent_loop loads the few most recent images for a call and
-- message_builder places them on the user's message; see app/services/image_input.py.
--
-- Two-step by design: the upload (POST /sessions/{id}/attachments) creates a row with message_event_id NULL; the
-- message that follows names the ids, and agent_loop CLAIMS them for that message (a unique negative token while the
-- message event is being written), then links the real event id. The claim is atomic (one UPDATE ... WHERE
-- message_event_id IS NULL), so two messages can never both own one picture. An upload that is never attached, or a
-- claim whose message never got written, is deleted after an hour (image_input.STALE_PENDING_SECONDS).
--
-- Limits are enforced twice on purpose — in Python (image_input.sniff_image, from the file's own bytes) and here —
-- so a direct PostgREST insert by a signed-in user can't store anything the backend would have refused.
-- 3 MiB of image = 4 MiB of base64 text (ceil(3145728 / 3) * 4 = 4194304).
--
-- RLS: owner-only through session -> project, the same shape as session_events. No cross-reference column that the
-- policy would have to vouch for (message_event_id deliberately has no foreign key).
--
-- Purely additive: the previous backend never reads or writes this table, so it is safe to apply before deploying
-- the new code. Roll back with `drop table session_attachments;`.

create table session_attachments (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references sessions(id) on delete cascade,
    filename text not null check (char_length(filename) between 1 and 200),
    media_type text not null check (media_type in ('image/png','image/jpeg','image/webp','image/gif')),
    width integer not null check (width between 1 and 8000),
    height integer not null check (height between 1 and 8000),
    byte_size integer not null check (byte_size between 1 and 3145728),
    data_b64 text not null check (char_length(data_b64) between 1 and 4194304),
    message_event_id bigint,        -- NULL = uploaded, not attached yet; negative = claimed by a message being written; positive = that event's id
    created_at timestamptz not null default now()
);
create index session_attachments_session_idx on session_attachments (session_id, created_at);
alter table session_attachments enable row level security;
create policy session_attachments_owner_all on session_attachments
    for all using (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = session_attachments.session_id and p.user_id = auth.uid()))
    with check (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = session_attachments.session_id and p.user_id = auth.uid()));

comment on table session_attachments is 'Phase 6.1: pictures attached to user messages. Pixels live here, never in session_events. See app/services/image_input.py.';


-- The three state transitions, as functions, so the backend never has to ask PostgREST to echo a multi-megabyte
-- row back just to learn which rows it changed: each returns metadata (or a count) only. Service role only — the
-- backend is the sole caller (search_path is pinned, per Supabase's security advisor) (a signed-in user can still read/insert their own rows directly through RLS above,
-- but has no business moving a row between message states).

create function claim_session_attachments(p_session_id uuid, p_ids uuid[], p_token bigint)
returns table (id uuid, filename text, media_type text, width integer, height integer, byte_size integer)
language sql set search_path = public, pg_temp as $$
    update session_attachments a
       set message_event_id = p_token
     where a.session_id = p_session_id and a.id = any(p_ids) and a.message_event_id is null
    returning a.id, a.filename, a.media_type, a.width, a.height, a.byte_size;
$$;

create function link_session_attachments(p_session_id uuid, p_token bigint, p_event_id bigint)
returns integer
language sql set search_path = public, pg_temp as $$
    with u as (
        update session_attachments set message_event_id = p_event_id
         where session_id = p_session_id and message_event_id = p_token
        returning 1
    ) select count(*)::integer from u;
$$;

create function release_session_attachments(p_session_id uuid, p_token bigint)
returns integer
language sql set search_path = public, pg_temp as $$
    with u as (
        update session_attachments set message_event_id = null
         where session_id = p_session_id and message_event_id = p_token
        returning 1
    ) select count(*)::integer from u;
$$;

revoke all on function claim_session_attachments(uuid, uuid[], bigint) from public, anon, authenticated;
revoke all on function link_session_attachments(uuid, bigint, bigint) from public, anon, authenticated;
revoke all on function release_session_attachments(uuid, bigint) from public, anon, authenticated;
grant execute on function claim_session_attachments(uuid, uuid[], bigint) to service_role;
grant execute on function link_session_attachments(uuid, bigint, bigint) to service_role;
grant execute on function release_session_attachments(uuid, bigint) to service_role;
