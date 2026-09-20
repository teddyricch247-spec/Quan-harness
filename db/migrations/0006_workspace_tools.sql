-- 0006_workspace_tools.sql
-- Quan Harness — Phase 2 — §14 (Tool Layer), §23 (Workspace), §25 (Branch strategy).
--
-- Everything Phase 1 needed for these features already exists: project_workspaces
-- (0004), checkpoints/session_events/approval_requests/audit_log (0005). This
-- migration adds exactly the pieces Phase 2's own implementation order steps 5-8
-- depend on that weren't anticipated by that schema:
--
--   1. project_secrets — §14.3's execute_bash spec says "if the command text
--      references a registered project_secrets name ... it's exported as an
--      environment variable." No table for that existed yet. Not explicitly
--      listed in this phase bundle's own numbered scope, but execute_bash (step 8)
--      directly depends on it existing, the same way step 6's file tools directly
--      depend on §23.4's checkpoint mechanics already being schema-ready. See
--      /docs/PHASE2_NOTES.md.
--   2. projects.harness_branch_ready — §25: "the first time it's Pushed... Push
--      creates one [the harness/workspace branch] ... every subsequent Push
--      updates this one branch." A boolean flag is cheaper and more honest than
--      re-querying GitHub on every Push to check whether the branch exists yet.
--   3. sessions.read_only / read_only_reason — §23.4: a checkpoint restore
--      "closes every other currently-open session on that project to permanently
--      read-only," and the 2-writable-session concurrency cap does the same to
--      the least-recently-used session when a 3rd is opened. Neither is the same
--      thing as the existing `status='archived'` (that's an explicit user
--      action with different semantics) so it needed its own column, not a new
--      enum value shoehorned into `status`.

create table project_secrets (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    name text not null,                 -- referenced in execute_bash commands as $NAME (§14.3)
    secret_ref uuid not null,           -- Vault id — see app/services/vault.py; raw value never stored here
    created_at timestamptz not null default now(),
    unique (project_id, name)
);
alter table project_secrets enable row level security;
create policy project_secrets_owner_all on project_secrets
    for all using (exists (select 1 from projects p where p.id = project_secrets.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_secrets.project_id and p.user_id = auth.uid()));


alter table projects add column harness_branch_ready boolean not null default false;


alter table sessions add column read_only boolean not null default false;
alter table sessions add column read_only_reason text
    check (read_only_reason is null or read_only_reason in ('concurrency_cap', 'checkpoint_restore'));

-- §23.4: "checkpoint-restore capability follows whichever session most recently
-- edited that project's workspace" — computed as the session_id of that
-- project's most recent checkpoint, not stored redundantly as its own column.
-- This index is what makes that lookup (app/repositories/checkpoints.py's
-- get_active_session_id) cheap instead of a full table scan per request.
create index checkpoints_project_created_idx on checkpoints (project_id, created_at desc);
