-- Coding Harness — schema
-- Run this once in the Supabase SQL editor (Project → SQL Editor → New query) for a
-- brand-new project. If you already applied the original version of this file, run
-- sql/002_providers_and_prompt_maker.sql instead (or first) — it takes an existing
-- installation to this same final state without touching your data.
--
-- RLS is intentionally left disabled on all three tables: the backend talks to
-- Postgres with the service-role key (bypasses RLS) and the browser never queries
-- these tables directly. Only add RLS if you later add direct browser→Supabase reads.

create extension if not exists pgcrypto;

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  github_repo text not null default '',   -- "owner/repo", empty until created
  github_default_branch text not null default 'main',
  vercel_project_id text,                 -- null until linked
  stack text check (stack in ('static','vite','nextjs')),
  memory text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  title text not null default 'New session',

  -- 'interview' = prompt-maker agent (interviews the user, then hands a generated
  -- prompt to a brand-new 'build' session it creates). 'build' = the main coding
  -- agent that reads/writes the repo directly. New sessions default to 'build' at
  -- the DB layer as a safety net for direct inserts — the actual UX default
  -- (prompt-maker) is applied by the API layer in routes/projects.js.
  kind text not null default 'build' check (kind in ('interview','build')),

  -- For a 'build' session spawned by a prompt-maker handoff, points back at the
  -- interview session that generated it. Null for everything else.
  origin_session_id uuid references sessions(id) on delete set null,

  -- Which entry in backend/src/config.js's `providers` registry this session calls.
  -- Not a DB-level enum on purpose: providers are configured via env vars, so the set
  -- of valid ids can change without a migration. Validated at the app layer instead.
  provider text not null default 'deepseek',

  -- Reasoning effort for whichever provider this session uses. Nullable and
  -- unconstrained at the DB layer (a provider may define its own set of valid
  -- levels, or none at all) — validated against that provider's registered
  -- `reasoningEfforts` in routes/sessions.js on every read and write.
  reasoning_effort text,

  -- Set once an 'interview' session's finalize_prompt tool call has fired. Locks the
  -- session against further messages (routes/sessions.js) — its job is done, and its
  -- history was never meant to be replayed into another turn anyway (see
  -- backend/src/agent/messageStore.js).
  completed_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  role text not null check (role in ('user','assistant','tool')),
  content jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists messages_session_id_created_at_idx
  on messages (session_id, created_at);

create index if not exists sessions_project_id_idx
  on sessions (project_id);

create index if not exists sessions_origin_session_id_idx
  on sessions (origin_session_id);
