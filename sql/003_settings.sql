-- Migration 003 — BYOK settings.
-- Adds two tables so model-provider credentials and any other API key the harness
-- needs (GitHub, Vercel, Tavily, ...) can be added, edited, and rotated from the
-- Settings page in the frontend, instead of being hardcoded into `backend/.env` and
-- requiring a redeploy every time a key changes. Run once against an existing
-- project; safe to run more than once — every statement is idempotent. If you're
-- setting up a brand-new project instead, sql/schema.sql already includes these
-- tables — you don't need this file too.
--
-- Values are stored AES-256-GCM encrypted (see backend/src/services/settingsStore.js)
-- under a key derived from the SETTINGS_ENCRYPTION_KEY env var — that's the one
-- secret still required in the environment; everything else lives here now.
--
-- RLS is intentionally left disabled, same reasoning as sql/schema.sql: the backend
-- talks to Postgres with the service-role key and the browser never queries these
-- tables directly.

create table if not exists providers (
  id text primary key,                       -- slug stored in sessions.provider, e.g. 'deepseek', 'openai'
  label text not null,
  base_url text not null,
  api_key_encrypted text not null,
  model text not null,
  reasoning_efforts text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists secrets (
  key text primary key,                      -- e.g. 'github_token', 'vercel_token', 'vercel_team_id', 'tavily_api_key'
  label text not null,
  value_encrypted text not null,
  updated_at timestamptz not null default now()
);
