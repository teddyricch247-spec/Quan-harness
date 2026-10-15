# Phase 5.6 – 5.8 — security checklist, sub-agent delegation, agent self-verification

**Read this first: this is a reconstruction.** The original Phase 5.6–5.8 source was lost (it lived in a working copy that
was never pushed; see `docs/RECONCILIATION_NOTES.md`). On 2026-10-13 it was rebuilt from three things: the spec
(`phase-5-chopped.md`: §23.10, §14.8, §14.9), the *call sites* in the original `agent_loop.py` (which survived inside the
Phase 6 overlay and therefore pins the interfaces exactly), and the original's own notes. Behaviour was written to the spec
and to those interfaces; it is **not** byte-for-byte the original and it has **never run against a real Chromium, a real
Sprite or a real model** (this environment has none of them). What *was* tested is listed at the end, as is what wasn't.

## What is original and what is rewritten

| Original, recovered intact | Rewritten from the spec and the loop's call sites |
|---|---|
| `services/agent_loop.py` — all of the 5.6–5.8 wiring (delegation, browser lanes, per-turn budgets, approval round-trip, the Push/Pull gate, `preview_*`) | `services/sub_agent.py`, `services/turn_limits.py` |
| `services/data_flows.py`, `tests/test_data_flows.py` | `services/visual_qa.py`, `services/visual_qa_rules.py`, `services/workspace_fingerprint.py` |
| `services/message_builder.py` (screenshots + the exit-code fix), `routers/agent.py` | the tool schemas for the browser/preview tools, `tool_partition.group_into_lanes`, `system_prompt` VISUAL_QA section |
| the migration's *effect* (`0012`, read back from the live column) | `routers/data_flows.py`, the Push/Pull gate in `routers/workspace.py`, the fingerprint hook in `deploy_pipeline.py`, `tests/test_security_checklist.py` |

## 5.6 — Security principles checklist (§23.10)

The checklist is enforced by `tests/test_security_checklist.py`, which reads the code (import graph + AST) and fails on purpose
when a change alters the answer. Per bullet:

1. **Secrets only in the runtime environment.** `get_runtime_env` may only be called from the deploy path; the prompt/message/tool-schema
   modules never import a secret store. *Enforced.*
2. **The agent never holds a git-push credential.** Nothing reachable from the agent loop imports `git_sync`, `github_oauth` or the
   GitHub credential repository, nor any HTTP router; `git_sync.push/pull` are called only from the user-facing workspace/projects
   routers. On top of that, **Push and Pull refuse (409) while any turn runs on the project**, and claim the project's sync slot in the
   same synchronous step as that check; a turn that starts later waits for the slot (`agent_loop._wait_for_git_sync`) before it can run
   one tool. Reason: Push/Pull put the token on a `git` command line for the seconds they run, where a command the agent runs at the
   same moment could read it from the process table (and Pull's `git reset --hard` would clobber in-flight edits). *Enforced + gated.*
3. **No native credential or tool for any external platform.** No offered tool is named for push/pull/GitHub/token/credential/secret/
   OAuth/publish. *Enforced.*
4. **Short-lived, least-privilege tokens for the initial clone and Push/Pull.** **NOT MET.** The GitHub OAuth token is the broad,
   long-lived `repo`-scope token. Doing this properly means a GitHub App with installation tokens minted per operation — a design
   change, not something this reconstruction attempted.
5. **Be explicit about what leaves the workspace.** `GET /projects/{id}/data-flows` + the page behind *Project settings → What leaves
   this workspace*. The test fails if a new module can send text to a model, or the backend names a new external host, without
   `data_flows.py` being updated. *Enforced.*
6. **No component holds both "read arbitrary repo content" and "write to GitHub" in one tool-call surface.** Follows from 2 and 3 plus:
   every model call outside the agent loop is tool-less (`tools=[]`), checked by AST. *Enforced.*

## 5.7 — Sub-agent delegation (§14.8)

`delegate_task(task, max_iterations)` runs a scoped sub-session that shares the workspace and returns **one report**; the parent blocks
until it returns.

* The sub-session's messages are a local list — not a `sessions` row, no `session_events`. Only the report reaches the parent.
* Its tools: `view_file`, `execute_bash` (not on scheduled runs), and connector tools that are both side-effect-free and switched fully
  on. **No edit tool, no `delegate_task`, no browser/preview tool, no Ask-gated connector tool.** `execute_bash`'s description tells it
  to inspect only — but *nothing technical stops a shell redirect*; the command guard and the gate are the real protection (see below).
* **Never auto-resolves an Ask-gated action.** A tool call that needs approval ends the sub-session on the spot; the loop raises it on the
  *parent* as an ordinary approval card (with a marker of what the sub-task was and had found). The sub-session is never resumed; the
  eventual result is wrapped so the parent reads "the delegated sub-task stopped at an approval gate and the person approved/rejected
  it", not the bare output of a command it never ran.
* Own iteration ceiling: default 15, hard cap 30 (parent: 50). Context guard: it wraps up at 60% of the model's window. At its budget it
  makes one last tool-less call asking for a report from what it found, and the result says it is partial.
* Budgets per turn (counted from the durable log): 5 delegations, 3 preview rebuilds (`turn_limits.py`).
* Every tool call it makes goes through the loop's own `_execute_call`, so audit rows (marked "via delegate_task"), secret redaction and
  the command guard apply exactly as for the parent. No recursion: the loop refuses `delegate_task` inside a delegation.

## 5.8 — Agent self-verification (§14.9)

Five browser tools (`browser_navigate/click/type/screenshot/get_console_logs`) plus two this codebase names itself:
`preview_status` (read-only) and `preview_rebuild` (the same pipeline as the Deploy button; waits up to six minutes).

* **Offered only when** the operator enabled it, Playwright/Chromium can start, **and** the project's current model is *confirmed* to read
  images (`visual_qa.credential_supports_vision`: litellm's table or `AGENT_VISION_MODELS`; fails closed). Otherwise the model is told
  plainly that it has no browser this session and must not claim a visual check, and the person sees why. If a provider rejects an image,
  the browser stays off for the rest of the session.
* **A tool parameter is never a URL.** `browser_navigate` takes a path on the project's own preview.
* **Network-level wall.** Each browser context gets a dead proxy and a bypass list naming only the project's Sprite host, a short list of
  font/script CDNs, and `AGENT_BROWSER_ALLOWED_HOSTS`; `<-loopback>` removes Chromium's built-in exemption for `127.0.0.1`. Everything
  else — including *every hop of a redirect*, which Playwright route handlers are never called for — fails to connect. A route handler is
  a second layer. The Sprites token is attached only by that handler and only to the exact Sprite origin; never as a context-wide header.
* Service workers blocked, downloads refused, no permissions, TLS errors not ignored; at most three live pages (LRU), idle ones closed
  after ten minutes; every operation has a hard timeout; a Chromium that cannot start switches the feature off for five minutes.
* On an unattended (scheduled) run: no click/type and no rebuild; navigate/screenshot/console/status still work.
* Pixels live in an in-memory store (3 most recent screenshots per session, bounded sessions) and are re-attached to the model call as
  images; the transcript only records that a screenshot was taken. A restart loses them.
* **`preview_status` without comparing clocks:** each successful deploy records the git tree hash of the workspace (migration `0012`,
  `deploy_runs.workspace_fingerprint`), computed with a throwaway `GIT_INDEX_FILE` so the real index is never touched, excluding build
  output and dependency directories. `preview_status` recomputes it: equal → up to date, different → stale, missing → "can't tell" (never
  a guess). The hash is taken when the deploy *finishes*, so an edit made during the build is counted as already built — a small race, in
  the direction of saying "up to date".

## Not verified — do not skip

* **Playwright and Chromium have never run here.** The proxy-bypass semantics (`<-loopback>`, the dead proxy, `per-context`), the route
  handler, screenshots, and the container/system-library requirements are written from the documentation, not observed. **Test the wall
  first:** point a page at a host outside the list (and at `http://127.0.0.1:<port>`, and a redirect to each) and confirm `[blocked]`.
* **Does a Sprite's edge forward `Authorization` to the app inside it?** Unknown. Deploy a page that echoes its request headers and look.
  If it does, code in the previewed app can see the Sprites token.
* **No real model has run a delegation or a browser session.** The sub-agent loop is tested with a fake model; the agent loop's
  integration is tested only statically (`tests/test_agent_loop_contracts.py`: every name and parameter the loop uses exists) plus
  the original loop code itself. The 21-test wiring test for Phase 6 (`docs/phase6-pending/`) still needs its harness.
* **`deploy_pipeline` now runs one extra command after a successful deploy** (the fingerprint). Its test doubles were checked by reading,
  not by running; if a deploy test fails on a script count, that is why.
* The Push/Pull gate's HTTP layer (409s) was written but could not be exercised without FastAPI; the in-memory gates it uses are tested
  (`test_isolation_concurrency.py`).
* Bullet 4 above is not met.
* `requirements-browser.txt` pins `playwright==1.49.1` from memory; confirm it resolves and match `playwright install chromium` to it.

## What *was* tested

`test_security_checklist.py` (9, mutation-checked: re-introducing a push-credential import, a tool-bearing model call, a new egress host,
or a context-wide header each fails a test), `test_sub_agent.py` (19), `test_turn_limits.py` (4), `test_visual_qa_rules.py` (the allow-list
parser, the path rules, request filtering, console bounding, screenshot store), `test_workspace_fingerprint.py` (the script, run in a real
git: stable, content-sensitive, ignores build output, never touches the real index), `test_agent_loop_contracts.py` (4), the lane
grouping, and the restored `test_data_flows.py` / `test_isolation_concurrency.py`.
