-- 0009_scheduling.sql
-- Quan Harness — Phase 4.5 — §26: Scheduling / Proactive Scanning.
--
-- Adds exactly two things:
--   1. project_schedules — the recurring-check config itself (§26: "a person
--      can configure a recurring check ... on a schedule (hourly, daily, or
--      a custom cron-style expression)"). Deliberately has no next_run_at
--      column — app/services/scheduler_rules.py computes due-ness on every
--      poll tick from frequency/cron_expression/last_run_at directly, so
--      there's exactly one place ("is this due right now?") that can drift
--      from the schedule's own config, instead of a second write path
--      (maintaining a cached next_run_at) that could fall out of sync with
--      it. See docs/PHASE4_5_NOTES.md for why.
--   2. sessions.trigger / sessions.schedule_id — §26: "a scheduled run starts
--      a session exactly the way a person's message would (§16.1)... The one
--      difference: a scheduled run treats every one of its own tool calls as
--      Ask." That one difference has to be *readable off the session itself*
--      (agent_loop.py's turn loop checks it every mutating tool call), so the
--      session needs to record which way it was started. Every session
--      created before this migration is implicitly trigger='user' — the
--      column default covers every existing row with no backfill statement
--      needed (this table has zero rows in the live project as of this
--      writing, but the same default is correct even with real rows in it).

create table project_schedules (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    description text not null,   -- stands in as the initiating user message (§16.1) on every run
    frequency text not null check (frequency in ('hourly', 'daily', 'custom')),
    -- Standard 5-field crontab syntax, interpreted in UTC. Required and only
    -- meaningful when frequency = 'custom' — the check below enforces that
    -- pairing at the schema level rather than trusting the API layer alone.
    cron_expression text,
    enabled boolean not null default true,
    last_run_at timestamptz,
    -- The session that run created. `on delete set null`, not cascade: if
    -- that session is later deleted, the schedule itself (and its history of
    -- *having* run) should survive — only the pointer to that one specific
    -- session goes away.
    last_session_id uuid references sessions(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (frequency <> 'custom' or cron_expression is not null)
);
alter table project_schedules enable row level security;
create policy project_schedules_owner_all on project_schedules
    for all using (exists (select 1 from projects p where p.id = project_schedules.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_schedules.project_id and p.user_id = auth.uid()));


alter table sessions add column trigger text not null default 'user' check (trigger in ('user', 'scheduled'));
alter table sessions add column schedule_id uuid references project_schedules(id) on delete set null;


-- Comment-only additions below — no schema change, nothing to re-run. Both
-- extend a text column's documented (not enforced — see 0005_sessions.sql,
-- neither `approval_requests.action_type` nor `audit_log.tool` has ever had
-- a CHECK constraint on its vocabulary) set of conventional values, the same
-- way Phase 4.1/4.2 extended audit_log.tool's own comment for 'memory'.
--
--   approval_requests.action_type gains 'scheduled_tool:<native_tool_name>'
--   — a native tool (str_replace / create_file / execute_bash / run_lint /
--   run_tests / update_plan) that a scheduled run's forced-Ask treatment
--   gated. The native-tool counterpart to 'mcp_tool:<server>:<tool>', for
--   the identical reason: outside a scheduled run, every one of those native
--   tools is always Auto and never generates an approval_requests row at all
--   (see agent_loop.py's _resolve_permission_for_call) — this value only
--   ever appears on a session whose trigger = 'scheduled'.
--
--   audit_log.tool gains 'schedule' — a person creating/editing/deleting/
--   manually running a project_schedules row from Settings (initiated_by =
--   'user'), and the scheduler loop itself starting a run
--   (initiated_by = 'system'). Distinct from the existing 'session' value
--   (routers/sessions.py's own interactive session-create audit rows) the
--   same way Phase 4.1/4.2 gave memory/knowledge writes their own 'memory'
--   category instead of reusing 'project' — "everything a given schedule
--   did" is a real, useful filter on its own.
