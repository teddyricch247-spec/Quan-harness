-- 0014_rls_cross_reference_checks.sql
-- Quan Harness — Phase 6.2 (step 20) — close the cross-account REFERENCE paths the isolation suite found.
--
-- THE GAP. Every owner policy so far checks ONE thing: that the row's own scoping column (user_id / project_id /
-- session_id / mcp_server_id) is the caller's. A row also carries other foreign keys, and a foreign key is
-- checked by Postgres without RLS — so a signed-in user, talking to PostgREST directly with their own token (the
-- anon key ships in the frontend), could write a row of THEIR OWN that POINTS AT SOMEONE ELSE'S:
--
--     project_mcp_access.mcp_server_id   B's project -> A's connector (and, in principle, A's connector credentials)
--     checkpoints / project_memory_log.session_id          B's row -> A's session
--     session_events.parent_event_id                       B's event -> A's event
--     sessions.schedule_id, project_schedules.last_session_id, project_notifications.deploy_run_id,
--     audit_log.project_id / session_id
--
-- (projects.llm_credential_id / github_credential_id are NOT in that list: the earlier ownership triggers on
-- `projects` — check_llm_credential_owner / check_github_credential_owner — already refuse a reference to someone
-- else's credential, and the isolation suite accepts that refusal. They are the model for what is added here.)
--
-- Nothing of A's was readable through any of them, and the backend re-checks ownership (the turn loop intersects
-- granted connectors with the user's own; credentials are looked up with get_for_user), so none of it was a live
-- leak. But a reference is not harmless: several of these are ON DELETE NO ACTION or CASCADE, so B's row could make
-- A's own delete of an event / session FAIL, or A's delete of a session silently remove B's rows. And
-- "the backend happens to re-check" is not what §5 promises — the promise is that no path lets one account touch
-- the other's data. These WITH CHECKs make the database refuse the write.
--
-- WHAT CHANGES. Each affected owner policy keeps its USING clause exactly as it was (so what a user can SEE is
-- untouched) and gains one more condition in WITH CHECK: every reference the row carries must point at something the
-- same user owns, and — for session/schedule/run references — inside the same project. Existing rows are not
-- re-validated (a policy only runs on writes). The backend uses the service role, which bypasses RLS, so nothing
-- the application does changes.
--
-- Two of the checks (session_events.parent_event_id, project_schedules.last_session_id) cannot be written as a plain
-- sub-select: sessions' policy already looks at project_schedules, and session_events would be looking at itself, so
-- Postgres would stop with "infinite recursion detected in policy". They go through two tiny SECURITY DEFINER
-- functions in a schema that PostgREST does not expose (`private`), which answer one yes/no question each. They only
-- ever run as a policy condition, on ids the caller is already writing into their own row.
--
-- ALSO HERE: project_workspaces.sprite_handle gets a unique index. Two projects must never name the same workspace
-- machine — that would put one account's agent inside another account's files — and nothing in the schema said so;
-- a client could also set their own row's handle to any string. (The table is empty today.)
--
-- NOT FIXED HERE, deliberately: the seven *_ref columns that hold vault secret ids (llm_credentials.api_key_ref,
-- github_credentials.token_ref, mcp_servers.{auth_token_ref,oauth_client_secret_ref,oauth_session_ref},
-- preview_secrets.secret_ref, project_secrets.secret_ref) have no foreign key and a signed-in client can write them.
-- Pointing one at another account's vault id needs that id, which is a random uuid no client is ever shown, so it is
-- not exploitable today — but it is the one place isolation still rests on an id staying secret. See
-- docs/PHASE6_NOTES.md ("Known gap") for the options; test_isolation_matrix.py pins it as an expected failure.
--
-- Safe to apply on a live database; roll back by re-creating each policy's WITH CHECK from its migration of origin
-- (the old text is the 'with_check' value in the notes) and `drop index project_workspaces_sprite_handle_key;`.

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to anon, authenticated;

create function private.event_in_session(p_event_id bigint, p_session_id uuid)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
    select exists (select 1 from public.session_events e where e.id = p_event_id and e.session_id = p_session_id);
$$;

create function private.session_in_project(p_session_id uuid, p_project_id uuid)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
    select exists (select 1 from public.sessions s where s.id = p_session_id and s.project_id = p_project_id);
$$;

revoke all on function private.event_in_session(bigint, uuid) from public;
revoke all on function private.session_in_project(uuid, uuid) from public;
grant execute on function private.event_in_session(bigint, uuid) to anon, authenticated;
grant execute on function private.session_in_project(uuid, uuid) to anon, authenticated;


alter policy project_mcp_access_owner_all on project_mcp_access with check (
    exists (select 1 from projects p where p.id = project_mcp_access.project_id and p.user_id = auth.uid())
    and exists (select 1 from mcp_servers s where s.id = project_mcp_access.mcp_server_id and s.user_id = auth.uid())
);

alter policy checkpoints_owner_all on checkpoints with check (
    exists (select 1 from projects p where p.id = checkpoints.project_id and p.user_id = auth.uid())
    and exists (select 1 from sessions s where s.id = checkpoints.session_id and s.project_id = checkpoints.project_id)
);

alter policy project_memory_log_owner_all on project_memory_log with check (
    exists (select 1 from projects p where p.id = project_memory_log.project_id and p.user_id = auth.uid())
    and exists (select 1 from sessions s where s.id = project_memory_log.session_id and s.project_id = project_memory_log.project_id)
);

alter policy audit_log_owner_all on audit_log with check (
    user_id = auth.uid()
    and (project_id is null or exists (
        select 1 from projects p where p.id = audit_log.project_id and p.user_id = auth.uid()))
    and (session_id is null or exists (
        select 1 from sessions s join projects p on p.id = s.project_id where s.id = audit_log.session_id and p.user_id = auth.uid()))
);

alter policy sessions_owner_all on sessions with check (
    exists (select 1 from projects p where p.id = sessions.project_id and p.user_id = auth.uid())
    and (schedule_id is null or exists (
        select 1 from project_schedules ps where ps.id = sessions.schedule_id and ps.project_id = sessions.project_id))
);

alter policy project_schedules_owner_all on project_schedules with check (
    exists (select 1 from projects p where p.id = project_schedules.project_id and p.user_id = auth.uid())
    and (last_session_id is null or private.session_in_project(project_schedules.last_session_id, project_schedules.project_id))
);

alter policy project_notifications_owner_all on project_notifications with check (
    exists (select 1 from projects p where p.id = project_notifications.project_id and p.user_id = auth.uid())
    and (deploy_run_id is null or exists (
        select 1 from deploy_runs d where d.id = project_notifications.deploy_run_id and d.project_id = project_notifications.project_id))
);

alter policy session_events_owner_all on session_events with check (
    exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = session_events.session_id and p.user_id = auth.uid())
    and (parent_event_id is null or private.event_in_session(session_events.parent_event_id, session_events.session_id))
);

create unique index project_workspaces_sprite_handle_key on project_workspaces (sprite_handle);
