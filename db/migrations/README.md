# Running these migrations

**Status as of 2026-09-24:** all eight of these, `0001` through
`0008_connector_oauth_client.sql`, are already applied to the live
`quan-harness` Supabase project — `0008` was applied directly via the
Supabase MCP connector rather than left for a human to run, and verified
against `information_schema.columns` afterward. If you're working against
that same project, there's nothing to run. The steps below are for anyone
setting up a *new* Supabase project from scratch (a fresh dev/staging
environment, or recovering from a deleted project — see `AGENTS.md`'s own
history of exactly that happening once already).

Run the files in this folder **in numeric order**, against your Supabase project's
Postgres database. Two ways to do it — pick whichever you're comfortable with:

**Option A — Supabase dashboard SQL Editor (easiest, no local tooling)**
1. Open your project in the Supabase dashboard → SQL Editor.
2. Paste the contents of `0001_extensions.sql`, run it.
3. Repeat for `0002_connections.sql`, `0003_vault_helpers.sql`, `0004_projects.sql`,
   `0005_sessions.sql`, `0006_workspace_tools.sql`, `0007_memory_and_project_knowledge.sql`,
   `0008_connector_oauth_client.sql`, in that order.

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

## Verifying it worked
After running all eight, `select table_name from information_schema.tables where
table_schema = 'public' order by 1;` should list: `approval_requests`,
`build_user_memory`, `checkpoints`, `github_credentials`, `llm_credentials`,
`mcp_servers`, `mcp_tool_overrides`, `project_knowledge`, `project_mcp_access`,
`project_memory`, `project_memory_log`, `project_secrets`, `project_workspaces`,
`projects`, `session_events`, `sessions`, `audit_log`. `select column_name from
information_schema.columns where table_name = 'mcp_servers';` should additionally
list `oauth_client_id` and `oauth_client_secret_ref`.

See `/docs/YOUR_SETUP_CHECKLIST.md` for the rest of the Supabase setup (Vault,
service role key, JWT secret, RLS live-test).
