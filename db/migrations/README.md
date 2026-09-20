# Running these migrations

Run the files in this folder **in numeric order**, against your Supabase project's
Postgres database. Two ways to do it — pick whichever you're comfortable with:

**Option A — Supabase dashboard SQL Editor (easiest, no local tooling)**
1. Open your project in the Supabase dashboard → SQL Editor.
2. Paste the contents of `0001_extensions.sql`, run it.
3. Repeat for `0002_connections.sql`, `0003_vault_helpers.sql`, `0004_projects.sql`,
   `0005_sessions.sql`, `0006_workspace_tools.sql`, in that order.

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

## Verifying it worked
After running all six, `select table_name from information_schema.tables where
table_schema = 'public' order by 1;` should list: `approval_requests`,
`checkpoints`, `github_credentials`, `llm_credentials`, `mcp_servers`,
`mcp_tool_overrides`, `project_mcp_access`, `project_secrets`, `project_workspaces`,
`projects`, `session_events`, `sessions`, `audit_log`.

See `/docs/YOUR_SETUP_CHECKLIST.md` for the rest of the Supabase setup (Vault,
service role key, JWT secret, RLS live-test).
