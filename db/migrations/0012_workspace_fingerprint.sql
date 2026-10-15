-- 0012_workspace_fingerprint.sql  (Phase 5.8, §14.9)
--
-- Recorded here after the fact. This migration was applied to the live database on 2026-10-03
-- (migration name `0012_workspace_fingerprint`) from the Phase 5.8 working copy, and its .sql file never reached
-- this repository. The statement below is reconstructed from the live column's definition (type, nullability and
-- comment were read back from the database), so applying it to a database that already has the column is a no-op.
--
-- The agent's browser (§14.9) must only look at a preview that matches the code on disk. Each successful deploy
-- records a hash of the workspace content; preview_status compares it with the current content to say "the preview
-- is stale". Nothing in this codebase reads the column yet — it ships with the Phase 5.8 code.

alter table public.deploy_runs
  add column if not exists workspace_fingerprint text;

comment on column public.deploy_runs.workspace_fingerprint is
  'Git tree hash of the workspace content (build output / dependency dirs excluded) when this deploy succeeded. Null = unknown (pre-0012 run, or not computable). Compared by preview_status (§14.9); never exposed through any API.';
