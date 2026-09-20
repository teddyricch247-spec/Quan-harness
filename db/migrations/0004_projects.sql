-- 0004_projects.sql
-- Quan Harness — Phase 1 — §10.2 of the spec: Projects, workspaces, and their
-- credential selections.
--
-- project_workspaces exists here as a schema placeholder only in Phase 1: a row is
-- created for every new project (billing_state='cold', a stub sprite_handle) so the
-- foreign-key shape is real from day one, but nothing actually provisions a Fly.io
-- Sprite yet — that's the Workspace Service, Phase 2. See /docs/PHASE1_NOTES.md.

create table projects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    github_repo text,                                             -- nullable — "owner/repo"; null until first Push or an Import
    github_default_branch text,
    github_credential_id uuid references github_credentials(id),  -- nullable — sync-only, see §8
    llm_credential_id uuid references llm_credentials(id),        -- null = use account default
    test_command text,
    deploy_targets jsonb not null default '[]'::jsonb,             -- [{name, root, build_cmd, run_cmd, port}] — Phase 2/5
    preview_subdomain text,                                        -- stable per-project subdomain — Phase 2/5
    max_turn_iterations integer not null default 50,
    created_at timestamptz not null default now()
);
alter table projects enable row level security;
create policy projects_owner_all on projects
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());


-- Defends against a credential landing on the wrong project's user.
create or replace function check_github_credential_owner()
returns trigger as $$
begin
    if new.github_credential_id is not null and not exists (
        select 1 from github_credentials
        where id = new.github_credential_id and user_id = new.user_id
    ) then
        raise exception 'github_credential_id must reference a credential owned by this project''s user';
    end if;
    return new;
end;
$$ language plpgsql;
create trigger projects_credential_owner_check
    before insert or update on projects
    for each row execute function check_github_credential_owner();

-- Same check for the LLM credential selection — not in the original spec excerpt's
-- trigger, but the same reasoning applies and the spec's projects_owner_all RLS
-- policy alone doesn't stop a cross-account llm_credential_id being written by a
-- backend bug, only by a PostgREST-level request. Structural belt-and-suspenders,
-- consistent with §5's "defense in depth" principle.
create or replace function check_llm_credential_owner()
returns trigger as $$
begin
    if new.llm_credential_id is not null and not exists (
        select 1 from llm_credentials
        where id = new.llm_credential_id and user_id = new.user_id
    ) then
        raise exception 'llm_credential_id must reference a credential owned by this project''s user';
    end if;
    return new;
end;
$$ language plpgsql;
create trigger projects_llm_credential_owner_check
    before insert or update on projects
    for each row execute function check_llm_credential_owner();


-- One persistent Sprite-backed workspace per project (§23.3, Phase 2). Looked up by
-- project id at the Sprite provider — never a filesystem path stored anywhere here.
create table project_workspaces (
    project_id uuid primary key references projects(id) on delete cascade,
    sprite_handle text not null,              -- opaque provider handle, never a filesystem path
    billing_state text not null default 'cold' check (billing_state in ('running','warm','cold')),
    last_active_at timestamptz,
    created_at timestamptz not null default now()
);
alter table project_workspaces enable row level security;
create policy project_workspaces_owner_all on project_workspaces
    for all using (exists (select 1 from projects p where p.id = project_workspaces.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_workspaces.project_id and p.user_id = auth.uid()));


create table project_mcp_access (
    project_id uuid not null references projects(id) on delete cascade,
    mcp_server_id uuid not null references mcp_servers(id) on delete cascade,
    granted_at timestamptz not null default now(),
    primary key (project_id, mcp_server_id)
);
alter table project_mcp_access enable row level security;
create policy project_mcp_access_owner_all on project_mcp_access
    for all using (exists (select 1 from projects p where p.id = project_mcp_access.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_mcp_access.project_id and p.user_id = auth.uid()));
