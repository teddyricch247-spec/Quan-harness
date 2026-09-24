# AGENTS.md — must read before touching deploy/infra

This file exists so any AI agent (or human) picking this repo back up has the
current, real state of the deployment — not the state described in older
docs. If something here conflicts with docs/DEPLOYMENT.md or
docs/YOUR_SETUP_CHECKLIST.md, this file wins; update those docs to match
reality when you get a chance, don't trust them blindly.

## Live infra (as of 2026-09-21)

- **Frontend:** Vercel project `quan-harness` → `frontend/` — https://quan-harness-teddyricch247-specs-projects.vercel.app
- **Backend:** Render web service `Quan-harness` (Python) → `backend/` — https://quan-harness.onrender.com
- **Database/Auth:** Supabase project `quan-harness` (`skyykzpamsvfjnnbcgjn.supabase.co`, eu-west-1). All eight migrations are applied as of 2026-09-24 (`0001` through `0008_connector_oauth_client.sql`, the last one applied directly via the Supabase MCP connector while verifying this phase's work, not left for the human to run) — confirmed against the live schema, not assumed. The note that used to be here ("no migrations applied yet, empty project") was accurate on 2026-09-21 but stale by the time this entry was written; check `information_schema.columns`/`list_tables` yourself rather than trusting either note if it's been a while.
- The previous Render service, Vercel env vars, and Supabase project (an older, schema-incompatible "harness" project) were all deleted and recreated from scratch on 2026-09-20/21. Don't trust anything in chat history or docs dated before that as still being live.

## Most recent change: Phase 4.3/4.4 connector + import-mode fixes (2026-09-24)

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

**If you're an agent about to touch `mcp_oauth.py`, `connectors.py`, or
`create_project` again:** read that notes file first — both fixes above were
found by actually tracing what happens for a real-world case (GitHub's MCP
server; an imported repo whose default branch isn't literally "main"), not
by re-reading the spec text alone, and it's easy to reintroduce either gap
by "simplifying" the code back toward what it looked like before.

## Previous change: `backend/requirements.txt` httpx pin (2026-09-21)

**What changed:** `httpx==0.28.1` → `httpx==0.27.2`.

**Why:** `supabase==2.10.0` requires `httpx<0.28,>=0.26`. The `0.28.1` pin made `pip install -r requirements.txt` fail on Render with `ERROR: ResolutionImpossible` — the build couldn't get past dependency resolution at all, so nothing else in the file was ever the problem. This had apparently never been verified against a real install (there's a comment further down the file, next to the `litellm` pin, admitting versions were pinned without network access to check them).

**If you're an agent about to bump `httpx`, `supabase`, or any of their transitive deps again:** re-run `pip install -r requirements.txt` somewhere with real network access first, or you'll reintroduce this exact failure mode silently.

## Known gaps, intentionally left open

- `SUPABASE_SERVICE_ROLE_KEY` is set on Render with a real value; `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET` and `FLY_API_TOKEN`/`FLY_ORG_SLUG` are still blank — by design, not an oversight. GitHub OAuth App creation and Fly.io org setup are pending on the human side. The app works without them; only the "Connect GitHub" one-click flow and the sandboxed preview/deploy workspace feature are unavailable until they're filled in. A blank `FLY_API_TOKEN` specifically means a freshly-imported project's automatic first Pull (Phase 4.4) will fail with a workspace-provisioning error — expected, not a regression; the project itself is still created correctly, and re-running Pull once Fly/Sprites credentials exist picks up where it left off.
- GitHub credential strategy is OAuth App (not MCP) for the Push/Pull sync mechanism specifically (`github_credentials`, `github_oauth.py`) — this was explicitly decided after initially considering MCP-based push/pull for users: MCP tools are single-file, non-atomic, and would put git-write credentials inside the same tool surface the coding agent uses, which conflicts with this project's own architecture decision that the agent must never hold push/pull credentials. This is a *separate* thing from GitHub-as-a-connector (`mcp_servers`, GitHub's own real remote MCP server at `api.githubcopilot.com/mcp`, wired up like any other connector via `routers/connectors.py`) — that path is read/action-oriented agent tool access (list issues, check PR status, and so on), gated per-tool by the usual On/Off/Ask permissioning, and was never a candidate for holding push/pull credentials in the first place. Phase 4.3 is what made connecting it via real OAuth actually possible; see the change entry above.
