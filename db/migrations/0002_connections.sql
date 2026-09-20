-- 0002_connections.sql
-- Quan Harness — Phase 1 — §6-§10.1 of the spec: Connections.
-- Every credential is registered once at the account level. Projects only ever
-- select from what's here — see 0004_projects.sql for the selection columns.

create table llm_credentials (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    label text not null,
    provider text not null check (provider in ('anthropic','openai','google','openrouter','custom')),
    model text not null,
    api_key_ref text not null,         -- Vault reference; the raw key is never stored here
    base_url text,                     -- required when provider = 'custom'
    extra_headers jsonb not null default '{}'::jsonb,
    is_default boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create unique index llm_credentials_one_default_per_user
    on llm_credentials(user_id) where is_default;
alter table llm_credentials enable row level security;
create policy llm_credentials_owner_all on llm_credentials
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());


-- The sync-only GitHub credential (§8). Never selected by, or reachable from, the agent.
-- is_default exists for a later phase's GitHub export, which has no project to scope a
-- selection by — Build's own Push/Pull still resolve per-project via
-- projects.github_credential_id regardless of which row is flagged default; this column
-- only matters where nothing else picks one.
create table github_credentials (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    credential_type text not null default 'pat' check (credential_type in ('pat','github_app')),
    label text not null,
    token_ref text,                         -- Vault ref; required when credential_type = 'pat'
    github_app_installation_id text,        -- required when credential_type = 'github_app'
    github_app_account_login text,          -- display only
    is_default boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint github_credential_shape check (
        (credential_type = 'pat' and token_ref is not null and github_app_installation_id is null)
        or
        (credential_type = 'github_app' and github_app_installation_id is not null and token_ref is null)
    )
);
create unique index github_credentials_one_default_per_user
    on github_credentials(user_id) where is_default;
alter table github_credentials enable row level security;
create policy github_credentials_owner_all on github_credentials
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());


-- Every connector, GitHub included when a person adds it for agent access (§9).
create table mcp_servers (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    url text not null,                    -- remote MCP endpoint; HTTP/SSE transport only
    auth_mode text not null default 'none' check (auth_mode in ('none','static_token','oauth')),
    auth_token_ref text,
    oauth_session_ref text,
    enabled boolean not null default true,
    default_permission_state text not null default 'ask' check (default_permission_state in ('on','off','ask')),
    discovered_tools jsonb not null default '[]'::jsonb,
    last_handshake_at timestamptz,
    last_handshake_error text,
    created_at timestamptz not null default now(),
    unique (user_id, name)
);
alter table mcp_servers enable row level security;
create policy mcp_servers_owner_all on mcp_servers
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());


create table mcp_tool_overrides (
    id uuid primary key default gen_random_uuid(),
    mcp_server_id uuid not null references mcp_servers(id) on delete cascade,
    tool_name text not null,
    permission_state text check (permission_state in ('on','off','ask')),   -- null = inherit default_permission_state
    unique (mcp_server_id, tool_name)
);
alter table mcp_tool_overrides enable row level security;
create policy mcp_tool_overrides_owner_all on mcp_tool_overrides
    for all using (exists (select 1 from mcp_servers s where s.id = mcp_tool_overrides.mcp_server_id and s.user_id = auth.uid()))
    with check (exists (select 1 from mcp_servers s where s.id = mcp_tool_overrides.mcp_server_id and s.user_id = auth.uid()));
