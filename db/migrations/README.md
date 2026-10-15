# Running these migrations

**Status as of 2026-10-13:** this folder holds `0001` through `0017` and matches the live `quan-harness`
Supabase project's migration history, entry for entry (the database records most of them by NAME, not by number — see
the table below). Before 2026-10-13 it did not: `0012`–`0015` had been applied to the live project from a separate
working copy and their files never reached this repository, while two other migrations had been written here under
numbers that clashed. `docs/RECONCILIATION_NOTES.md` has the story; the numbering that resulted is:

| File | Live history name | Applied | What |
|---|---|---|---|
| `0012_workspace_fingerprint.sql` | `0012_workspace_fingerprint` | 2026-10-03 | Phase 5.8: `deploy_runs.workspace_fingerprint`. **File reconstructed** from the live column (type, nullability and comment read back) — idempotent. Written by `deploy_pipeline`, read by `preview_status`. |
| `0013_session_attachments.sql` | `session_attachments` | 2026-10-08 | Phase 6.1: pictures attached to messages. |
| `0014_rls_cross_reference_checks.sql` | `rls_cross_reference_checks` | 2026-10-08 | Phase 6.2: `WITH CHECK` tightening, `sprite_handle` unique index. |
| `0015_rls_audit.sql` | `rls_audit` (+ `phase6_advisor_fixes`, folded in) | 2026-10-08 | Phase 6.2: `public.rls_audit()`. |
| `0016_llm_provider_presets.sql` | `llm_provider_presets` | 2026-10-08 | BYOK presets: widens the provider CHECK. Written as `0012` before the renumbering. |
| `0017_llm_reasoning_config.sql` | `llm_reasoning_config` | 2026-10-09 | Per-credential thinking config. Written as `0013` before the renumbering. |

**Never re-run an applied migration just because its number changed:** the database tracks migrations by name, and
`0017` is guarded (`IF NOT EXISTS` / a guarded constraint), and `0016` drops and re-adds one CHECK constraint to the same strict
superset — harmless to re-run, but not guarded, so don't. A FRESH database built from these
files, in order, gets exactly the state the live project has.

**Phase 6 (2026-10-08) notes:** `0013`–`0015` were each dry-run first (see `docs/PHASE6_NOTES.md`), then applied through
the Supabase connector and verified. Live history also has a fourth entry, `phase6_advisor_fixes`: after applying,
Supabase's security advisor flagged the three attachment functions (no pinned `search_path`) and `rls_audit`
(needlessly SECURITY DEFINER); those two fixes were applied live as `ALTER FUNCTION`s and are already folded into the
`0013` and `0015` files, so a fresh database built from these files gets the final state directly.

**Earlier status (2026-10-08, presets):** `0001` through `0011` plus the presets migration were applied. The presets migration (now `0016`) only
widens `llm_credentials_provider_check` to a strict superset of the old list, so it touches
no rows and no policies; it was dry-run in a rolled-back transaction first (all 12 provider ids
accepted, 4 invalid values rejected — checked by distinguishing `check_violation` from the
FK error a fake `user_id` produces), the rollback was confirmed against the live constraint,
then it was applied via the Supabase MCP connector and the live constraint re-read.
Previous status: `0001` through `0011_preview.sql` were applied. `0011` (Phase 5.3/5.4) was
dry-run first — the full DDL plus 25 positive/negative assertions (the
subdomain immutability trigger, uniqueness and format checks, every CHECK
constraint, RLS isolation between two users, cascade delete) inside a
transaction that was rolled back, with the rollback itself confirmed — then
applied via the Supabase MCP connector and verified against the live schema. The
`projects` table had 0 rows, so its subdomain backfill touched nothing. The
recorded migration has the same statements as the file with the long header
comments trimmed. `0008`/`0009` were applied
via the Supabase MCP connector on 2026-09-24/27 (`0008` is recorded there under
the name `connector_oauth_client`). `0010` (Phase 5.1/5.2/5.5) was applied the
same way on 2026-09-29 and then verified against the live database, not just
assumed: `deploy_runs`'s columns/defaults, all four CHECK constraints, the
`projects_repo_origin_check` constraint, the FK's `ON DELETE CASCADE`, the
`(project_id, created_at desc)` index, RLS enabled with the one
`deploy_runs_owner_all` policy — plus a functional test run inside a
transaction that was rolled back (bad `status`/`failure_class`/`stack`/
`repo_origin` values rejected, valid ones accepted, a second user sees 0 rows
of another user's run while the owner sees 1, cascade delete works). The
`projects` table had 0 rows at the time, so the `'scratch'` default for
`repo_origin` backfilled nothing.

Run the files in this folder **in numeric order**, against your Supabase project's
Postgres database. Two ways to do it — pick whichever you're comfortable with:

**Option A — Supabase dashboard SQL Editor (easiest, no local tooling)**
1. Open your project in the Supabase dashboard → SQL Editor.
2. Paste the contents of `0001_extensions.sql`, run it.
3. Repeat for `0002_connections.sql`, `0003_vault_helpers.sql`, `0004_projects.sql`,
   `0005_sessions.sql`, `0006_workspace_tools.sql`, `0007_memory_and_project_knowledge.sql`,
   `0008_connector_oauth_client.sql`, `0009_scheduling.sql`, `0010_deploy_pipeline.sql`,
   `0011_preview.sql`, `0012_workspace_fingerprint.sql`, `0013_session_attachments.sql`,
   `0014_rls_cross_reference_checks.sql`, `0015_rls_audit.sql`, `0016_llm_provider_presets.sql`,
   `0017_llm_reasoning_config.sql`, in that order.

**Option B — Supabase CLI**
```bash
supabase link --project-ref <your-project-ref>
for f in db/migrations/0*.sql; do
  psql "$SUPABASE_DB_URL" -f "$f"
done
```
(`SUPABASE_DB_URL` is the connection string from Settings → Database → Connection
string → URI, in your Supabase dashboard.)

## Order matters here specifically because:
- `0002` creates `github_credentials` and `mcp_servers`, which `0004`'s `projects`
  table has foreign keys into.
- `0003` wraps Supabase Vault in `SECURITY DEFINER` functions the backend calls —
  it has to exist before the backend can store its first credential.
- `0004` creates `projects`, which `0005`'s `sessions`/`checkpoints`/`audit_log`
  reference.
- `0006` (Phase 2) adds `project_secrets` (references `projects`), plus columns
  on `projects` and `sessions` — needs both tables to already exist.
- `0007` (Phase 4.1/4.2) adds `project_memory`, `project_memory_log`,
  `build_user_memory`, and `project_knowledge` (all reference `projects` and/or
  `sessions`, so both need to already exist), plus a CHECK-constraint change on
  `session_events.event_type` — needs `0005` to already exist.
- `0008` (Phase 4.3) adds two nullable columns to `0002`'s `mcp_servers` table —
  needs `0002` to already exist, nothing else depends on it.
- `0009` (Phase 4.5) creates `project_schedules` (references `projects`), and adds
  `trigger`/`schedule_id` columns to `0005`'s `sessions` table (the second of
  those two references `project_schedules`, created earlier in this same file)
  — needs `0004` and `0005` to already exist.
- `0010` (Phase 5.1/5.2/5.5) creates `deploy_runs` (references `projects`) and
  adds `repo_origin`/`deploy_targets_confirmed` columns to `0004`'s `projects`
  table — needs `0004` to already exist, nothing else depends on it.

## Verifying it worked
After running all seventeen, `select table_name from information_schema.tables where
table_schema = 'public' order by 1;` should list: `approval_requests`,
`build_user_memory`, `checkpoints`, `deploy_runs`, `github_credentials`, `llm_credentials`,
`mcp_servers`, `mcp_tool_overrides`, `project_knowledge`, `project_mcp_access`,
`project_memory`, `project_memory_log`, `project_schedules`, `project_secrets`,
`project_workspaces`, `projects`, `session_attachments`, `session_events`, `sessions`, `audit_log`, `preview_secrets`,
`project_notifications`.
`select column_name from information_schema.columns where table_name =
'mcp_servers';` should additionally list `oauth_client_id` and
`oauth_client_secret_ref`. `select column_name from information_schema.columns
where table_name = 'sessions';` should additionally list `trigger` and
`schedule_id`. `select column_name from information_schema.columns where
table_name = 'projects';` should additionally list `repo_origin` and
`deploy_targets_confirmed`.

See `/docs/YOUR_SETUP_CHECKLIST.md` for the rest of the Supabase setup (Vault,
service role key, JWT secret, RLS live-test).
- `0011` (Phase 5.3/5.4) adds `preview_secrets` and `project_notifications`
  (both reference `projects`; the latter also references `0010`'s `deploy_runs`),
  an immutable-once-set unique `projects.preview_subdomain`, and
  `deploy_runs.environment_kind` — needs `0004` and `0010` to already exist,
  nothing else depends on it. It **backfills** a subdomain for existing projects
  before adding the format constraint, so run it before any code that assumes every
  project has one.
- `0012` (Phase 5.8) adds `deploy_runs.workspace_fingerprint` (nullable `text`) — needs `0010`. Purely additive. `NULL`
  means "unknown" (an older run, or the hash couldn't be computed). A successful deploy writes it
  (`deploy_pipeline` → `workspace_fingerprint.compute`); `preview_status` compares it with the workspace now.
- `0013` (Phase 6.1, image input) adds `session_attachments` (the pictures a person attaches to a message — pixels
  live here, never in `session_events`) and three service-role-only functions that move a picture between message
  states. Needs `0005` (sessions). Purely additive: an older backend never touches it, so apply it before
  deploying the new code. Roll back with `drop table session_attachments;` (the functions go with `drop function`).
- `0014` (Phase 6.2, isolation) tightens eight owner policies' `WITH CHECK` so a row can no longer POINT AT another
  account's row (connector grants, checkpoints, memory-log, audit-log, scheduled sessions, notifications, event
  parents), adds a unique index on `project_workspaces.sprite_handle`, and creates two tiny helper functions in a
  new `private` schema. Needs `0013` only for ordering. What a user can SEE does not change (USING is untouched),
  and the backend uses the service role, so no application behaviour changes. Roll back by restoring each policy's
  previous `WITH CHECK` (the old text is in `docs/PHASE6_NOTES.md`) and dropping the index.
- `0015` (Phase 6.2) adds `public.rls_audit()`: metadata only (table names, policy text, foreign keys, who can
  execute which function) for the isolation suite's catalog guards. Executable by signed-in callers only. Roll back
  with `drop function public.rls_audit();`.
- `0016` widens `llm_credentials_provider_check`; the list MUST match `provider_catalog.py` and `schemas.LlmProvider`
  (`tests/test_provider_catalog.py` fails on drift).
- `0017` adds `llm_credentials.reasoning` (jsonb, default `{}`). Purely additive.
