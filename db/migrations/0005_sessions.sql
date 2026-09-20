-- 0005_sessions.sql
-- Quan Harness — Phase 1 — §10.3 of the spec: Sessions, events, approvals, audit.
--
-- Phase 1 only builds the data model and plain CRUD for `sessions` (create/list/get/
-- archive/delete) — there is no turn loop yet (that's Phase 3), so a session created
-- now just sits at status='idle' with no way to actually run an agent turn against it.
-- `checkpoints`, `session_events`, and `approval_requests` are created here because
-- they're part of the one standalone data model (§10 says as much), but nothing
-- writes to them yet — the agent core, the workspace service, and the approval flow
-- that populate them are Phase 2/3 work. See /docs/PHASE1_NOTES.md.

create table sessions (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    title text,
    status text not null default 'idle'
        check (status in ('idle','running','waiting_approval','completed','failed','stuck','archived')),
    branch_name text,                      -- nullable: unset until this project's first link/Push (Phase 2)
    base_branch text,
    pr_url text,
    plan jsonb not null default '[]'::jsonb,         -- [{step, status: pending|in_progress|done}] — Phase 3
    turn_iteration_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
alter table sessions enable row level security;
create policy sessions_owner_all on sessions
    for all using (exists (select 1 from projects p where p.id = sessions.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = sessions.project_id and p.user_id = auth.uid()));


-- Auto-created on every agent edit in later phases; FIFO-capped at 10 per project by
-- application logic. git_commit_sha refers to a *local, never-pushed* commit inside
-- the workspace's own hidden git history. Empty in Phase 1 — nothing writes here yet.
create table checkpoints (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    session_id uuid not null references sessions(id) on delete cascade,
    git_commit_sha text not null,
    conversation_snapshot jsonb not null,   -- full session_events payload at this point
    created_at timestamptz not null default now()
);
alter table checkpoints enable row level security;
create policy checkpoints_owner_all on checkpoints
    for all using (exists (select 1 from projects p where p.id = checkpoints.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = checkpoints.project_id and p.user_id = auth.uid()));


create table session_events (
    id bigint generated always as identity primary key,
    session_id uuid not null references sessions(id) on delete cascade,
    parent_event_id bigint references session_events(id),
    role text not null check (role in ('user','agent','system')),
    event_type text not null check (event_type in (
        'message','tool_call','tool_result','approval_request','approval_response',
        'stuck_notice','condensation_summary','error','user_interrupt','plan_update'
    )),
    content jsonb not null,
    created_at timestamptz not null default now()
);
alter table session_events enable row level security;
create policy session_events_owner_all on session_events
    for all using (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = session_events.session_id and p.user_id = auth.uid()))
    with check (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = session_events.session_id and p.user_id = auth.uid()));


create table approval_requests (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references sessions(id) on delete cascade,
    action_type text not null,   -- 'execute_bash_escalation' | 'mcp_tool:<server>:<tool>'
    payload jsonb not null,      -- for a multi-hunk diff proposed by an MCP merge tool, includes a `hunks` array
    status text not null default 'pending' check (status in ('pending','approved','rejected')),
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);
alter table approval_requests enable row level security;
create policy approval_requests_owner_all on approval_requests
    for all using (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = approval_requests.session_id and p.user_id = auth.uid()))
    with check (exists (select 1 from sessions s join projects p on p.id = s.project_id where s.id = approval_requests.session_id and p.user_id = auth.uid()));


create table audit_log (
    id bigint generated always as identity primary key,
    user_id uuid references auth.users(id) on delete set null,
    session_id uuid references sessions(id) on delete set null,           -- Build only
    -- ask_session_id intentionally has NO foreign key yet: it references chat_sessions(id),
    -- a table that belongs to the "Ask" surface built in a later phase (not Phase 1). Recorded
    -- as a plain uuid now so the column exists and audit rows can be written from day one;
    -- add `alter table audit_log add constraint audit_log_ask_session_fk
    -- foreign key (ask_session_id) references chat_sessions(id) on delete set null;`
    -- in the migration that creates chat_sessions.
    ask_session_id uuid,                                                   -- Ask only, FK added later — exactly one of
                                                                             -- session_id/ask_session_id is set,
                                                                             -- or neither for an account-level
                                                                             -- action with no session at all
    project_id uuid references projects(id) on delete set null,
    tool text not null,       -- 'bash' | 'file_edit' | 'web_search' | 'browser' | 'delegate_task'
                               -- | 'mcp:<server_name>' | 'llm_credential' | 'github_credential' | 'mcp_server_admin'
                               -- | 'push' | 'pull' | 'checkpoint_restore'
                               -- | 'plan' (update_plan) | 'unknown' (a tool name the agent loop doesn't recognize)
                               -- | 'mcp:unavailable' (a connector tool no longer granted to the project)
                               -- Comment-only addition after Phase 3 -- no schema change, nothing to re-run.
    action text not null,
    input jsonb,
    output_summary text,
    success boolean not null,
    initiated_by text not null default 'agent' check (initiated_by in ('agent','user','system')),
    created_at timestamptz not null default now()
);
alter table audit_log enable row level security;
create policy audit_log_owner_all on audit_log
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
