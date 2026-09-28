# AGENTS.md — must read before touching deploy/infra

This file exists so any AI agent (or human) picking this repo back up has the
current, real state of the deployment — not the state described in older
docs. If something here conflicts with docs/DEPLOYMENT.md or
docs/YOUR_SETUP_CHECKLIST.md, this file wins; update those docs to match
reality when you get a chance, don't trust them blindly.

## Live infra (as of 2026-09-25)

- **Frontend:** Vercel project `quan-harness` → `frontend/` — https://quan-harness-teddyricch247-specs-projects.vercel.app
- **Backend:** Render web service `Quan-harness` (Python) → `backend/` — https://quan-harness.onrender.com
- **Database/Auth:** Supabase project `quan-harness` (`skyykzpamsvfjnnbcgjn.supabase.co`, eu-west-1). Migrations `0001` through `0009_scheduling.sql` are all applied as of 2026-09-27 — confirmed against `information_schema.columns`/`pg_policies`, not assumed. `0009` (Phase 4.5) was dry-run first (the full DDL plus explicit positive/negative tests of both new CHECK constraints, the `sessions.trigger` default, and `schedule_id`'s `ON DELETE SET NULL` behavior, all inside a transaction that was rolled back) before being applied for real via the Supabase MCP connector.
- The previous Render service, Vercel env vars, and Supabase project (an older, schema-incompatible "harness" project) were all deleted and recreated from scratch on 2026-09-20/21. Don't trust anything in chat history or docs dated before that as still being live.

## Most recent change: Phase 4.5 Scheduling / Proactive Scanning (2026-09-25)

**What changed:** see `docs/PHASE4_5_NOTES.md` for the full writeup. The
headline items:

1. New migration `0009_scheduling.sql` — a `project_schedules` table, plus
   `trigger`/`schedule_id` columns on `sessions`. Dry-run verified, then
   applied to the live Supabase project on 2026-09-27 (see the Live infra
   note above).
2. A new in-process background loop (`app/services/scheduler.py`, started
   from `main.py`'s new lifespan handler) that starts a real session for any
   due `project_schedules` row, through the exact same `agent_loop.start_turn`
   an interactive message goes through. No separate Render Cron Job or
   worker service — there isn't a second service to point one at (this is
   still one Render web service) — so a schedule can't fire while this
   single free-tier instance is asleep. See `docs/PHASE4_5_NOTES.md`'s rough
   edges section for what that actually means and how to fix it if it
   matters.
3. `agent_loop.py`'s permission resolution (`_resolve_permission_for_call`)
   gained a `force_ask` path: on a session whose `trigger == 'scheduled'`,
   every mutating tool call — native tools included, which normally have no
   Ask concept at all — is gated behind an approval request, regardless of
   the project's configured Auto/Ask/Off states. `_action_resolved_approval`
   correspondingly gained a `scheduled_tool:` branch, including a genuinely
   new shape: an approved scheduled `execute_bash` call can itself still
   trip the heuristic guard on execution, producing a second, nested
   approval. Read `docs/PHASE4_5_NOTES.md`'s "Nested approvals" section
   before touching either function again.

**If you're an agent about to touch `agent_loop.py`'s mutating-call branch,
`_action_resolved_approval`, or `scheduler.py` again:** read
`docs/PHASE4_5_NOTES.md` first, specifically the "Nested approvals" and
"single-process only" notes — both are easy to silently break by
"simplifying" the code back toward what it looked like before this pass.

## Previous change: Phase 4.3/4.4 connector + import-mode fixes (2026-09-24)

**What changed:** see `docs/PHASE4_3_4_4_NOTES.md` for the full writeup. Two
headline items if you only read one paragraph:

1. `mcp_servers` gained `oauth_client_id`/`oauth_client_secret_ref`
   (`0008_connector_oauth_client.sql`, applied directly to the live Supabase
   project on 2026-09-24 — confirmed via `information_schema.columns`, not
   just "should have run") — a connector's OAuth flow can now use
   a pre-registered client instead of always attempting dynamic client
   registration (DCR). This matters because **GitHub's own remote MCP server
   does not support DCR** (confirmed via two independent, current GitHub
   issue reports — see `mcp_oauth.py`'s module docstring) — before this
   change, there was no way to connect it via real OAuth at all, only a
   personal access token in static_token mode (still the simpler, reliable
   default — see the Connectors page's "Quick connect: GitHub" button).
2. `routers/projects.py`'s `create_project` no longer hardcodes
   `github_default_branch = "main"` for 'import' mode, and now pulls the
   repository's real content into the workspace immediately at creation time
   instead of leaving it silently empty until the person happens to click
   Pull themselves. See `docs/PHASE4_3_4_4_NOTES.md` for why this was a real
   bug, not a nice-to-have.

## Known gaps, intentionally left open

- `SUPABASE_SERVICE_ROLE_KEY` is set on Render with a real value; `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET` and `FLY_API_TOKEN`/`FLY_ORG_SLUG` are still blank — by design, not an oversight. GitHub OAuth App creation and Fly.io org setup are pending on the human side. The app works without them; only the "Connect GitHub" one-click flow and the sandboxed preview/deploy workspace feature are unavailable until they're filled in. A blank `FLY_API_TOKEN` specifically means a freshly-imported project's automatic first Pull (Phase 4.4) will fail with a workspace-provisioning error — expected, not a regression; the project itself is still created correctly, and re-running Pull once Fly/Sprites credentials exist picks up where it left off.
- GitHub credential strategy is OAuth App (not MCP) for the Push/Pull sync mechanism specifically (`github_credentials`, `github_oauth.py`) — this was explicitly decided after initially considering MCP-based push/pull for users: MCP tools are single-file, non-atomic, and would put git-write credentials inside the same tool surface the coding agent uses, which conflicts with this project's own architecture decision that the agent must never hold push/pull credentials. This is a *separate* thing from GitHub-as-a-connector (`mcp_servers`, GitHub's own real remote MCP server at `api.githubcopilot.com/mcp`, wired up like any other connector via `routers/connectors.py`) — that path is read/action-oriented agent tool access (list issues, check PR status, and so on), gated per-tool by the usual On/Off/Ask permissioning, and was never a candidate for holding push/pull credentials in the first place. Phase 4.3 is what made connecting it via real OAuth actually possible; see the Phase 4.3/4.4 entry above.
