-- 0007_memory_and_project_knowledge.sql
-- Quan Harness — Phase 4.1/4.2 — §20 (Memory System) and §21 (Project Knowledge).
--
-- Four new tables:
--   1. project_memory      — one curated, size-bounded row per project (memory_md,
--      injected verbatim into every session's context — §17/§18's
--      WHAT_YOU_KNOW_ABOUT_THIS_PROJECT). Never touched by the agent (no tool exists
--      for it); written only by app/services/memory_extraction.py, and directly
--      view/edit/clear-able by the project's owner from Settings (§20's "manual
--      control" line).
--   2. project_memory_log  — the unedited, append-only raw material behind it: one
--      row per completed-or-stuck turn's final report, verbatim. Never injected into
--      any prompt itself (§20 is explicit) — exists purely so the curated memory_md
--      can be rebuilt if a bad extraction ever corrupts it.
--   3. build_user_memory   — the same idea as project_memory, at the account level,
--      for Build specifically. Named that way rather than plain user_memory because
--      Ask keeps its own separate ask_user_memory store in a later phase — the two
--      are never read by each other's loop, under any circumstance (§20's own line).
--   4. project_knowledge   — §21's optional, per-project, human-authored notes. The
--      deliberate counterpart to memory: written only by the person (their own
--      project Settings), read (never written) by the agent loop, and pulled into a
--      session's context only when a note's own keyword/path trigger actually fires.
--
-- One schema change to an existing table: session_events.event_type gains
-- 'project_knowledge_injected' — a system-role bookkeeping event the loop appends
-- the first time a given note triggers in a session, so "only ever injected once
-- per session" (§21) is reconstructed from the durable event log the same way
-- every other per-session fact in this codebase is (crash_recovery.py's dangling-
-- call scan, agent_loop.py's own _reconstruct_viewed_paths) — never held only in
-- local turn-loop state, which would forget everything already triggered in an
-- earlier turn of the same session. message_builder.build_messages' own fallthrough
-- branch already skips any event_type it doesn't explicitly render (see that
-- module's docstring), so this new type reaches the model exactly nowhere — it's
-- pure bookkeeping, not a conversational turn.

create table project_memory (
    project_id uuid primary key references projects(id) on delete cascade,
    memory_md text not null default '',
    updated_at timestamptz not null default now()
);
alter table project_memory enable row level security;
create policy project_memory_owner_all on project_memory
    for all using (exists (select 1 from projects p where p.id = project_memory.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_memory.project_id and p.user_id = auth.uid()));


create table project_memory_log (
    id bigint generated always as identity primary key,
    project_id uuid not null references projects(id) on delete cascade,
    session_id uuid not null references sessions(id) on delete cascade,
    report text not null,
    created_at timestamptz not null default now()
);
alter table project_memory_log enable row level security;
create policy project_memory_log_owner_all on project_memory_log
    for all using (exists (select 1 from projects p where p.id = project_memory_log.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_memory_log.project_id and p.user_id = auth.uid()));
create index project_memory_log_project_created_idx on project_memory_log (project_id, created_at desc);


-- user_id is the primary key directly (not a surrogate uuid id) — there is exactly
-- one build_user_memory row per account, the same one-row-per-owner shape
-- project_memory already uses for project_id. Cascades on account delete, closing
-- the same gap app/routers/account.py's own docstring already promises: "Cascades
-- to every project, session, credential, and piece of memory owned by that account."
create table build_user_memory (
    user_id uuid primary key references auth.users(id) on delete cascade,
    memory_md text not null default '',
    updated_at timestamptz not null default now()
);
alter table build_user_memory enable row level security;
create policy build_user_memory_owner_all on build_user_memory
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());


create table project_knowledge (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    name text not null,
    body text not null,
    trigger_type text not null check (trigger_type in ('keyword', 'path')),
    -- 'keyword': a word/phrase — matched (case-insensitively) against the task text
    --   that started this turn, or against the path of any file the agent has
    --   viewed or created this session (see app/services/project_knowledge.py).
    -- 'path': a glob pattern — matched against the path of any file the agent has
    --   viewed or created this session.
    trigger_value text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
alter table project_knowledge enable row level security;
create policy project_knowledge_owner_all on project_knowledge
    for all using (exists (select 1 from projects p where p.id = project_knowledge.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_knowledge.project_id and p.user_id = auth.uid()));


-- session_events.event_type's CHECK constraint (0005_sessions.sql) is a real,
-- enforced constraint, unlike audit_log.tool's plain descriptive comment below —
-- this needs an actual ALTER, not just an edit to a comment nobody enforces.
alter table session_events drop constraint if exists session_events_event_type_check;
alter table session_events add constraint session_events_event_type_check
    check (event_type in (
        'message','tool_call','tool_result','approval_request','approval_response',
        'stuck_notice','condensation_summary','error','user_interrupt','plan_update',
        'project_knowledge_injected'
    ));
