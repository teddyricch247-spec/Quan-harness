# Running these migrations

**Status as of 2026-09-29:** `0001` through `0010_deploy_pipeline.sql` are all
applied to the live `quan-harness` Supabase project. `0008`/`0009` were applied
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
   in that order.

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
After running all ten, `select table_name from information_schema.tables where
table_schema = 'public' order by 1;` should list: `approval_requests`,
`build_user_memory`, `checkpoints`, `deploy_runs`, `github_credentials`, `llm_credentials`,
`mcp_servers`, `mcp_tool_overrides`, `project_knowledge`, `project_mcp_access`,
`project_memory`, `project_memory_log`, `project_schedules`, `project_secrets`,
`project_workspaces`, `projects`, `session_events`, `sessions`, `audit_log`.
`select column_name from information_schema.columns where table_name =
'mcp_servers';` should additionally list `oauth_client_id` and
`oauth_client_secret_ref`. `select column_name from information_schema.columns
where table_name = 'sessions';` should additionally list `trigger` and
`schedule_id`. `select column_name from information_schema.columns where
table_name = 'projects';` should additionally list `repo_origin` and
`deploy_targets_confirmed`.

See `/docs/YOUR_SETUP_CHECKLIST.md` for the rest of the Supabase setup (Vault,
service role key, JWT secret, RLS live-test).
