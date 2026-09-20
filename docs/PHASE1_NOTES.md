# Phase 1 — what's actually here

This maps what's implemented against the spec's own Phase 1 scope (Implementation
Order steps 1–4) and names every stub/deferral explicitly, the same way the spec
itself names its non-goals — so nothing gets assumed-done that isn't.

## Fully implemented

**1. Auth & account scaffolding (§4)**
- Signup/login/password-reset via Supabase Auth, both frontend-direct (primary
  path, per §4) and backend-proxied (`/auth/*`, per §28's API surface).
- JWT verification supporting both HS256 (legacy secret) and JWKS (newer
  asymmetric-key projects).
- Email-verification gating (`verified_user` dependency) on every action that
  touches real infrastructure — connect a credential, connect a connector,
  create a project, create a session.
- Account deletion, cascading via `auth.users(id) on delete cascade` through
  every owned table, with a typed "DELETE" confirmation enforced both frontend
  and backend-side.

**2. Connections shell (§6–§9)**
- `llm_credentials`: full CRUD, set-default, rotate (overwrites the Vault
  value in place — every project selecting it picks up the change
  automatically, per §24).
- `github_credentials`: OAuth App flow (§8's "one Connect GitHub flow") +
  manual fine-grained PAT entry, list, rotate, delete. GitHub App
  (installation-based) credential type exists in the schema but isn't
  implemented — see "Deferred" below.
- `mcp_servers` + `mcp_tool_overrides`: the handshake→confirm flow from §9.1 —
  a draft row (`enabled=false`) is created immediately, a handshake runs where
  possible, and nothing merges into any project's tool set until `/confirm`
  flips `enabled=true`. Static-token and no-auth modes handshake synchronously;
  OAuth mode implements RFC 8414 discovery + RFC 7591 dynamic client
  registration + PKCE (best-effort — see `docs/YOUR_SETUP_CHECKLIST.md`'s rough
  edges section). Per-tool On/Off/Ask permissions, refresh (with stale-override
  cleanup per §9.2), disconnect (cascading, including Vault credential
  invalidation).

**3. Projects & Sessions (§10.2, §10.3, §12)**
- Full §12 setup flow: scratch (default), import (records the link; the actual
  clone is Phase 2 — see below), create-new-repo (real GitHub API call, since
  that's a plain REST call with no workspace dependency).
- Project CRUD, credential selection (LLM + GitHub), connector grants
  (`project_mcp_access`), test_command / max_turn_iterations, deletion with
  typed name confirmation.
- Sessions: create/list/get/archive/delete only — see "Deferred" below for why
  that's the deliberate boundary, not an oversight.
- Mobile-responsive nav (single-column collapse, hamburger menu) per §11.1's
  general pattern, **and** `/projects/[id]`'s own two-pane layout now runs
  through `components/WorkspaceShell.tsx` — the tab-switching single-column
  collapse the implementation order names specifically for the Workspace
  screen (§11.2), not just the nav. Both panes hold honest "not built yet"
  placeholders (Phase 3 for chat/plan, Phase 5 for Live Preview) rather than
  faking content, but the responsive shell itself is real now, so neither
  later phase has to revisit the layout — only fill in what each pane
  renders.

**4. Platform Operations (§24)**
- Every deterministic action in §24's table that has a real target in Phase 1's
  data model: connect/disconnect/rotate for both credential types, connect/
  review/disable/disconnect for connectors, grant/revoke project connector
  access, delete project, delete account — all audit-logged
  (`initiated_by='user'`), all reachable from a dedicated `/platform-ops`
  dashboard page as well as from their natural Connections/Settings locations.
- RLS live-tested, not just declared: `backend/tests/test_rls_isolation.py` runs
  real cross-account queries through two real Supabase-authenticated sessions
  and asserts zero rows come back — the actual requirement in §5, not a
  structural argument for why it should work. Covers every table this phase
  creates, including `checkpoints`/`session_events`/`approval_requests` (empty
  in production traffic this phase, but their policies are verified now rather
  than first exercised once Phase 3's real conversation data is on the line)
  and `audit_log` (the one table here scoped directly by `user_id` rather than
  a project join, tested separately for that reason). Beyond per-row lookups,
  a dedicated broad-select check confirms an unfiltered query never returns
  more than the caller's own rows — the failure mode a same-id lookup can't
  catch (an accidental `using (true)` policy).
- `NOTICES.md` — §29's licensing requirement, read before any code here was
  written. Nothing in Phase 1 touches the Aider/OpenHands/DeepSeek Harness
  adaptations §29 names, so the file states that plainly and carries a
  placeholder table, filled in truthfully as each one actually lands in
  Phase 2/3.

## Deliberately stubbed (schema exists, behavior doesn't yet)

These aren't bugs — they're Phase 2/3 work per the spec's own roadmap, and
building fake versions now would mean guessing at a turn-loop/workspace
contract the spec explicitly hasn't specified yet for this phase.

- **`project_workspaces`** — a row is created for every new project
  (`billing_state='cold'`, a placeholder `sprite_handle`), but nothing
  provisions a real Fly.io Sprite. That's the Workspace Service (Phase 2).
- **Imported repositories aren't actually cloned** — `projects.github_repo` gets
  set to what you typed, but the one-time clone into a persistent workspace
  needs the Workspace Service to exist first.
- **Sessions have no turn loop** — a session sits at `status='idle'` forever in
  this phase. No `/sessions/{id}/stream`, `/messages`, or `/interrupt` routes
  exist (Phase 3: turn loop, system prompt, context compaction).
- **`checkpoints`, `session_events`, `approval_requests`** — tables exist (per
  §10's "one standalone data model"), RLS is live on them, but nothing writes
  to them yet. They start filling up once the agent core exists.
- **The full Workspace screen (§11.2)** — the two-pane chat/plan/preview layout
  is Phase 2/3 UI. `/projects/[id]` in this phase is a stub page that's honest
  about being a stub, linking to the parts that *are* real (Settings, Sessions
  list).
- **`audit_log.ask_session_id`** — column exists as a plain `uuid` with no
  foreign key yet, because it references `chat_sessions(id)`, a table that
  belongs to the "Ask" surface (a much later phase). The exact `ALTER TABLE`
  to add the FK once that table exists is commented directly in
  `db/migrations/0005_sessions.sql`.

## Explicitly out of scope for Phase 1 (not started at all)

- GitHub App (installation-based) credential type — schema supports it
  (`credential_type='github_app'`), no implementation. The OAuth App + manual
  PAT paths cover everything §8 actually requires for Phase 1.
- Anything from Phases 2–9: Workspace Service, file tools, Push/Pull, shell,
  turn loop, system prompt, memory, deploy pipeline, Live Preview, sub-agent
  delegation, image input, the entire "Ask" surface, capability tiers.

## Bug-fix pass (after initial delivery)

A follow-up review caught four real issues, now fixed:

1. **Email verification was silently broken.** `verified_user` trusted a JWT
   claim (`email_confirmed_at` and two fallback names) that Supabase does not
   reliably put in the JWT itself unless you've configured a custom Access
   Token Hook — which this repo doesn't set up. As written, this meant every
   verified account would still get rejected forever. Fixed in
   `backend/app/dependencies.py`: the JWT claim is now only a fast-path skip
   when true; otherwise it asks Supabase's Admin Auth API directly (adds one
   network round-trip per gated request — fine for Phase 1's scale; a custom
   claims hook would remove it later if it ever matters).
2. **"Import an existing repository" didn't actually require a GitHub
   credential** on the backend, even though the spec's §12 says to "pick a
   GitHub sync credential" for that path, and the frontend wizard already
   enforced it. A direct API call (bypassing the wizard) could have created an
   import-mode project with no credential attached. Fixed in
   `backend/app/routers/projects.py`.
3. **Connector tool permissions didn't reflect their saved state on reload** —
   the On/Off/Ask buttons always rendered unselected, even for a tool someone
   had already set to Off, because the connector list endpoint never returned
   each tool's *current* resolved permission. Fixed by having
   `backend/app/routers/connectors.py`'s response include each tool's
   effective permission (override if set, else the server default, per §9.4's
   own resolution rule), and updating the frontend to initialize from it
   instead of starting blank.
4. Minor: a confusing double-masking call in the LLM credentials list endpoint
   (`mask_last_four(...)[-4:]`) produced the right answer by accident of how
   the two operations composed — simplified to a direct slice.
5. **Two gaps against this phase's own implementation order, caught in a
   second review pass:** no `NOTICES.md` existed at all (§29 — the spec says
   to read this section "before writing any code," and the file itself
   should exist from the start even with nothing to attribute yet), and
   `/projects/[id]` had no mobile single-column collapse — the whole
   Workspace screen was skipped to a flat stub rather than standing up
   §11.2's responsive shell the way the implementation order names
   explicitly. Both fixed: `NOTICES.md` added at the repo root, and
   `components/WorkspaceShell.tsx` now backs `/projects/[id]`'s two panes.
   The RLS suite also gained coverage it was missing for tables this phase
   already creates (`checkpoints`, `session_events`, `approval_requests`,
   `audit_log`) plus a broad-select invariant check, rather than only
   testing tables that happened to be covered in the first pass.

## A design call worth knowing about

The spec's §9.1 prose ("no row gets written until confirmation") and §28's API
surface (`GET /connectors/{id}/oauth-start` — which needs an `{id}` to exist
*before* confirmation) are in tension for OAuth-mode connectors, since the
redirect-based OAuth flow can't complete inside a single synchronous POST call.
This implementation resolves it by creating a draft row immediately
(`enabled=false`) and treating `enabled=true` as the actual activation gate —
which is also what §9.4's runtime tool merge already checks. A disabled draft
row existing in the table doesn't contradict "nothing is active anywhere" in
any way that matters functionally, but it's a real interpretive choice, not
something the spec spelled out — flagging it here in case a future phase reads
the spec differently.
