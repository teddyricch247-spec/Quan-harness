# AGENTS.md — must read before touching deploy/infra

This file exists so any AI agent (or human) picking this repo back up has the
current, real state of the deployment — not the state described in older
docs. If something here conflicts with docs/DEPLOYMENT.md or
docs/YOUR_SETUP_CHECKLIST.md, this file wins; update those docs to match
reality when you get a chance, don't trust them blindly.

## Live infra (as of 2026-09-21)

- **Frontend:** Vercel project `quan-harness` → `frontend/` — https://quan-harness-teddyricch247-specs-projects.vercel.app
- **Backend:** Render web service `Quan-harness` (Python) → `backend/` — https://quan-harness.onrender.com
- **Database/Auth:** Supabase project `quan-harness` (`skyykzpamsvfjnnbcgjn.supabase.co`, eu-west-1). **No migrations have been applied yet** — this is an empty project, `db/migrations/*.sql` have not been run. Do not assume any tables exist.
- The previous Render service, Vercel env vars, and Supabase project (an older, schema-incompatible "harness" project) were all deleted and recreated from scratch on 2026-09-20/21. Don't trust anything in chat history or docs dated before that as still being live.

## Most recent change: `backend/requirements.txt` httpx pin (2026-09-21)

**What changed:** `httpx==0.28.1` → `httpx==0.27.2`.

**Why:** `supabase==2.10.0` requires `httpx<0.28,>=0.26`. The `0.28.1` pin made `pip install -r requirements.txt` fail on Render with `ERROR: ResolutionImpossible` — the build couldn't get past dependency resolution at all, so nothing else in the file was ever the problem. This had apparently never been verified against a real install (there's a comment further down the file, next to the `litellm` pin, admitting versions were pinned without network access to check them).

**If you're an agent about to bump `httpx`, `supabase`, or any of their transitive deps again:** re-run `pip install -r requirements.txt` somewhere with real network access first, or you'll reintroduce this exact failure mode silently.

## Known gaps, intentionally left open

- `SUPABASE_SERVICE_ROLE_KEY` is set on Render with a real value; `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET` and `FLY_API_TOKEN`/`FLY_ORG_SLUG` are still blank — by design, not an oversight. GitHub OAuth App creation and Fly.io org setup are pending on the human side. The app works without them; only the "Connect GitHub" one-click flow and the sandboxed preview/deploy workspace feature are unavailable until they're filled in.
- GitHub credential strategy is OAuth App (not MCP) — this was explicitly decided after initially considering MCP-based push/pull for users: MCP tools are single-file, non-atomic, and would put git-write credentials inside the same tool surface the coding agent uses, which conflicts with this project's own architecture decision that the agent must never hold push/pull credentials.
