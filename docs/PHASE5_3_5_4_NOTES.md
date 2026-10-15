# Phase 5.3 + 5.4 — Preview compute (Fly.io Sprites) & known preview limitations

Spec: §23.7 (preview compute) and §23.8 (known limitations). Migration:
`db/migrations/0011_preview.sql` — **applied to the live `quan-harness` Supabase
project and verified** (see "What was verified" below).

> **Read this first if you're about to touch the preview proxy, the deploy
> pipeline's start step, or anything that handles preview secrets.** Several
> choices here look like they could be "simplified" and would quietly break
> something. They're listed under "Design decisions".

## What was built

| Area | Where |
|---|---|
| App runs as a **Sprite service** (survives hibernation), one entry target exposed | `services/preview_runtime.py`, `workspace_service.py` (`create_or_replace_service`, `stop_service`, `get_sprite_info`, `refresh_billing_state`), `deploy_pipeline.py` |
| **Proxy**: per-project stable subdomain, host-routed ASGI gateway, auth, streaming, cold-start retry, WebSocket relay, billing cut-offs | `services/preview_proxy.py`, `preview_rules.py`, `preview_tokens.py`, `main.py` |
| Stable **preview subdomain** per project (immutable, unique, DNS-safe) | `0011_preview.sql`, `projects` repo, `routers/projects.py` |
| **Secrets panel** (preview-only, never visible to the agent) | `repositories/preview_secrets.py`, `preview_secrets_service.py`, `secret_redaction.py`, `routers/preview.py`, `components/PreviewSecretsPanel.tsx` |
| **CORS / OAuth / DB / secrets / Docker notifications**, all notify-only | `preview_limitations.py` (pure), `preview_notifications.py`, `repositories/notifications.py`, `components/PreviewNotices.tsx` |
| Billing states (`running`/`warm`/`cold`), read without waking the Sprite | `workspace_service.refresh_billing_state`, `PreviewPanel.tsx` |
| Frontend: Live Preview panel, Secrets, Notices | `frontend/components/Preview*.tsx`, `app/projects/[id]/page.tsx` |

**Tests added/changed:** `test_preview_rules` (33), `test_preview_tokens` (10),
`test_preview_limitations` (21), `test_preview_proxy` (33), `test_preview_runtime`
(36), `test_preview_secret_isolation` (23), `test_secret_redaction` (8), plus
changes to `test_deploy_pipeline` (17 → 29), `test_deploy_detection` (30 → 31),
`test_deploy_diagnosis` (13 → 17), `test_agent_loop_audit` (harness only). Full suite:
558 pass; the 8 that don't are pre-existing artifacts of the offline runner
(see "How the tests were run").

## Problems found in earlier phases while building this (and fixed)

These were in 5.1/5.2/5.5's territory and directly blocked 5.3/5.4, so they were
fixed rather than worked around. None were searched for; each surfaced while
reading code or docs the new work depends on.

1. **The app would die ~30s after every deploy.** 5.1 started the app with a
   detached `nohup … &`. Per the Sprites docs, a Sprite's RAM doesn't persist:
   *running processes stop when it hibernates* and only the disk survives. So a
   person opening the preview a minute later would hit a Sprite that woke up with
   nothing listening. Fixed by running the app as a **Sprite service** (the
   platform's own mechanism: restarted on wake, can declare `http_port`). The
   health probe is unchanged (still "alive after a few seconds", still checks the
   exit file before `kill -0`).
2. **A Dockerfile in a repo made the whole project un-previewable.** 5.1 treated
   *any* Dockerfile as "nested container support needed" and refused to build.
   §23.6's actual wording is about "the repo's own logic *tries to spin up* its own
   Docker", i.e. the build/run **commands**, not a file existing. A Next.js app
   that ships a Dockerfile for production could never be previewed. Now: a
   Dockerfile is ignored by detection; nested-container is declared only when a
   detected build/run command invokes docker/podman, or a log shows the Docker
   daemon being unavailable. The fallback LLM is told Docker doesn't exist.
   *This reverses a decision `PHASE5_1_5_2_5_5_NOTES.md` flagged as open*; the
   reasoning is in `deploy_pipeline.py`'s docstring.
3. **`cat package.json` without a trailing newline swallowed the next section.**
   The scan script `cat`s files then prints the next `@@MARKER@@`; with no final
   newline the marker was glued onto the last line and never parsed. For
   `package.json` that lost the pnpm/yarn lockfile flags and the file listing, so
   a pnpm project would silently be built with npm. Found because the same bug
   would have hit the `.env.example` capture I was adding. Fixed (and a regression
   test runs the real script in bash).
4. **§23.9 point 4's "environment failures route to the notification system"** was
   left open in 5.5 because nothing existed to route to. It's now wired:
   environment-class failures are classified into a §23.8 kind and raised as a
   notification. A Docker-daemon failure is recognised deterministically (no LLM
   call); otherwise the diagnosis model supplies `environment_kind`, with a pure
   regex classifier as the fallback when no model is available.

### Found but deliberately NOT changed

- **`execute_bash` builds an `env` dict of the project's agent-usable secrets but
  never passes it to the exec call** (`shell_tools.py`: the comment says "inline
  export statements", the code doesn't do it). So the §14.3 "`$NAME` in a command
  is exported" feature doesn't actually work today. It's Phase 2, it's unrelated to
  preview, and fixing it *turns on* agent-visible secret injection, which is a
  behaviour change on a security-sensitive path I wasn't asked to touch. Flagging
  rather than silently changing.
- Your earlier notes number these phases differently (they call 5.3 "Live Preview"
  and 5.4 "sub-agent delegation / visual QA"). I followed this prompt's numbering.
  Sub-agent delegation and visual QA are **not** part of this work.

## Design decisions the prompt doesn't spell out

**Preview secrets are a different table from `project_secrets`.** §23.8 names
`project_secrets`, but that table is the *agent-usable* store: its names go into
the agent's system prompt and its values are exported into `execute_bash`
(§14.3). §23.8/§23.10 require the opposite for preview secrets ("the agent cannot
read or use these values"). Two opposite visibility contracts can't share a table
without a filter every future reader must remember, so `preview_secrets` is
separate: no existing agent code path can reach it. A static test
(`test_preview_secret_isolation`) fails if anything agent-facing ever imports it.

**Subdomain-per-project, not a path prefix.** The previewed app has to be served
from the *root* of its own origin or every root-absolute asset path (`/_next/…`,
`/assets/…`) breaks. That's also what makes §23.8's CORS fix ("allowlist one
origin once") possible. The cost is a wildcard DNS record + wildcard custom domain
(see `YOUR_SETUP_CHECKLIST.md` §3b). With no domain configured the UI says plainly
that preview isn't set up rather than rendering a broken iframe.

**Wildcard DNS points at the same backend as the API**, so a host under the
preview domain is handled by the proxy **only** — a malformed one (`a.b.<base>`)
gets a 404 from the proxy and never reaches an API route (tri-state
`classify_host`, tested).

**Auth without a bearer header.** An iframe navigation can't send
`Authorization`. Flow: signed-in owner → `POST /preview/session` → single-use,
60-second token in the iframe URL → proxy burns it, sets a host-only HttpOnly
session cookie → every later request (including WebSocket upgrades) uses the
cookie. Tokens are bound to project + subdomain; HS256 with a dedicated
`PREVIEW_SIGNING_SECRET` (not the Supabase JWT secret).

**What the proxy rewrites, and why** (all in `preview_rules.py`, all tested):
`Authorization` is replaced with the Sprites token; `X-Frame-Options`/CSP
`frame-ancestors` are replaced so only the harness frontend can embed the preview;
`Set-Cookie Domain=` is stripped (an app can't plant cookies on sibling previews)
and cookies are rewritten to `Secure; SameSite=None; Partitioned` because the
preview always sits in a cross-site iframe where Lax/Strict cookies silently
break every cookie-session app; `Location` headers pointing at the Sprite's
internal host are rewritten so the internal URL never leaks.

**Billing guard (§23.7 "the one thing to get right").** An open TCP connection
keeps a Sprite awake. So: no keep-alive pool to the Sprite; one response is cut
off after 5 min; a WebSocket closes after 90s of silence and 15 min total; the
frontend unloads the iframe when the tab has been hidden 60s; status polling reads
Sprites *metadata* (not the Sprite's URL) and only while the tab is visible. No
idle timer was built — the platform does that.

**"Checkpointing" — what it means here, and what was not built.** The prompt's
"automatic filesystem checkpointing (sleep/restore without losing state)" is the
Sprite platform's own disk persistence: nothing to provision or call. This work
*depends* on it — build output (`node_modules`, `.next`, …) survives hibernation, so
waking the preview only has to re-run the start command, never rebuild
(`preview_runtime.restart_all` relies on exactly that). I did **not** integrate the
Sprites explicit-checkpoint API, and nothing in the preview path calls it. It is also
unrelated to the harness's own §23.4 checkpoints, which are git commits made after
every file edit (`checkpoints.py`). One interaction worth knowing: restoring one of
those git checkpoints changes files under a *running* app, which keeps running its old
code until the person restarts it (the Restart button, or the next deploy).

**Cold start.** A request that wakes a Sprite gets 502 until the service is up.
GET/HEAD are retried with backoff up to 30s — but **only if no request has
succeeded in the last 20s**, so a *running* app's own 502 is never delayed. After
that, a self-refreshing "still starting" page.

**Entry target.** A Sprite's URL routes to one port. For a monorepo that's the
frontend (conventional names first, else the first non-backend); only that target
gets `http_port`. The backend stays reachable inside the Sprite via the existing
`BACKEND_URL` injection.

**Secrets are runtime-only, and harness-managed variables win.** They go into the
service's `env`, not the build step. A secret named `PORT`/`BACKEND_URL` is
rejected at the API and would be overridden anyway.

**CORS "proxy server-side" option was not built.** §23.8 offers it as an
alternative to the stable-origin allowlist. Building it means an authenticated
relay to arbitrary configured upstreams (an SSRF surface) *and* still requires the
app to be pointed at the relay path. I built the allowlist path fully, and the CORS
guidance also tells people to make their app call the API from its own server.

## What "the agent cannot read these values" does and doesn't mean

Be precise about this, because it's the easiest claim here to overstate.

**Enforced by the harness (hard guarantees, tested):**
the values live in a store no agent tool can query; they're never returned by any
API; they reach the app only through the Sprite service's `env` (proven in a real
shell: in no process's argv); every tool result is redacted at the one chokepoint
(`_execute_call`) *before* the transcript, the model, or the audit row sees it —
failing **closed** if the secret set can't be loaded; stored deploy logs and the
diagnosis prompt are redacted too; an SDK error that echoes the request body is
scrubbed.

**Speed bumps, not walls:** the guard now also gates `sprite-env` and BSD-style
`ps e…`, on top of the existing rules that already gate `sudo`, `..`, and any
absolute path outside the workspace (so `cat /proc/*/environ` already needed
approval).

**Not guaranteed, and can't be from inside the harness:** the agent and the app
run as the **same Linux user in the same VM**. A determined agent could write app
code that prints `process.env` somewhere it can read, or re-encode a value (hex,
reversed) to slip past exact-match redaction. Also, a service's `env` is
persisted in the Sprite's service definition on its disk — whether that's readable
from inside the Sprite is **unverified** (Live check 10). If it is, the only things
between the agent and the value are the guard and the redaction. That's a real but
much narrower exposure than "the model can see secrets", and it's why the tests
assert *structure* (nothing agent-facing can obtain a value) rather than only
behaviour.

## What was verified, and what could not be

**Verified:** 558 tests pass (offline); the type-check of every frontend file I
touched passes (against ambient stubs — see below); the secret-in-argv guarantee
and the service wrapper/probe were run in a **real local bash**; and the migration
was dry-run (25 assertions, rolled back, confirmed no residue), applied, then
verified against the live schema (tables, RLS, policies, constraints, indexes,
trigger, column). Several tests were also *mutation-checked* (I broke the
behaviour on purpose and confirmed the test failed): the warm/cold retry logic, the
auth gate, secret-in-argv, and the structural isolation invariants.

**Not verified — no `FLY_API_TOKEN` is configured, so nothing here has touched a
real Sprite.** Run these first; each takes a few minutes and turns an assumption
into a fact:

1. `create_service(..., http_port=N)` actually routes the Sprite's URL to port N.
2. A service **comes back after hibernation** (deploy → wait ~60s → hit the
   preview → it answers). This is the whole point of the Services change.
3. `get_sprite(name)` exposes `.url`, `.status`, and `.url_settings.auth` (read
   defensively via `getattr`; a different shape degrades to "preview unavailable",
   not a crash).
4. The **async** client's `create_service` returns something `_drain` can read
   (it accepts async *or* sync iterables) and has `stop_service`.
5. A new Sprite's URL really is `sprite`-auth (bearer-gated). The code refuses to
   proxy one that reports `public`, but it doesn't *set* auth at creation (the
   async `create_sprite(url_settings=…)` signature was unverifiable).
6. The Sprite edge doesn't strip `X-Forwarded-Host`/`-Proto` (apps like Next.js
   server actions compare Origin to it).
7. **Billing dry run** (below).
8. `websockets` connect kwarg: `additional_headers` (≥14) vs `extra_headers` (≤13);
   there's a `TypeError` fallback, but it has never run against the real library.
9. Wildcard DNS + TLS on Render, and **cookies in Safari / Chrome / Firefox** with
   `SameSite=None; Partitioned` in a cross-site iframe. The most robust setup is
   serving the frontend on the **same registrable domain** as the preview domain.
10. From inside a Sprite: can `sprite-env services get <name>` (or a file under
    the Sprite's service registry) show the service `env`? Decides how much the
    guard+redaction layers are actually carrying.
11. WebSockets survive Render's edge (Cloudflare) for the iframe origin.
12. `create_service`'s service log location isn't relied on (the wrapper logs to
    `/tmp/qh-deploy-<slug>.log` itself), but confirm the service really restarts a
    crashing app (the harness stops it after a failed probe).

### Cost / billing dry run (§23.7: "the step most worth a real dry run")

Using the prompt's rates (CPU ≈ $0.07/hr, RAM ≈ $0.04375/GB-hr, hot storage
≈ $0.50/GB-month, cold ≈ $0.02/GB-month, bandwidth unmetered), an **upper bound**
for a 1 CPU + 1 GB Sprite billed on wall-clock while `running` is
≈ **$0.114/hr ≈ $0.002 per minute**. Whether Sprites bill allocation or actual
usage wasn't verifiable here — if it's usage, real cost is lower. A short preview
session (a minute or two) is therefore a few tenths of a cent at most.

To check it for real:
1. Open the preview, then **close it** (or hide the tab). Within ~30–60s the
   badge should go `running → warm`. If it stays `running`, something is holding a
   connection open — check for WebSockets/SSE in the previewed app first.
2. Open a page with a WebSocket and leave the tab **visible and idle**: the socket
   should close at ~90s and the Sprite should settle to `warm`.
3. Leave a preview open in a **hidden tab**: after ~60s the iframe unloads
   ("Paused while this tab was in the background").
4. Compare the Fly dashboard's billed usage for the Sprite against the above.

## How the tests were run

The sandbox this was built in has no `pytest`, `pydantic`, `fastapi`, `httpx`,
`supabase` or `sprites` and no network. I ran the suite with a small stub-based
runner (not in the repo) that installs stand-ins for the missing packages and
executes every `test_*` function. Eight pre-existing tests fail under that runner
for reasons that are artifacts of it (a `MagicMock` croniter, no `tmp_path`
fixture, no real `httpx` response objects) and were failing identically before any
change. **Run the real `pytest` in CI** — it's the authoritative result. One
real-pytest difference I checked rather than assumed: `backend/tests/` is a
package (`__init__.py`), so a sibling test import must be `from tests.test_x import …`.

Likewise the frontend was type-checked against minimal ambient stubs for
React/Next (no `node_modules` offline). That validates my props, API types and
null-handling, not the real React typings — run `npm run build` for the real check.

## Files

**New (backend):** `app/services/{preview_proxy,preview_rules,preview_tokens,preview_runtime,preview_limitations,preview_notifications,preview_secrets_service,secret_redaction}.py`,
`app/repositories/{preview_secrets,notifications}.py`, `app/routers/preview.py`,
`tests/test_preview_*.py`. **New (frontend):** `components/Preview{Panel,SecretsPanel,Notices}.tsx`.
**New (db):** `0011_preview.sql`.
**Changed:** `config.py`, `main.py`, `models/schemas.py`, `workspace_service.py`,
`deploy_pipeline.py`, `deploy_detection.py`, `deploy_diagnosis.py`, `agent_loop.py`
(one redaction call), `shell_tools.py` (literal-value guard), `guard_rules.py`
(two rules), `routers/{projects,deploy}.py`, `repositories/projects.py`,
`requirements.txt` (+`websockets`), `.env.example`, `lib/types.ts`,
`DeployPanel.tsx`, `app/projects/[id]/page.tsx`.

The live migration history records `0011_preview` with the **same statements** as
`db/migrations/0011_preview.sql` but with the long header comments trimmed.

---

## Audit of 5.3 / 5.4 (post-delivery review)

Reviewed against `phase-5-chopped.md` §23.7 and §23.8: migration 0011 (also confirmed
applied on the live Supabase project: tables, RLS, indexes, the immutability trigger and
the `deploy_runs.environment_kind` column all match the file), preview gateway, runtime,
secrets isolation, notifications, routers and the frontend panels. Result: the delivered
work matches the spec; no functional gaps were found. Four small fixes were made:

1. `preview_proxy.py` — the upstream URL is built as `origin + path`. A request target not
   starting with `/` (e.g. `@evil.example/`) could change the host the Sprites API token is
   sent to. Such requests are now refused with a 400 before any upstream call.
   Test: `test_a_request_target_that_is_not_an_absolute_path_...`.
2. `guard_rules.py` — the `ps e` speed bump also blocked ordinary commands whose *argument*
   contained an `e` (`ps -u sprite`, `ps -C node`). Value-taking options' arguments are now
   skipped. Test: extended `test_ordinary_commands_are_not_caught_by_the_new_rules`.
3. `PreviewPanel.tsx` — the idle-unload timer called `setPausedForIdle` from inside a
   `setIframeUrl` updater function (updaters must be pure; React may run them twice). It now
   reads the current URL through a ref.
4. `tests/test_agent_loop_audit.py` — the fake connector result lacked `status_code`, which
   `agent_loop._execute_mcp` (Phase 4.3) reads; two tests failed with `AttributeError`.
   Test fake only; no production change.

Known limits, unchanged (see above): the agent shares a Sprite with the previewed app, so
the `/proc` / `ps e` / `sprite-env` guard is a speed bump rather than a sandbox boundary;
a stronger guarantee needs a second Sprite. Nothing here has run against a live Sprites
account — do the cost/billing dry run before shipping, as the spec asks.
