-- 0011_preview.sql
-- Quan Harness — Phase 5.3 (§23.7, Live Preview compute) and 5.4 (§23.8, known
-- preview limitations). Additive only: nothing here rewrites or drops an
-- existing object, and every new column is nullable or defaulted.
--
-- What this adds, and why each piece has to be structural rather than a
-- convention in Python:
--
--   1. projects.preview_subdomain — column already existed (0004) but nothing
--      ever wrote it. §23.8's CORS mitigation is "a stable preview subdomain per
--      project so the client can allowlist it once." That promise is only true
--      if the value can never change after it's first assigned, so it's
--      enforced by a trigger, not left to application code to remember. Also
--      unique (two projects can never share an origin) and format-checked (it
--      becomes a DNS label).
--
--   2. preview_secrets — the Secrets panel (§23.8 / §11.3 / §13). Deliberately
--      NOT the existing project_secrets table (0006): that one is the
--      *agent-usable* secret store — its names go into the agent's system
--      prompt and its values are exported into execute_bash (§14.3). §23.8/§23.10
--      require the opposite for preview secrets: "injected into the Sprite's
--      runtime env only. Never in the LLM's context, and the agent cannot read
--      or use these values." Two opposite visibility contracts can't share one
--      table without a filter that every future reader has to remember; a
--      separate table means no existing code path can reach these rows at all.
--      Values live in Vault, same as every other credential (§13).
--
--   3. project_notifications — §23.8's "notification system" (§23.9 point 4
--      routes environment-class deploy failures here). One row per known
--      limitation kind per project while open; notify-only — nothing in this
--      table's lifecycle triggers an action.
--
--   4. deploy_runs.environment_kind — which §23.8 limitation an
--      environment-class failure looks like, so the Deploy panel and the
--      notification it raised agree.

-- ---------------------------------------------------------------------------
-- 1. Stable preview subdomain
-- ---------------------------------------------------------------------------

-- Backfill first (unique index / constraint below need every row valid).
-- 'p-' + 12 hex chars: lowercase alphanumerics and one hyphen — a valid DNS label.
update projects
set preview_subdomain = 'p-' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 12)
where preview_subdomain is null;

alter table projects
    add constraint projects_preview_subdomain_format
    check (preview_subdomain is null or preview_subdomain ~ '^[a-z0-9]([a-z0-9-]{0,40}[a-z0-9])?$');

create unique index projects_preview_subdomain_key
    on projects (preview_subdomain)
    where preview_subdomain is not null;

-- Once set, never changed: this is what makes "allowlist it once" true.
create or replace function projects_preview_subdomain_immutable()
returns trigger as $$
begin
    if old.preview_subdomain is not null and new.preview_subdomain is distinct from old.preview_subdomain then
        raise exception 'projects.preview_subdomain is stable once assigned and cannot be changed';
    end if;
    return new;
end;
$$ language plpgsql;
create trigger projects_preview_subdomain_immutable_check
    before update on projects
    for each row execute function projects_preview_subdomain_immutable();


-- ---------------------------------------------------------------------------
-- 2. preview_secrets — preview-only, never visible to the agent
-- ---------------------------------------------------------------------------

create table preview_secrets (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    name text not null check (name ~ '^[A-Za-z_][A-Za-z0-9_]{0,127}$'),  -- an environment variable name
    secret_ref uuid not null,                                            -- Vault id; the raw value is never stored here
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, name)                                            -- "one set": a name has exactly one value
);
alter table preview_secrets enable row level security;
create policy preview_secrets_owner_all on preview_secrets
    for all using (exists (select 1 from projects p where p.id = preview_secrets.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = preview_secrets.project_id and p.user_id = auth.uid()));


-- ---------------------------------------------------------------------------
-- 3. project_notifications — §23.8's notification system
-- ---------------------------------------------------------------------------

create table project_notifications (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    kind text not null check (kind in ('cors', 'secrets', 'oauth', 'database', 'nested_container', 'other')),
    status text not null default 'open' check (status in ('open', 'dismissed', 'resolved')),
    source text not null check (source in ('deploy_failure', 'env_scan', 'manual')),
    title text not null,
    body text not null,
    -- Change detector: a dismissed notification only re-opens when this differs
    -- (e.g. a different set of missing variable names), so a person who
    -- dismissed something isn't nagged about the identical thing on every deploy.
    detail_key text,
    detail jsonb not null default '{}'::jsonb,
    deploy_run_id uuid references deploy_runs(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    dismissed_at timestamptz,
    resolved_at timestamptz
);
-- At most one *open* notification per kind per project (upsert target).
create unique index project_notifications_one_open_per_kind
    on project_notifications (project_id, kind)
    where status = 'open';
create index project_notifications_project_created_idx
    on project_notifications (project_id, created_at desc);
alter table project_notifications enable row level security;
create policy project_notifications_owner_all on project_notifications
    for all using (exists (select 1 from projects p where p.id = project_notifications.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = project_notifications.project_id and p.user_id = auth.uid()));


-- ---------------------------------------------------------------------------
-- 4. deploy_runs.environment_kind
-- ---------------------------------------------------------------------------

alter table deploy_runs
    add column environment_kind text
    check (environment_kind is null or environment_kind in ('cors', 'secrets', 'oauth', 'database', 'nested_container', 'other'));
