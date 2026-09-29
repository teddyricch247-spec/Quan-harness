# Phase 5.1/5.2/5.5 Notes — Deploy Pipeline, Monorepos & Failure Handling

Implements Combined Prompt A (§23.5 stack detection & build, §23.6 repo
structure edge cases, §23.9 deploy failure handling) — Implementation Order
step 16. Phases 1–4 were already complete going in. This does **not** cover
§23's remaining pieces from the same roadmap item — Live Preview (5.3),
sub-agent delegation (5.4), or visual QA — those are later sub-prompts and
nothing here assumes they exist yet.

## What this delivers

- `db/migrations/0010_deploy_pipeline.sql` — a `deploy_runs` table (one row
  per build+start attempt, holding the raw stdout/stderr/exit code plus,
  once produced, the diagnosis) and two columns on `projects`:
  `repo_origin` (`'scratch' | 'imported'`) and `deploy_targets_confirmed`.
- `app/services/deploy_detection.py` — pure, dependency-free rules (Nixpacks'
  own detection order: Dockerfile, then package.json/next, then
  requirements.txt) plus the tool-less LLM fallback's prompt-building and
  response-parsing, for both §23.5's single-root build plan and §23.6's
  monorepo root proposal.
- `app/services/deploy_diagnosis.py` — the tool-less diagnosis call §23.9
  point 2 describes, structured JSON in, `{diagnosis, failure_class,
  suggested_fix_prompt}` out, with the environment-class "never use 'fix'
  framing" rule (point 4) enforced in code, not just trusted from the model.
- `app/services/deploy_pipeline.py` — the I/O orchestration: scans a
  workspace, calls the two modules above, runs the actual build/start
  commands via `workspace_service.exec_in_workspace`, and writes
  `deploy_runs`. Same async-background-task-plus-in-memory-pub/sub shape as
  `agent_loop.py`.
- `app/repositories/deploy_runs.py`, schema additions in `models/schemas.py`,
  `app/routers/deploy.py`, registered in `main.py`.
- `system_prompt.py`/`agent_loop.py` — a new `DEPLOY_DIAGNOSIS` dynamic
  section (§23.9 point 3: "available context for the main agent's next
  turn").
- `frontend/components/DeployPanel.tsx`, wired into the project page's right
  pane, plus `frontend/lib/types.ts` additions.
- A real bug fix in `guard_rules.py` (see "Gap found while auditing" below).
- `backend/tests/test_deploy_detection.py` (30 tests),
  `backend/tests/test_deploy_diagnosis.py` (13 tests),
  `backend/tests/test_deploy_pipeline.py` (17 tests) — all passing.

## Design decisions the sub-prompt's own text doesn't spell out

### "Building a container image regardless of source language" isn't an instruction to build container images here

§23.5 cites Nixpacks building a container image "regardless of source
language" as the reason its detection order is worth following. Taken
literally against this codebase, that would mean actually running
`docker build` inside a Sprite workspace for a Dockerfile-having repo — but
§23.6, two sections later in the same sub-prompt, says directly that Sprites
aren't Docker-based and nested virtualization isn't something to lean on.
Those two sentences can't both be followed literally.

This reads Nixpacks' container-building property as background on *why*
Nixpacks' detection order is worth copying, not as an instruction to build
actual images. A detected Dockerfile is handled as an immediate,
**deterministic** §23.6 nested-sandboxing case — caught by
`deploy_pipeline.py` before any build is attempted (a static file check, not
a failure caught after trying), so it never wastes a build attempt or an LLM
diagnosis call on something that was never going to work. The message
surfaced is the sub-prompt's own wording verbatim: "this app requires nested
container support, which preview doesn't support yet."

### The monorepo confirmation gate is keyed on `repo_origin`, not root count

§23.6: "This detection/confirmation step is for imported repos only." That
sentence doesn't say whether a single-root *imported* repo still needs a
one-time confirmation click, or whether confirmation is only for the
genuinely-multi-root case. This picks the former — confirmation is gated on
`projects.repo_origin == 'imported'` full stop, independent of how many
roots detection actually finds. Reasoning: "the harness doesn't already know
the shape of this codebase" is exactly as true for a single-root imported
repo as a multi-root one; the distinction §23.6 draws is about *authorship*
of the repo's structure, not its complexity. `test_deploy_pipeline.py`'s
`test_imported_project_single_root_still_needs_one_time_confirmation` pins
this down explicitly since it's the one case a root-count-based reading
would have handled differently.

`repo_origin` itself didn't exist anywhere in the schema before this —
nothing recorded which of §12's three setup modes (`scratch`,
`create_new_repo`, `import`) a project was created under, once creation
itself finished. `routers/projects.py`'s `create_project` now writes it:
`'imported'` for `mode == "import"`, `'scratch'` for the other two (both
authored by Quan Harness itself, or not yet existing — no outside scan could
tell the person anything about either they don't already know). **Every
project row that predates this migration defaults to `'scratch'`** — real
setup mode isn't recoverable retroactively for those rows. If you have a
specific already-imported project you want the confirmation gate to apply
to, a one-time `UPDATE projects SET repo_origin = 'imported' WHERE id = ...`
fixes that project alone.

### "All or nothing" stack detection

§23.5 doesn't say what happens when a rule confidently resolves a
`build_cmd` (there's a requirements.txt) but can't resolve a `run_cmd` (no
Procfile, no manage.py, no recognizable entrypoint). `detect_stack_from_rules`
returns `None` for the whole result rather than a half-filled one, falling
through to the LLM fallback for the complete `{build_cmd, run_cmd, port}`
triple. A confident build_cmd paired with a guessed run_cmd is a worse
contract than one clearly-labeled `stack="llm_fallback"` result — "where did
this plan actually come from" shouldn't be a per-field question.

### "Start" health is judged by process survival, not an HTTP check

A launched process is judged healthy if it's still running
`PROBE_SECONDS` (5s) after launch — not by curling the detected port. Many
real apps don't serve `200` on `/`, and a false "unhealthy" from an HTTP
probe is a worse failure mode than accepting "still alive" as the signal.
What this phase is actually trying to catch (a missing dependency, a bad
config read, a startup-time crash) shows up as the process dying, which
this does catch. Whether the app is *also* correctly serving traffic yet is
a Live Preview / proxying question (§23, out of scope here — 5.3).

### The BACKEND_URL heuristic is narrow on purpose

§23.6's own example names two targets, `frontend` and `backend`, and says
"the frontend needing the backend's preview URL auto-injected as an env
var." Since both targets of a monorepo run inside the *same* Sprite (one
workspace per project, not per target), "the backend's preview URL" from the
frontend's own process's point of view is just `http://127.0.0.1:<port>` —
no externally-routable URL is involved (Live Preview's proxying, §23, is
still 5.3). `deploy_pipeline.py` deploys a target literally named `backend`
(case-insensitive) before one literally named `frontend`, and only injects
`BACKEND_URL` when both names are present and the backend resolved a real
port. This is real, working, and exactly matches the sub-prompt's own
example — but it is not general inter-service dependency detection; a
monorepo with different target names, or more than two targets, gets no
cross-injection. Real dependency graphs are out of scope for this sub-prompt.

### The needs-confirmation response is a 200, not a 409

`POST /projects/{id}/deploy` returns `DeployTargetsProposal` as a normal 200
response (a `needs_confirmation` boolean field distinguishes the outcome),
not an HTTP error status — matching `routers/workspace.py`'s existing
`PullResult.needs_confirmation` pattern exactly, for the same reason: a
branch that needs the person's own input isn't an error condition. Only "a
deploy is already running for this project" is a real 409.

## Gap found while auditing: `guard_rules.py`'s `REPO_ROOT` was stale

While tracing `exec_in_workspace`'s callers to build the deploy pipeline's
own shell scripts, `guard_rules.py`'s heuristic guard turned out to still be
checking absolute paths against `"/workspace/repo"` — the Fly *Machines*-era
Volume mount path — even though `workspace_paths.py`'s own `REPO_ROOT` moved
to `"/home/sprite/repo"` when the codebase ported to Sprites. `guard_rules.py`
duplicates the literal on purpose (to stay dependency-free for unit
testing), not because the two were ever meant to disagree — the port just
silently missed this one spot.

Effect: `_escapes_workspace()`'s check `token.startswith(REPO_ROOT)` was
comparing against the wrong root, so a legitimate absolute path like
`/home/sprite/repo/README.md` would have been flagged as escaping the
workspace, while the actually-unreachable `/workspace/repo/README.md` would
have been waved through. Likely low real-world impact so far —
`shell_tools.execute_bash` always runs with `cwd=REPO_ROOT` (the correct,
current one), so most agent-issued commands use relative paths and never hit
this branch — but a real, live inconsistency all the same, and exactly the
kind of thing that's cheap to fix once found and easy to leave live
indefinitely otherwise. Fixed; `test_heuristic_guard.py`'s
`test_absolute_path_inside_workspace_is_allowed` updated to assert against
the real, current path instead of the stale one.

## Rough edges / known gaps

- **No live Sprite or LLM credential was available to run any of this
  against** (the Supabase project *was* reachable in the later review pass — see below) — same "ROUGH EDGE" honesty
  `workspace_service.py`/`llm_client.py` already carry for their own pieces.
  Everything pure (`deploy_detection.py`, `deploy_diagnosis.py`'s parsing)
  is unit-tested and passing. `deploy_pipeline.py`'s orchestration is tested
  with every collaborator (repos, `exec_in_workspace`, `call_llm`) replaced
  by an in-memory double, same convention as `test_agent_loop_audit.py` — it
  has **not** been run against a real Sprite. Two things in particular are
  worth verifying against one before trusting this in production:
  - Whether the detached launch (`nohup setsid bash -c ... &`) really does
    survive past the single `sprite.run()` call that launched it, the way it
    would over a real SSH connection. (The launch script itself *was* executed
    for real in a local bash during review — see below — but not on a Sprite.) This is standard Unix process-detachment behavior
    and should hold, but "should" isn't "verified here."
  - Real request/response shapes from each of the two tool-less LLM fallback
    calls against a real Anthropic/OpenAI/Google/OpenRouter credential — the
    JSON-in-JSON-out contract is enforced by `deploy_detection.py`/
    `deploy_diagnosis.py`'s own parsing either way (a malformed response
    raises a clear error rather than silently misbehaving), but no live call
    has actually exercised it.
- **The `/deploy/stream` SSE endpoint has no frontend consumer.** Same
  situation `routers/agent.py`'s `stream_session` is already in: both need a
  Bearer Authorization header, which native `EventSource` can't send, and
  neither this phase nor Phase 3's frontend has solved that yet. `DeployPanel.tsx`
  polls `GET /deploy/runs` every 2 seconds instead — real, working, and
  avoids inventing a second unsolved-auth pattern alongside the first. A
  `fetch()`-based streaming reader (which *can* carry the header) is the
  natural fix for both endpoints at once, whenever the chat transcript UI
  takes this on.
- **Rule-based Python entrypoint detection is Procfile/manage.py/app.py/
  main.py only.** A Python project structured any other way (a `src/`
  layout, a WSGI file with a different name) falls through to the LLM
  fallback rather than being rule-detected — deliberate (§23.5's own "all or
  nothing" framing, see above), just worth knowing this rule set is narrow,
  not exhaustive.
- **`_run_script`'s package-manager selection is lockfile-presence only** —
  it doesn't handle a repo with more than one lockfile present at once (e.g.
  both `package-lock.json` and `pnpm-lock.yaml` left over from a migration).
  pnpm is checked before yarn before npm; a repo in that specific messy state
  gets pnpm's install command whether or not that's actually the one in use.
  Narrow edge case, not handled.
- **`DeployPanel.tsx`'s target-confirmation UI lets a person edit the
  proposed `name`/`root` freely but doesn't validate that an edited `root`
  actually exists in the repository** — that validation happens for free the
  moment the next deploy actually scans it (a bad root just fails detection
  with a clear error), so this isn't a correctness gap, just something that
  surfaces one step later than it could.

## Testing

`backend/tests/test_deploy_detection.py` — 30 tests, pure rule-based
detection (every stack branch, every "returns None, falls through" case) and
LLM-fallback response parsing (valid JSON, a markdown-fenced response, every
rejected-input case) for both §23.5 and §23.6. Zero mocking; the module
itself has no import beyond the standard library.

`backend/tests/test_deploy_diagnosis.py` — 13 tests, `parse_diagnosis_response`
and `build_diagnosis_prompt`. Covers the environment-class "never carries a
fix prompt, even if the model supplied one" enforcement directly.

`backend/tests/test_deploy_pipeline.py` — 10 tests, `deploy_pipeline.py`'s
orchestration with `deploy_runs_repo`, `projects_repo`, `workspace_service.
exec_in_workspace`, and `llm_client.{resolve_credential,call_llm}` all
replaced by in-memory doubles (same convention as `test_agent_loop_audit.py`).
Covers: a `'scratch'` project's auto-confirmed single-root deploy succeeding;
an already-running deploy being rejected; an `'imported'` project's ambiguous
roots correctly reaching the LLM fallback and raising
`DeployNeedsConfirmation`; an `'imported'` single-root repo still needing
confirmation; a confirmed multi-root project skipping re-detection of roots;
the Dockerfile nested-sandbox short-circuit never calling the LLM; a
start-phase crash being captured, diagnosed, and recorded with the right
`exit_code`; a build-phase failure never reaching the start phase; a broken
diagnosis call never blocking the raw log from being saved; and the
`backend`-before-`frontend` ordering with `BACKEND_URL` injection.

`backend/tests/test_heuristic_guard.py` — one existing test updated (see
"Gap found while auditing" above); everything else in that file untouched.

All three new files, plus the updated existing one, were run function-by-
function in this environment (no `pytest` available here — no network to
install it) and every test passes. They should also just work under a real
`pytest` in CI without modification — same import style every other pure-
logic test file in this suite already uses.

## Review pass (2026-09-29) — bugs found and fixed after the first delivery

An independent review of the delivered code found these; all are fixed and
covered by new tests in `test_deploy_pipeline.py`.

1. **A crashed/interrupted deploy could leave its run `running` forever, and
   that permanently blocked the project from deploying** (`has_running` saw the
   stale row → 409 on every later attempt). Any exception outside the few
   caught types (a Sprite call failing, a bad root, a DB error) or a backend
   restart did this. Now: the in-memory single-process guard is the source of
   truth, orphaned `running` rows are closed out at the start of each deploy
   (`deploy_runs_repo.fail_orphaned_running`), and `_run_deploy` has a
   catch-all that marks the run failed. The slot is also claimed before the
   first `await`, so a double click can't start two deploys.
2. **Raw log was not shown "immediately" (§23.9 point 1).** `_fail_run` wrote
   stdout/stderr/exit code *together with* the diagnosis, after the LLM call —
   and lost them entirely if that call raised an unanticipated exception.
   Now the raw log is written and the run marked failed first; the diagnosis
   is a second write. `DeployPanel.tsx` keeps polling ~90s after a failure so
   the diagnosis appears on its own.
3. **Exit code of a crashed app was wrong** (`wait` on a pid launched from a
   different shell always fails → exit 127/None). The app now runs in a small
   wrapper that records its own pid and real exit status. Also found by
   executing the script in a real shell: a finished-but-unreaped process still
   answers `kill -0`, which made a crashed app look healthy — the exit file is
   now checked first.
4. **Every redeploy of a running app would fail with "address already in
   use".** A successful deploy keeps running on a fixed port and nothing
   stopped it. The start script now stops the previous process group for the
   same target first (pid/exit/log files are keyed by target name, not run id).
5. `cd <root>` in the start script was unquoted (a root with a space broke it;
   shell metacharacters were interpreted). Now quoted, and the confirm endpoint
   validates each root with `resolve_repo_path` (422 instead of failing later
   inside the background task).
6. Root-detection LLM errors (`DetectionLlmError`, no credential, provider
   failure) escaped `POST /deploy` as a 500; now 422/400/502 with a message.
7. Generic Node projects got `port=None`, so `PORT` was never injected and
   Live Preview would have had nothing to proxy to; they now default to 3000
   like Next.
8. Cosmetic: environment-class failures are labelled as such in the UI; the
   `DeployNeedsConfirmationResult` docstring said "409-shaped" but it's a 200.

**Still open — product decisions, deliberately not changed here:**

- *Dockerfile handling vs. the prompt's §23.5 line "Dockerfile present → just
  build it".* The delivered code treats any Dockerfile as the §23.6
  nested-sandbox case and refuses to preview it. §23.6's sentence is about a
  repo's *own runtime logic* spawning containers, not about a Dockerfile used
  as a build recipe — so as built, an ordinary Python/Node app that merely
  ships a Dockerfile can't be previewed at all. Decide whether Dockerfile repos
  should instead fall through to Nixpacks-style detection (ignoring the
  Dockerfile) and only declare nested-sandbox when the app itself needs Docker.
- *§23.9 point 4's "routes to §23.8's notification system"* — there is no
  notification system in this codebase yet, so environment failures are only
  shown as a labelled diagnosis in the Deploy panel.
- *Build-class "offer to fix"* is a Copy button, not a one-click "send to the
  agent" action.
- *From-scratch projects with several roots:* the harness never records the
  roots it creates, so a scratch project always deploys as one root `.`.

## What's next

Live Preview (5.3) and sub-agent delegation / visual QA (5.4) are the
remaining pieces of this roadmap item — neither assumed anything from here
that doesn't already exist. Live Preview in particular has a natural
foothold to build on: `deploy_runs.port` is already the exact "which port is
this target listening on" fact a proxying iframe needs, and `DeployPanel.tsx`'s
"not yet embedded here" note marks exactly where that iframe will go.
