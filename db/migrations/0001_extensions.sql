-- 0001_extensions.sql
-- Quan Harness — Phase 1
--
-- Run this against your Supabase project's Postgres database (SQL Editor, or
-- `supabase db push` / psql against the connection string — see /docs/YOUR_SETUP_CHECKLIST.md).
--
-- gen_random_uuid() is provided by pgcrypto, which Supabase enables by default on new
-- projects. This statement is a no-op if it's already on; it's here so this migration
-- set doesn't silently depend on an assumption about your project's defaults.
create extension if not exists pgcrypto;

-- Supabase Vault (used for every credential/secret in this system — §13 of the spec)
-- ships enabled by default on Supabase projects. This is a note, not a statement:
-- there is nothing to run here. If `select * from vault.secrets limit 1;` errors with
-- "schema vault does not exist" in your project, enable the Vault extension from
-- Database → Extensions in the Supabase dashboard before running 0003_vault_helpers.sql.

-- auth.users is Supabase Auth's own table and already exists — there is no separate
-- `users`/`profiles` table in this schema (§10 of the spec). Every table below references
-- auth.users(id) directly.
