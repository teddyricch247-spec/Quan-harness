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

## 3. Fly.io Sprites (Phase 2 — the Workspace Service, §23)

Every project's workspace is a real Fly.io Sprite (https://sprites.dev) — a
persistent, hardware-isolated Linux sandbox with its own disk, created lazily
the first time it's needed. A Sprite hibernates automatically when idle and
wakes on the next request, so there's no manual start/stop step to configure
here the way the old Fly Machines integration needed.

- [ ] Create a Fly.io account at [fly.io/dashboard](https://fly.io/dashboard)
      if you don't have one already.
- [ ] Create a Sprites API token at
      [sprites.dev/account](https://sprites.dev/account) (or run
      `sprite org auth` with the Sprites CLI if you'd rather authenticate that
      way) and copy it into `backend/.env` as `SPRITES_API_TOKEN`. The token
      is scoped to one org on its own — there's no separate org-slug or
      region setting to fill in, unlike the old Machines setup.
- [ ] **For now** (you and your dev team testing this together): your
      **personal** Fly.io org is fine — new accounts get a $30 usage credit,
      which comfortably covers development. **Before you open this up to
      other people**, create a **dedicated org** for it (Organizations → New
      Organization in the Fly dashboard) and generate a new token scoped to
      that org instead — every signed-up user's Sprite will end up inside
      whichever org this token points at, and you don't want that mixed in
      with your own personal usage or billing once it's not just you and your
      devs anymore.
- [ ] **Set a spending/usage alert on whichever org you're using** before real
      users show up — nothing in this codebase caps how many Sprites can be
      provisioned, and a bug in the idle-hibernation behavior (which Sprites
      handle automatically — not something this codebase commands; see
      `/docs/PHASE2_NOTES.md`) would show up as a Fly bill, not an error
      message.
- [ ] Before trusting any of this, run `backend/tests/test_workspace_integration.py`
      against this real account (see that file's own docstring for the env
      vars it needs) — implementation order step 5 explicitly calls for this
      to be verified in isolation before anything else depends on it.

## 4. Environment variables

Copy each `.env.example` to a real env file and fill it in — see
`backend/.env.example` and `frontend/.env.local.example` for the full list with
inline comments on where each value comes from. Short version:

**backend/.env** needs: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` (maybe blank, see above),
`GITHUB_OAUTH_CLIENT_ID` / `_SECRET`, `SPRITES_API_TOKEN`
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
- [ ] **A dedicated Fly.io org for Sprites** (per §3 above) — don't launch to
      other people on your personal org's token.

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
- **Phase 2's rough edges** (an unverified `sprite.run(..., dir=...)` kwarg
  name in the Sprites port — see `workspace_service.py`'s own module
  docstring — plus tree-sitter being optional and the GitHub auth header
  format) are all in `/docs/PHASE2_NOTES.md` rather than duplicated here —
  read that before relying on the Workspace Service or Push/Pull in production.
