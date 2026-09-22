# Phase 2 notes — Workspace Service, structured file tools, Push/Pull, shell

Written the same way /docs/PHASE1_NOTES.md was: an honest account of what's
real, what's a documented rough edge, and every place this build had to make a
call the spec excerpt didn't fully pin down. Read this before touching any of
Phase 2's code, and before starting Phase 3.

**Update — ported to Fly.io Sprites.** The Workspace Service originally
targeted the Fly Machines API; it's since been rewritten against Fly's newer
Sprites product (https://sprites.dev) via the official `sprites-py` SDK — see
`workspace_service.py`'s own module docstring for exactly what changed and
why. Everything below describes the module as originally built; the two rough
edges that were Machines-specific (#1 and #2) are marked resolved in place
rather than rewritten, so this still reads as an honest history of both
versions rather than pretending the Machines integration never happened.

## What's real and working

- **Workspace Service** (`app/services/workspace_service.py`) — a real Fly.io
  Sprites client (originally Machines; see the update note above): creates
  one Sprite per project, lazily on first use (§14.6), with its own built-in
  persistent disk — no separate App/Volume to provision the way Machines
  needed. Sprites hibernate and wake automatically, so `wake()`/`sleep()` no
  longer command a start/stop the way they used to; `wake()` still forces the
  wake-up now for the UI's benefit, and `sleep()` refreshes billing_state from
  the Sprite's own reported status instead. `exec_in_workspace()` is still the
  one primitive everything else in this phase is built on.
- **File tools** (`app/services/file_tools.py` + the pure matching/syntax logic
  in `text_edit.py`) — `view_file`/`str_replace`/`create_file`, all three
  working against a real workspace over the exec primitive above. `str_replace`
  fails loudly on anything but exactly one match (§14.2) — see
  `apply_str_replace`. Files are written via a Python one-liner fed its payload
  as a base64 argv element specifically so file content is never interpolated
  into a shell string.
- **Automatic syntax check** (§22, in `text_edit.py`) — a real `compile()` call
  for Python (runs locally against content already in hand, no workspace round
  trip needed); a real bracket/string/comment-aware balance checker for
  JS/TS/JSX/TSX (`check_js_ts_heuristic`) as the documented fallback the spec
  itself allows when a full type-check isn't run. An optional tree-sitter pass
  runs ahead of both if `tree-sitter`/`tree-sitter-languages` happen to be
  installed — see "Rough edges" below for why that's optional rather than a
  hard dependency.
- **Checkpoints** (`app/services/checkpoints.py`) — real, unconditional git
  commits inside the workspace's own hidden history after every successful
  edit; FIFO-capped at 10 (`checkpoint_fifo.py`); restore does a real
  `git reset --hard`, deletes later checkpoints/events for that session, and
  closes every other open session on the project to read-only (§23.4).
- **Session concurrency cap** (`app/repositories/sessions.py`) — opening a 3rd
  writable session for a project really does demote the least-recently-used of
  the existing two to read-only (§23.4/§25), enforced on every `create_for_project`
  call.
- **execute_bash** (`app/services/shell_tools.py` + the pure guard logic in
  `guard_rules.py`) — the heuristic guard's six structural rules (sudo, paths
  outside the workspace, curl/wget-into-shell, credential-file-location
  references, git remote/branch operations, literal secret values) are all
  real, all unit tested, and checked in the order §14.3 lists them. A blocked
  command never executes. Output is truncated and secret-masked for real.
  `build_bash_env`'s signature is the actual isolation guarantee — it has no
  parameter a GitHub or connector credential could arrive through (see its
  docstring, and `test_execute_bash_env_isolation.py`).
- **run_lint / run_tests** — real: language detection via lockfile/config
  presence, flake8 restricted to the fatal-only ruleset §22 names, an eslint
  invocation for JS/TS against the project's own config if present, and
  `projects.test_command` execution for run_tests.
- **Push / Pull** (`app/services/git_sync.py`) — real GitHub REST calls
  (repo creation, PR lookup/creation) and real git operations against the
  workspace. The GitHub write credential is used to build a single
  `http.extraHeader` git-config value passed as one CLI argument per call —
  **never** written into the workspace's own `.git/config`, so it can't leak
  through anything `execute_bash`'s heuristic guard would otherwise have to
  worry about (`git remote -v` inside the workspace shows a bare
  `https://github.com/...` URL, same as a token-less clone).
- **project_secrets** (`app/repositories/project_secrets.py` +
  `app/routers/workspace.py`) — vault-backed, same pattern as
  `llm_credentials`/`github_credentials`; raw values never stored outside
  Vault, never returned over HTTP (only last-four, matching the existing
  credential-masking convention).

## Testing — what actually ran, and what needs real infrastructure

Same split Phase 1 landed on with `test_rls_isolation.py`: pure logic gets
real, run tests; anything that needs a live Fly.io Sprite or a live GitHub
repo is written as a real integration test but documented as requiring real
credentials, since no such account was available while building this.

**Ran locally, 88/88 passing** (`backend/tests/test_heuristic_guard.py`,
`test_str_replace_logic.py`, `test_checkpoint_fifo.py`, `test_syntax_check.py`,
`test_execute_bash_env_isolation.py`, `test_workspace_paths.py`,
`test_repo_naming.py`):

To make this possible at all, the pure decision logic was deliberately pulled
out of the I/O-heavy service modules into dependency-free files with **zero**
imports of `httpx`/`fastapi`/`supabase`/`app.config` — `guard_rules.py`,
`text_edit.py`, `checkpoint_fifo.py`, `repo_naming.py`, `workspace_paths.py`.
The service modules (`shell_tools.py`, `file_tools.py`, `checkpoints.py`,
`git_sync.py`, `workspace_service.py`) import from these rather than
redefining the logic inline. This is a real architectural split (pure core /
imperative shell), not a testing trick — it's what let these tests run for
real, against the actual shipped code, with no network and no package
installs available in the environment this was built in. **One real bug this
caught**: `resolve_repo_path(".")` originally returned `REPO_ROOT + "/"`
instead of `REPO_ROOT` because of an empty-string artifact in how
`"".split("/")` behaves — fixed in `workspace_paths.py`, verified by
`test_bare_dot_resolves_to_root`.

**Written, not run — need real credentials** (`test_workspace_integration.py`,
`test_push_pull_integration.py`): the live counterparts to implementation
order steps 5–7's own literal instructions ("create a trivial project
workspace, run a command, confirm persistence across a sleep/wake cycle";
"a real end-to-end test that a model-scope execute_bash call genuinely cannot
reach the internal clone/checkpoint machinery's own credentials"). Both read
credentials straight from the environment the same way `test_rls_isolation.py`
does — `QH_TEST_PROJECT_ID`, `QH_TEST_USER_ID`, plus `SPRITES_API_TOKEN`
(originally `FLY_API_TOKEN`/`FLY_ORG_SLUG` — see the update note at the top)
and a connected GitHub credential. **Run these against a real account before
trusting this in production.**

## Rough edges (same spirit as Phase 1's OAuth section — flagged, not hidden)

1. ~~**Fly Machines' `/exec` endpoint response shape isn't in Fly's indexed
   API reference.**~~ **Resolved by the Sprites port** — moot now that
   `workspace_service.py` goes through the official `sprites-py` SDK instead
   of parsing raw HTTP responses by hand. That SDK is itself brand new
   (first stable release days before this port was written) with its own,
   smaller, unverified surface — see `workspace_service.py`'s own ROUGH EDGE
   note on the `dir=` exec kwarg for what replaced this.
2. ~~**The base workspace image is bare Ubuntu with no toolchain
   preinstalled.**~~ **Resolved by the Sprites port** — every Sprite ships
   with git, Python, Node, and other common tools preinstalled, so
   `ensure_workspace()`'s old bootstrap-install step is gone entirely.
   `flake8`/`eslint` specifically still aren't preinstalled, so `run_lint`
   still depends on the project's own `npm install`/`pip install` the same
   way it always has — that part of this rough edge was never
   image-specific and still applies.
3. **Tree-sitter is optional, not a hard dependency** (`text_edit.py`'s
   `_tree_sitter_check`) — not added to `requirements.txt` because its exact
   current package/version shape couldn't be verified against a real install
   in this environment (no network for `pip install` here), and shipping an
   unverified heavy native dependency seemed worse than the honest fallback
   the spec itself allows (§22: "fall back to a lighter parser-level syntax
   check instead of skipping JS/TS entirely"). Install `tree-sitter` +
   `tree-sitter-languages` for the full language-agnostic pass §22 describes;
   without them, the Python `compile()` check and the JS/TS bracket-balance
   heuristic are what's actually catching syntax errors.
4. **GitHub PAT auth header format** (`git_sync.py`'s `_auth_header_config`) —
   uses the `Authorization: basic base64(x-access-token:TOKEN)` scheme (the
   same one GitHub Actions' own `GITHUB_TOKEN` uses for git-over-HTTPS).
   Should work for both classic and fine-grained PATs but wasn't verified
   against a real push, for the same "no live GitHub credential available
   here" reason as everything else in this section.
5. **The JS/TS heuristic syntax check false-positives on JSX prose text
   containing English contractions** — `check_js_ts_heuristic` in
   `text_edit.py` tracks string/template-literal state character-by-character
   but has no concept of "JSX child text node" as distinct from "JS string
   literal," so an apostrophe in ordinary prose (`haven't`, `what's`, `can't`)
   inside a `.tsx` file's JSX children reads as opening a string that never
   closes. Caught by literally running it against this delivery's own new
   `.tsx` files (`WorkspaceSyncPanel.tsx`, the edited `projects/[id]/page.tsx`
   and `settings/page.tsx`) as a sanity check — all three false-positived on
   exactly this. Plain `.ts` files without JSX are unaffected (`types.ts`
   checked clean). Two honest options for Phase 3, neither implemented here:
   track JSX-text-vs-expression context (a real scope increase — knowing when
   `{...}` opens a JS expression inside JSX vs. when plain text is being
   parsed), or scope this heuristic's string-tracking down to `.ts`/`.js`
   only and skip it for `.tsx`/`.jsx` (losing bracket-balance coverage for
   JSX files specifically, gaining zero false positives). Left as-is rather
   than guessed at under time pressure — the risk of a wrong scope decision
   here seemed worse than documenting the gap plainly.
6. **The Sprites port itself is unverified against a live account** (added
   with the update above) — `sprite.run(..., dir=cwd)`'s exact kwarg name,
   and the exception types raised on a timed-out or failed exec, are both
   inferred from `sprites-py`'s public docs/README rather than a source-level
   signature check — see `workspace_service.py`'s own module docstring for
   specifics. Run `test_workspace_integration.py` against a real Sprites
   account before trusting this in production; if `dir=` is wrong, the fix is
   a one-line change to wrap the argv in `["bash", "-c", f"cd {cwd} && ..."]`
   instead.

## Design decisions this phase had to make that the spec excerpt didn't spell out

- **`project_secrets` table** — §14.3's execute_bash spec directly depends on
  it existing ("if the command text references a registered project_secrets
  name..."), but it wasn't in Phase 1's schema and isn't explicitly listed in
  this bundle's own numbered scope. Added in `0006_workspace_tools.sql` since
  step 8 can't be built without it — see that migration's own comment.
- **"Already viewed this session" for str_replace** (§14.2) is enforced
  against a caller-supplied `viewed_paths: set[str]` argument rather than a new
  persistent session-state table, since Phase 2 has no turn loop yet to own
  that state correctly. Phase 3's turn loop should pass its own accumulated
  "paths seen via view_file this session" set in — it already has to track
  something equivalent for the transcript.
- **run_lint's "base state"** (§22: diff "against the workspace's base state,
  not a specific base branch") — interpreted as this repo's own root commit
  (`git rev-list --max-parents=0 HEAD`): the empty `git init` commit for a
  from-scratch project, or the Import clone's original HEAD for an imported
  one. This was the only reading that doesn't require inventing a
  not-yet-specified "session start" marker.
- **Push's squash mechanism** (§23.4: "squash the local checkpoint-commit
  chain into whatever commit(s) actually get pushed") — implemented as one
  `git commit-tree` per Push, with the previous Push's remote tip as its
  parent (a real fast-forward, not a force-push) or rootless on the very first
  Push. Keeps a sensible one-commit-per-sync history on GitHub's side instead
  of either exposing every internal checkpoint commit or force-pushing a
  rootless snapshot every time.
- **Pull's source branch** — `harness/workspace` once it exists
  (`projects.harness_branch_ready`), otherwise the repository's own default
  branch (for pulling latest upstream content before any Push has ever
  happened, e.g. right after an Import).
- **`initiated_by='system'` for execute_bash's audit_log rows** — not
  `'agent'`, because nothing but tests calls execute_bash yet (§14 tools have
  no caller until Phase 3's turn loop exists — see `app/repositories/audit.py`'s
  own docstring on what `'agent'` rows are reserved for).
- **No HTTP endpoints for view_file/str_replace/create_file/execute_bash/
  run_lint/run_tests.** These are native agent tools (§14) with no caller
  until Phase 3. Exposing them over REST now would mean inventing an ad-hoc
  debug API the spec never asked for, and would blur the "zero agent-facing
  surface" property implementation order steps 6–8 ask for these tools to have
  in isolation. Push, Pull, workspace status, checkpoints, and project secrets
  *are* genuinely user-facing (§23.3), so those got real endpoints in
  `app/routers/workspace.py`.

## NOTICES.md

Aider's row (added by Phase 1, in anticipation of this phase) is now filled
in — its strict, non-fuzzy `str_replace` matching discipline is what
`apply_str_replace` in `text_edit.py` implements. See NOTICES.md itself for
the actual attribution text.

## What Phase 3 needs to know

- Every file-tool and shell-tool function (`file_tools.py`, `shell_tools.py`)
  is a plain importable async function with a clean signature — the turn loop
  should call these directly rather than going through HTTP, the same way
  Phase 2 itself never adds an HTTP layer in front of them.
- `str_replace`'s `viewed_paths` and `session_id` parameters, and
  `execute_bash`'s `session_id`, are exactly the per-session state the turn
  loop needs to own and pass in.
- `checkpoints.create_checkpoint`'s `conversation_snapshot` parameter defaults
  to empty — Phase 3 should pass the actual accumulated `session_events` for
  the turn so checkpoints capture more than file state.
- The approval flow implied by `execute_bash` returning
  `needs_approval=True` (instead of executing) has no UI or `approval_requests`
  row written yet — Phase 2 only makes the *tool-level* behavior real ("a
  match requires approval before the command runs, full stop"). Wiring that
  into the actual turn-loop pause/approval-card flow (§16.2) is Phase 3's job.
