-- Coding Harness — schema
-- Run this once in the Supabase SQL editor (Project → SQL Editor → New query).
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
  -- Reasoning effort for DeepSeek V4 Flash's Responses API. These are the three
  -- effort levels DeepSeek actually documents for that API (see README for why
  -- there's no separate "medium"). Stored per-session so it's a durable per-thread
  -- setting, and sent as `reasoning.effort` on every responses.create call for the
  -- turn (main agent + verifier).
  reasoning_effort text not null default 'high' check (reasoning_effort in ('low','high','max')),
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
