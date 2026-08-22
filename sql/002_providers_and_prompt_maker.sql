-- Migration 002 — provider selection + prompt-maker (interview) sessions.
-- Run this once against a Supabase project that already has the ORIGINAL
-- sql/schema.sql applied. (This has already been applied to the live "harness"
-- project — this file is here for any other environment running from the same
-- starting point, e.g. a second deploy or a fresh clone that was set up before this
-- change.) Safe to run more than once — every statement is idempotent.
--
-- Brings a session table with only `reasoning_effort text not null default 'high'
-- check (in ('low','high','max'))` up to the same shape sql/schema.sql now describes
-- for a fresh install. No existing rows are touched or lost — every new column has a
-- safe default (kind → 'build', provider → 'deepseek', origin_session_id/completed_at
-- → null), so anything already in the table keeps behaving exactly as before.

alter table sessions
  add column if not exists kind text not null default 'build' check (kind in ('interview','build'));

alter table sessions
  add column if not exists origin_session_id uuid references sessions(id) on delete set null;

alter table sessions
  add column if not exists provider text not null default 'deepseek';

alter table sessions
  add column if not exists completed_at timestamptz;

-- reasoning_effort now varies per provider (a custom OpenAI-compatible provider might
-- support different levels, or none at all) instead of DeepSeek's fixed three, so the
-- old CHECK constraint and NOT NULL/DEFAULT no longer hold — validation moves to the
-- app layer (backend/src/config.js's `providers` registry, enforced in
-- backend/src/routes/sessions.js).
alter table sessions
  drop constraint if exists sessions_reasoning_effort_check;

alter table sessions
  alter column reasoning_effort drop not null;

alter table sessions
  alter column reasoning_effort drop default;

create index if not exists sessions_origin_session_id_idx on sessions (origin_session_id);
