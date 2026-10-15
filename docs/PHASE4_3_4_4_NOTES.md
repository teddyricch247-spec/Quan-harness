# Phase 4.3/4.4 Notes — Connector Integration polish & Auto-Provisioning

## Starting point: this was an audit, not a build

Both sub-prompts for this phase say the same thing in different words: the
spec content itself (§9 — account-level connect/review, OAuth path, per-tool
Auto/Ask/Off, per-project grants; §12 — the New Project flow's three setup
modes) was already delivered in full back in Phase 1, and this phase is "the
actual implementation work against a spec that already exists."

Reading `docs/PHASE1_NOTES.md` and the actual code confirmed that's true to
an unusual degree — Phase 1 didn't just stub these out, it built real,
working implementations:

- `routers/connectors.py` + `services/mcp_handshake.py` + `services/mcp_oauth.py`:
  a full draft → handshake → confirm flow, OAuth (RFC 8414 discovery + RFC
  7591 dynamic client registration + PKCE), static token and none auth
  modes, per-tool On/Off/Ask overrides, refresh, disconnect with cascading
  credential invalidation — plus a real working frontend page at
  `/connections/connectors`.
- `routers/projects.py` + `frontend/app/projects/new/page.tsx`: all three
  setup modes (scratch/import/create_new_repo), connector grants at
  creation time, a real 4-step wizard, plus a full per-project connector
  access toggle UI in project Settings (§9.3).

So this phase was not "build §9/§12" — it was **exercise both against
something real and fix what breaks**, which is exactly what the sub-prompts
ask for ("connect GitHub-as-connector here too, as the first real-world
connector exercised end to end"; nothing new for §12's content, "just the
implementation work"). Two real, concrete gaps came out of that — one per
sub-prompt — plus one already-documented gap (OAuth refresh) that happened
to sit squarely inside 4.3's own scope.

Everything below is either a fix, or a deliberate decision not to fix
something that turned out fine on inspection. Nothing in this phase invented
new scope beyond what tracing the existing code actually surfaced.

---

## 4.3 — Connector Integration

### Gap 1 (already documented): no MCP OAuth token refresh

`docs/PHASE3_NOTES.md` flagged this directly: `mcp_oauth.py` had
`exchange_code` but nothing to call once the access token it returns
actually expires — `mcp_tools.call_tool` would just surface a 401 as a plain
failed tool result, forever, until the person manually reconnected the
connector.

**Fixed:**
- `mcp_oauth.refresh_access_token(token_endpoint, client_id, refresh_token,
  client_secret=None)` — the refresh half of the token exchange, same shape
  and error handling as `exchange_code`.
- `mcp_tools.McpCallResult` gained a `status_code` field, populated from
  `httpx.HTTPStatusError` — the transport layer stays a single-attempt,
  no-retry module (unchanged design), it just now exposes enough for a
  caller to *decide* whether a retry is worth attempting.
- `tool_schemas.MergedMcpTool` gained `oauth_session_ref` and
  `oauth_client_secret_ref` (both default `None`, so every existing caller
  and test that builds a server dict without them is unaffected), and a new
  pure function `should_attempt_oauth_refresh(tool, status_code)` — True
  only for a 401 on an oauth-mode tool that actually has a refresh session
  on file. Unit-tested directly (6 new tests in `test_tool_schemas.py`).
- `agent_loop.py`'s `_execute_mcp` now calls that check after a failed call;
  on a match it attempts exactly one silent refresh (`_refresh_oauth_token`),
  updates the Vault-stored access token (and refresh token, if the server
  rotated it) in place, and retries the call once. A refresh that isn't
  attempted or that fails degrades to the original failure with a clearer
  message ("...reconnect it from Connections → Connectors") rather than
  raising — matching every other connector-call failure mode in that file.

### Gap 2 (found by exercising GitHub's real server): no path around servers without dynamic client registration

The sub-prompt names GitHub's own remote MCP server explicitly as "the first
real-world connector exercised end to end." Tracing what actually happens if
someone tries to connect `https://api.githubcopilot.com/mcp` via this
backend's existing OAuth flow: `oauth_start` always attempts RFC 7591
dynamic client registration (DCR) if the server's metadata doesn't already
give it a `registration_endpoint`, and raises a "Server has no dynamic
client registration endpoint... try static token instead" error otherwise.

Checked against reality (not assumed): GitHub's authorization server
(`github.com`) is a confirmed, currently-open case of exactly this —
[github/copilot-cli#4604](https://github.com/github/copilot-cli/issues/4604)
and
[github/github-mcp-server#1404](https://github.com/github/github-mcp-server/issues/1404)
are two independent, current reports of DCR failing against GitHub's real
server for this exact reason. So before this phase, GitHub's own connector
could only ever be connected in `static_token` mode (a personal access
token) — never via real OAuth, regardless of what the person supplied.

**Fixed:**
- `mcp_servers` gained two columns (`0008_connector_oauth_client.sql`):
  `oauth_client_id` (plain text — a client_id is a public identifier, not a
  secret) and `oauth_client_secret_ref` (a Vault ref, for a confidential
  pre-registered client — GitHub OAuth Apps are confidential, unlike the DCR
  path's public client).
- `McpServerCreate` accepts `oauth_client_id`/`oauth_client_secret`;
  `create_connector` validates and stores them (400 if a secret is given
  without a client_id, or either is given outside `auth_mode == "oauth"`).
- `oauth_start` now checks for a stored `oauth_client_id` *before* attempting
  DCR — when present, it's used directly and DCR is never attempted, even if
  the server happens to also advertise a `registration_endpoint`. The error
  message for the no-DCR-and-no-preregistered-client case now points at this
  option instead of only static_token.
- `oauth_callback`/`mcp_oauth.exchange_code` now thread an optional
  `client_secret` through the authorization-code exchange, sent as a plain
  POST body parameter — the same form GitHub's own
  `/login/oauth/access_token` endpoint accepts for an OAuth App's
  client_secret. `refresh_access_token` (above) takes the same parameter for
  the same reason.
- `delete_connector` now also deletes `oauth_client_secret_ref` from Vault on
  disconnect — closing the same "invalidate every credential this row holds"
  requirement §9.2 already states for the other two refs on the row.
- Frontend: the Connectors page gained a "Quick connect: GitHub" button that
  pre-fills name/url for GitHub's real server and defaults to
  `static_token` mode (the reliable path with zero setup), plus optional
  OAuth Client ID/Secret fields shown whenever `auth_mode = "oauth"` is
  selected, with inline help text explaining when they're needed. Confirmed
  connectors now show their pre-registered client_id (not secret) inline,
  so it's visible which auth path a connector is actually using.

**What this does *not* claim:** nobody in the environment this was built in
had a live GitHub OAuth App, a running backend, or a browser to actually
click through the redirect — the DCR-failure claim above is sourced from two
current, independent GitHub issue reports, not from running this code
against GitHub's server. The `static_token` path (a PAT) needs no such
claim — it was already working, unchanged, and is still the button's
default for exactly that reason.

---

## 4.4 — Auto-Provisioning

The sub-prompt is explicit that the New Project flow itself needed "no new
content" and to "build the plain flow now" — monorepo detection (§23.6) is
correctly out of scope, deferred to a later phase, and untouched here.

Auditing the actual flow end to end (`create_project` → `create_workspace_stub`
→ `workspace_service.ensure_workspace` → what happens to an imported repo's
content) surfaced one real, concrete bug that undercuts exactly the "plain
flow" this sub-prompt is about:

### Gap: 'import' mode never actually imported anything

- `create_project`'s `'import'` branch hardcoded
  `github_default_branch = "main"`, with a comment promising it would be
  "confirmed/corrected once the Workspace Service (Phase 2) clones it."
- Reading `workspace_service.ensure_workspace` (Phase 2, now real) shows it
  never clones anything, for *any* setup mode — it always just runs a bare
  `git init` on a fresh Sprite. The only place a clone-shaped operation
  exists at all is `git_sync.pull()`, which is strictly user-triggered (§25
  — Push/Pull are never automatic).

Put together: creating an "import" project left the workspace an **empty**
git repository, silently unrelated to the real GitHub repo, until the person
happened to know to click Pull themselves from the project's Workspace
panel. And even then, the first Pull would very likely fail outright —
`git_sync.pull()` fetches `github_default_branch` by name, which had been
guessed as `"main"` rather than looked up, so any repo whose real default
branch is `master`, `develop`, or anything else would get
"couldn't find remote ref" on its very first sync.

**Fixed** (`services/github_oauth.py`, `routers/projects.py`):
- `github_oauth.get_repository(token, full_name)` — a plain
  `GET /repos/{full_name}` call, resolving the repository's *real* default
  branch at project-creation time instead of assuming "main." Also fails
  project creation early and clearly (502, with the real GitHub error) if
  the repo doesn't exist or the credential can't see it — previously this
  only surfaced much later, and more confusingly, at first-Pull time.
- `create_project` now calls `git_sync.pull(..., confirm_discard=True)`
  immediately after creating an 'import' project's workspace stub —
  `confirm_discard=True` is safe specifically because the workspace is
  provably brand new at that point (zero commits), so there is nothing local
  to discard. This makes 'import' mode actually import, synchronously, by
  the time project creation returns, using the mechanism Phase 2 already
  built rather than inventing a new one.
- A failure in that pull (most likely today: Fly/Sprites credentials aren't
  configured yet — see `AGENTS.md`) does **not** fail project creation; the
  project row, its GitHub link (with the now-correct default branch), and
  its credential selection are all real and useful regardless. The failure
  is instead returned on the creation response as a new
  `ProjectOut.import_pull_error` field (`None` everywhere else — see its own
  docstring in `models/schemas.py`), which the New Project wizard passes
  through to the project page as a one-time, dismissible banner pointing at
  the Workspace panel's own Pull button to retry.

**What this does *not* fix:** the `'scratch'` and `'create_new_repo'` setup
modes were already correct as-is (a from-scratch or brand-new-on-GitHub repo
genuinely has nothing to clone — an empty `git init` is the right starting
state for both) — nothing about them changed. Also unchanged: the
`'create_new_repo'` path's own default-branch handling, which was already
correct (it reads `default_branch` straight back from GitHub's repo-creation
response, never guesses it).

---

## Everything reviewed and found already correct (no change made)

Worth naming explicitly, since a fix list alone doesn't show what was
checked and ruled out:

- The per-project connector access grant UI (`project Settings` →
  "Connectors granted to this project", `PUT /projects/{id}/connectors-access`)
  — real, wired, works independently of the New Project wizard's own
  at-creation-time grant step.
- `mcp_handshake.py`'s discovery/tools-list logic, including how it handles
  a server with a large tool list (GitHub's real server exposes 45+ tools
  across categories) — no pagination assumption or size limit that would
  break on a realistic connector.
- `tool_schemas.merge_mcp_tools`'s server-name-collision handling — already
  correctly disambiguates two connectors that slugify to the same name.
- `create_new_repo` mode's whole path, `find_open_pull_request`/
  `create_pull_request` — all correct as-is; no changes.

---

## Testing

Same honesty convention as every prior phase's notes: nothing here has run
against a real database, workspace, or browser in the environment this was
built in (no network access — see `docs/PHASE3_NOTES.md`).

- `test_tool_schemas.py` gained 6 new tests (`oauth_session_ref`/
  `oauth_client_secret_ref` default to `None` and thread through correctly;
  `should_attempt_oauth_refresh`'s four decision branches) — pure logic, no
  I/O, reviewed by hand line-by-line but not executed under `pytest` in this
  environment, same as every other pure-module test in this repo per the
  top-level README's own caveat.
- `mcp_oauth.py`, `github_oauth.py`, `agent_loop.py`'s new
  `_refresh_oauth_token`/`_execute_mcp` branch, and `routers/projects.py`'s
  new import-mode path are all I/O-bound (httpx, Vault, git-in-a-Sprite) and
  fall into the same "reviewed and reasoned through, not run" bucket the
  rest of `mcp_oauth.py`, `github_oauth.py`, and `agent_loop.py` were
  already in before this phase — this phase didn't change that bucket,
  just what's reasoned through inside it.
- The GitHub-DCR claim underpinning Gap 2 above is sourced from two current,
  independent GitHub issue reports (linked above), not from a live test
  against GitHub's server — flagged the same way `workspace_service.py`'s
  own "ROUGH EDGE" note flags its Sprites SDK inferences: real, sourced, but
  not verified end-to-end in this environment.

## What's next

Scheduling (4.5), the deploy pipeline, Live Preview, sub-agent delegation,
and visual QA remain exactly as `docs/PHASE4_1_4_2_NOTES.md`'s closing
section described them — this phase touched none of that surface.

One thing worth flagging for whoever picks up 4.5 or later, found but out of
scope to fix here: `agent_loop.py`'s turn loop (`_run_inner`), including the
OAuth refresh branch added this phase, has zero automated test coverage —
same gap the top-level README already calls out for the rest of that
function, just now also true of the new branch inside it.
