# Your setup checklist

Everything in this repo runs once these boxes are checked. None of it can be done
by the code itself — each one requires you to click something on an external
site, or make a real-world decision. Roughly in the order you'll hit them.

## 1. Supabase project

- [ ] Create a project at [supabase.com](https://supabase.com) (pick a region —
      Supabase doesn't currently have an Africa region; closest to South Africa
      is usually `eu-west` or `eu-central`).
- [ ] **Settings → API** — copy the **Project URL**, the **anon / public key**,
      and the **service_role key** (click "reveal"). These go in both
      `backend/.env` and `frontend/.env.local`.
- [ ] **Settings → API → JWT Keys** — if your project shows a **JWT Secret**
      (legacy HS256 projects), copy it into `backend/.env`'s
      `SUPABASE_JWT_SECRET`. If your project instead shows "JWT Signing Keys"
      with no plain secret (newer asymmetric-key projects), leave that env var
      blank — the backend automatically falls back to fetching your project's
      JWKS endpoint.
- [ ] **Database → Extensions** — confirm `pgcrypto` and `supabase_vault` are
      both enabled (they're on by default on new projects; check anyway).
- [ ] Run the seven migration files in `db/migrations/` **in order** — see
      `db/migrations/README.md` for the exact steps (SQL Editor is the easiest
      path if you don't already use the Supabase CLI).
- [ ] **Authentication → Sign In / Providers** — confirm Email is enabled and
      "Confirm email" is turned on (it's the default). This is what makes §4's
      email-verification gate actually work.
- [ ] **Authentication → URL Configuration** — set **Site URL** to your
      frontend's URL (`http://localhost:3000` for now, your real domain once
      deployed) and add it to **Redirect URLs** too. This is what the
      confirmation-email and password-reset links point back to — without it,
      those links land on the wrong place or get rejected.
- [ ] **(Recommended) Two throwaway test accounts**, for the RLS live-test suite
      (§5 of the spec requires this be run, not just written). Sign up two real
      accounts through your own running frontend (or via the Supabase dashboard's
      Authentication → Users → "Add user"), confirm both emails, and set:
      `TEST_ACCOUNT_A_EMAIL`, `TEST_ACCOUNT_A_PASSWORD`, `TEST_ACCOUNT_B_EMAIL`,
      `TEST_ACCOUNT_B_PASSWORD` wherever you run `backend/tests/test_rls_isolation.py`
      (a local shell, or your CI's secrets). Don't reuse your own real account for
      this — the tests create and delete rows.

## 2. GitHub OAuth App

Needed for the "Connect GitHub" button (§8's sync credential). Skip this and the
app still works — the frontend's "Add a token manually" path always works — but
the one-click OAuth flow won't until this exists.

- [ ] Go to **github.com/settings/developers → OAuth Apps → New OAuth App**.
- [ ] Application name: anything (e.g. "Quan Harness — dev" and a separate one
      later for production — GitHub OAuth Apps are tied to one callback URL
      each, so most people end up with a dev app and a prod app).
- [ ] Homepage URL: your frontend URL.
- [ ] **Authorization callback URL:** `<your backend's public URL>/connections/github-credential/oauth-callback`
      — e.g. `http://localhost:8000/connections/github-credential/oauth-callback`
      for local dev, or `https://your-backend.onrender.com/connections/github-credential/oauth-callback`
      once deployed.
- [ ] Copy the **Client ID**, generate and copy a **Client Secret** — both go in
      `backend/.env` as `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`.
- [ ] For Push/Pull (§23.3) you'll also need at least one **GitHub credential
      connected** for the account you test with — either through this OAuth
      flow, or the "add a token manually" path with a PAT that has `repo`
      scope. Push creates a repository on that credential's behalf the first
      time it runs, so it needs write access, not just read.

## 3. Fly.io (Phase 2 — the Workspace Service, §23)

Every project's workspace is a real Fly.io Machine + persistent Volume,
created lazily the first time it's needed. **Use a dedicated Fly
organization for this, never your personal one** — every signed-up user's
projects will end up as Fly Apps inside whichever org you point this at, and
you don't want that mixed in with your own unrelated Fly usage or billing.

- [ ] Create a Fly.io account and a **new, dedicated organization** for this
      product at [fly.io/dashboard](https://fly.io/dashboard) (Organizations →
      New Organization).
- [ ] **Access Tokens** (in that org's dashboard, or `fly tokens create org`
      via the `flyctl` CLI) — create a token scoped to the new org and copy it
      into `backend/.env` as `FLY_API_TOKEN`.
- [ ] Copy the org's slug (shown in its dashboard URL) into `backend/.env` as
      `FLY_ORG_SLUG`.
- [ ] Pick a region close to wherever most of your users will be and set
      `FLY_REGION` (defaults to `iad` — US East). All of a user's project
      workspaces currently provision in this one region — see
      `/docs/PHASE2_NOTES.md` if you need per-project region choice later.
- [ ] Decide on `WORKSPACE_IMAGE` (defaults to a bare `ubuntu:24.04`).
      `ensure_workspace()` bootstraps `git`/`python3` on first boot either
      way, but if you want `run_lint` to work out of the box, either add
      `flake8`/`node`/`npm` to that bootstrap step yourself or build a small
      custom image with them preinstalled and point `WORKSPACE_IMAGE` at it.
      See `/docs/PHASE2_NOTES.md`'s rough-edges section — this one's flagged,
      not silently guessed at.
- [ ] **Set a spending/usage alert on the new org** before real users show up
      — nothing in this codebase caps how many workspaces can be provisioned
      or how long they stay running beyond §23.1's own sleep-when-idle
      behavior working correctly, and a bug in that behavior would show up as
      a Fly bill, not an error message.
- [ ] Before trusting any of this, run `backend/tests/test_workspace_integration.py`
      against this real org (see that file's own docstring for the env vars
      it needs) — implementation order step 5 explicitly calls for this to be
      verified in isolation before anything else depends on it, and it
      couldn't be run in the environment this was originally built in (no
      live Fly account available there).

## 4. Environment variables

Copy each `.env.example` to a real env file and fill it in — see
`backend/.env.example` and `frontend/.env.local.example` for the full list with
inline comments on where each value comes from. Short version:

**backend/.env** needs: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` (maybe blank, see above),
`GITHUB_OAUTH_CLIENT_ID` / `_SECRET`, `FLY_API_TOKEN`, `FLY_ORG_SLUG`
(Phase 2 — §3 above), `FRONTEND_URL`, `BACKEND_PUBLIC_URL`,
`CORS_ALLOWED_ORIGINS`.

**frontend/.env.local** needs: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`.

**Never commit either real env file** — `.gitignore` already excludes them, but
double-check before your first push if you're pasting real keys in to test.

## 5. Deploying (when you're ready — not needed for local dev)

See `docs/DEPLOYMENT.md` for the Render (backend) + Vercel (frontend) steps
matching the spec's own tech stack (§2). Once deployed, come back and update:
- The GitHub OAuth App's callback URL (or add a second app for prod, per above)
- Supabase's Site URL / Redirect URLs to your real frontend domain
- `FRONTEND_URL` / `BACKEND_PUBLIC_URL` / `CORS_ALLOWED_ORIGINS` on the backend
- `NEXT_PUBLIC_API_URL` on the frontend

## 6. Before you let real people sign up

- [ ] **Terms of Service / Privacy Policy** — not part of this codebase at all,
      and out of scope for me to draft here, but worth flagging since this
      system stores real credentials (LLM API keys, GitHub tokens) and account
      data for anyone who signs up, with no invite list. You mentioned this is
      already in progress separately — this is your reminder that it needs to
      land before a real launch, not after.
- [ ] **Rate limiting / abuse prevention** on `/auth/signup` — Supabase Auth has
      some built-in protections, but nothing in this Phase 1 backend itself
      throttles repeated signups or password-reset requests. Worth adding
      before this is public.
- [ ] **A production GitHub OAuth App** (separate from your dev one, per §2
      above), pointed at your real domain.

## Known rough edges to know about going in

- The GitHub OAuth App flow and the MCP connector OAuth flow both use an
  **in-process, single-instance** pending-state store (`backend/app/services/oauth_state.py`
  and `mcp_oauth_state.py`). This is fine for one backend process. If you scale
  the backend horizontally (multiple Render instances without sticky sessions),
  a person could start the OAuth flow on instance A and get redirected back to
  instance B, which won't recognize the state token. Swap these for a shared
  store (a Postgres table, or Redis) before doing that — see the comments in
  those two files for the exact shape needed.
- MCP connector OAuth (`backend/app/services/mcp_oauth.py`) implements RFC 8414
  discovery + RFC 7591 dynamic client registration + PKCE, which is what the
  MCP authorization spec expects — but real servers vary in how strictly they
  follow it. If a specific connector's OAuth connect fails, the error shows up
  plainly in the UI; "static token" auth mode is the reliable fallback for any
  server that just issues a plain bearer token.
- **Phase 2's rough edges** (the Fly Machines `/exec` response shape, the bare
  base workspace image, tree-sitter being optional, the GitHub auth header
  format) are all in `/docs/PHASE2_NOTES.md` rather than duplicated here —
  read that before relying on the Workspace Service or Push/Pull in production.
