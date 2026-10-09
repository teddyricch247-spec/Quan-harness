# AGENTS.md — must read before touching deploy/infra

This file exists so any AI agent (or human) picking this repo back up has the
current, real state of the deployment — not the state described in older
docs. If something here conflicts with docs/DEPLOYMENT.md or
docs/YOUR_SETUP_CHECKLIST.md, this file wins; update those docs to match
reality when you get a chance, don't trust them blindly.

## Live infra (as of 2026-09-25)

- **Frontend:** Vercel project `quan-harness` → `frontend/` — https://quan-harness-teddyricch247-specs-projects.vercel.app
- **Backend:** Render web service `Quan-harness` (Python) → `backend/` — https://quan-harness.onrender.com
- **Database/Auth:** Supabase project `quan-harness` (`skyykzpamsvfjnnbcgjn.supabase.co`, eu-west-1). Migrations `0001` through `0011_preview.sql` are all applied as of 2026-10-02 (`0011` was dry-run in a rolled-back transaction first, then applied and verified against the live schema) — confirmed against `information_schema.columns`/`pg_policies`, not assumed. `0009` (Phase 4.5) was dry-run first (the full DDL plus explicit positive/negative tests of both new CHECK constraints, the `sessions.trigger` default, and `schedule_id`'s `ON DELETE SET NULL` behavior, all inside a transaction that was rolled back) before being applied for real via the Supabase MCP connector. `0010_deploy_pipeline.sql` (Phase 5.1/5.2/5.5) was applied and verified on 2026-09-29 (schema, constraints, RLS and cascade all checked against the live project) — see `db/migrations/README.md`.
- The previous Render service, Vercel env vars, and Supabase project (an older, schema-incompatible "harness" project) were all deleted and recreated from scratch on 2026-09-20/21. Don't trust anything in chat history or docs dated before that as still being live.

## Most recent change: Ling 3.1 Flash quick-connect + native thinking controls (2026-10-08)

Full writeup, including everything **not** verified: `docs/LING_THINKING_NOTES.md`. Headline:

1. `provider_catalog.py` gained `QUICK_MODELS` (one-tap "paste only your key" connections — first
   entry: OpenRouter `inclusionai/ling-3.1-flash`, free) and `ReasoningProfile`/`MODEL_REASONING`
   (the native thinking levels per model). New endpoint `GET /connections/llm-credentials/quick-models`.
2. Per-credential thinking config in `llm_credentials.reasoning` (jsonb); sent as OpenRouter's
   unified `reasoning` object via litellm `extra_body`; a rejected level falls back to the model
   default once instead of failing the turn.
3. Migration `0013_llm_reasoning_config.sql`. **The live Supabase history has migrations that are not
   in this repo** (`0012_workspace_fingerprint`, `session_attachments`, `rls_cross_reference_checks`,
   `rls_audit`, `phase6_advisor_fixes`) — check `list_migrations` before assuming this folder is the
   whole story.
4. Not done: storing/showing the thinking text in a session (see the notes doc for the patch).

## Previous change: BYOK provider presets (2026-10-08)

**What changed:** connecting an LLM key is now preset-driven instead of "pick one of five
and hand-type the model ID and base URL".

1. `backend/app/services/provider_catalog.py` is the **single source of truth** for providers
   (OpenRouter, Anthropic, OpenAI, Google, Groq, Together, Fireworks, DeepSeek, Mistral, xAI,
   Cerebras, Custom). `llm_client._litellm_model_string` reads its prefix from there; the
   frontend fetches the list from `GET /connections/llm-credentials/providers`.
2. `provider_probe.py` + `POST /connections/llm-credentials/probe` (and `/{id}/probe` for a saved
   key) check a key against the provider's own model-list endpoint and return the models, with a
   per-model `supports_tools` flag where the provider reports it. A probe is advice, never a gate.
3. Migration `0012_llm_provider_presets.sql` widens the provider CHECK. **Applied and verified on
   the live Supabase project 2026-10-08.**
4. `tests/test_provider_catalog.py` fails if the catalog, `schemas.LlmProvider` and the latest
   migration's CHECK drift — adding a provider means touching all three (see the catalog's docstring).

**Not run / flagged:** nothing here has been exercised against a live key of every provider
(no network in the build environment) — endpoint URLs and key-prefix hints come from provider docs.
`create_credential` and `call_llm` don't SSRF-guard a saved custom `base_url` (only the new probe
does); that predates this change. The Render backend must be redeployed for the new endpoints.

## Previous change: Phase 5.3/5.4 Preview Compute & Known Preview Limitations (2026-10-02)

**What changed:** see `docs/PHASE5_3_5_4_NOTES.md` for the full writeup, including the
**list of live checks that could not be run** (no `FLY_API_TOKEN` yet) and an honest
statement of what "the agent cannot read preview secrets" does and doesn't guarantee.
The headline items:

1. New migration `0011_preview.sql` — immutable/unique `projects.preview_subdomain`,
   `preview_secrets`, `project_notifications`, `deploy_runs.environment_kind`.
   **Dry-run (25 assertions, rolled back), applied, and verified on the live Supabase
   project on 2026-10-02.**
2. The deployed app now runs as a **Sprite service**, not a detached `nohup` — a
   Sprite's RAM doesn't persist across hibernation, so the old launcher died ~30s
   after every deploy. (`preview_runtime.py`)
3. A **host-routed ASGI proxy** (`preview_proxy.py`) serves each project at
   `<subdomain>.<PREVIEW_BASE_DOMAIN>`: single-use enter token → session cookie,
   streaming, cold-start retry, WebSocket relay, and hard caps on how long any
   connection can stay open (an open connection keeps a Sprite billed). Needs
   `PREVIEW_BASE_DOMAIN` + `PREVIEW_SIGNING_SECRET`; blank = preview off, and the UI
   says so.
4. **Preview secrets** (`preview_secrets`) are deliberately a *different table* from
   `project_secrets`: those are agent-usable, these must never be. Redacted at
   `agent_loop._execute_call` (fails closed), in stored deploy logs, and in the
   diagnosis prompt. `test_preview_secret_isolation.py` has static tests that fail if
   anything agent-facing ever touches them.
5. **§23.8 notifications** (CORS / secrets / OAuth / database / needs-Docker), all
   notify-only and opt-in, plus 5.5's "environment failures route to notifications".
6. Fixes to earlier phases found en route: a **Dockerfile no longer blocks a
   project** (§23.6 is about commands invoking Docker, not a file existing — this
   *reverses* what 5.1 did), and the scan script no longer glues a section marker
   onto a file with no trailing newline (it was silently breaking pnpm/yarn
   detection).

**If you're an agent about to touch the proxy, the pipeline's start step, or anything
that handles preview secrets:** read `docs/PHASE5_3_5_4_NOTES.md`'s "Design decisions"
first. In particular don't (a) reuse `project_secrets` for preview secrets, (b) put an
env value into a command line, (c) go back to `nohup`, (d) add `url_settings=public`
anywhere, or (e) let any connection through the proxy stay open indefinitely.

**Not fixed, flagged:** `execute_bash` computes an env dict of agent-usable secrets
but never passes it to the exec call (`shell_tools.py`) — Phase 2, unrelated to
preview, and fixing it changes agent-visible behaviour. See the notes.

## Previous change: Phase 5.1/5.2/5.5 Deploy Pipeline, Monorepos & Failure Handling (2026-09-29)

**What changed:** see `docs/PHASE5_1_5_2_5_5_NOTES.md` for the full writeup.
The headline items:

1. New migration `0010_deploy_pipeline.sql` — a `deploy_runs` table, plus
   `repo_origin`/`deploy_targets_confirmed` columns on `projects`. **Applied
   and verified on the live Supabase project on 2026-09-29** (see
   `db/migrations/README.md`).
2. A real deploy pipeline (`app/services/deploy_pipeline.py`): stack
   detection (Nixpacks' own rule order, with a tool-less LLM call as
   fallback), monorepo root detection/confirmation for imported repos only,
   and a two-phase build-then-start execution against the project's
   workspace, with raw stdout/stderr/exit code captured either way. Same
   async-background-task-plus-pub/sub shape as `agent_loop.py`'s turn loop.
3. Deploy failure diagnosis (`app/services/deploy_diagnosis.py`): a second
   tool-less LLM call that turns a raw failure log into a plain-language
   diagnosis, classified as `build` (the agent's own code — an "offer to
   fix" affordance is safe) or `environment` (not a code bug — secrets,
   CORS, an unreachable database — "fix" framing is never used, enforced in
   code regardless of what the model itself returns). Attached to the
   project's next agent turn as read-only context via a new
   `DEPLOY_DIAGNOSIS` system-prompt section — informational only, never
   auto-applied.
4. ~~A Dockerfile in a repo is now a deterministic, pre-build nested-sandboxing
   case.~~ **Superseded in Phase 5.3:** a Dockerfile merely existing no longer blocks
   anything; nested-container support is declared only when a build/run command
   invokes Docker or the daemon is unavailable. See `docs/PHASE5_3_5_4_NOTES.md`.
5. Found and fixed a real, live bug while auditing `exec_in_workspace`'s
   callers: `guard_rules.py`'s duplicated `REPO_ROOT` literal was still the
   Fly Machines-era `/workspace/repo` path, silently mismatched against
   `workspace_paths.py`'s own (correct, current) `/home/sprite/repo` since
   the Sprites port. Fixed; see `docs/PHASE5_1_5_2_5_5_NOTES.md`.

**If you're an agent about to touch `deploy_pipeline.py`, the monorepo
confirmation flow, or `guard_rules.py`'s `REPO_ROOT` again:** read
`docs/PHASE5_1_5_2_5_5_NOTES.md` first — specifically the "Design decisions
the sub-prompt's own text doesn't spell out" section (the Dockerfile
handling, the `repo_origin`-based confirmation gate, and the BACKEND_URL
heuristic are all easy to "simplify" back into something that quietly
breaks one of these) and the "Gap found while auditing" note on
`guard_rules.py`.

## Previous change: Phase 4.5 Scheduling / Proactive Scanning (2026-09-25)

**What changed:** see `docs/PHASE4_5_NOTES.md` for the full writeup. The
headline items:

1. New migration `0009_scheduling.sql` — a `project_schedules` table, plus
   `trigger`/`schedule_id` columns on `sessions`. Dry-run verified, then
   applied to the live Supabase project on 2026-09-27 (see the Live infra
   note above).
2. A new in-process background loop (`app/services/scheduler.py`, started
   from `main.py`'s new lifespan handler) that starts a real session for any
   due `project_schedules` row, through the exact same `agent_loop.start_turn`
   an interactive message goes through. No separate Render Cron Job or
   worker service — there isn't a second service to point one at (this is
   still one Render web service) — so a schedule can't fire while this
   single free-tier instance is asleep. See `docs/PHASE4_5_NOTES.md`'s rough
   edges section for what that actually means and how to fix it if it
   matters.
3. `agent_loop.py`'s permission resolution (`_resolve_permission_for_call`)
   gained a `force_ask` path: on a session whose `trigger == 'scheduled'`,
   every mutating tool call — native tools included, which normally have no
   Ask concept at all — is gated behind an approval request, regardless of
   the project's configured Auto/Ask/Off states. `_action_resolved_approval`
   correspondingly gained a `scheduled_tool:` branch, including a genuinely
   new shape: an approved scheduled `execute_bash` call can itself still
   trip the heuristic guard on execution, producing a second, nested
   approval. Read `docs/PHASE4_5_NOTES.md`'s "Nested approvals" section
   before touching either function again.

**If you're an agent about to touch `agent_loop.py`'s mutating-call branch,
`_action_resolved_approval`, or `scheduler.py` again:** read
`docs/PHASE4_5_NOTES.md` first, specifically the "Nested approvals" and
"single-process only" notes — both are easy to silently break by
"simplifying" the code back toward what it looked like before this pass.

## Known gaps, intentionally left open

- `SUPABASE_SERVICE_ROLE_KEY` is set on Render with a real value; `GITHUB_OAUTH_CLIENT_ID`/`GITHUB_OAUTH_CLIENT_SECRET` and `FLY_API_TOKEN`/`FLY_ORG_SLUG` are still blank — by design, not an oversight. GitHub OAuth App creation and Fly.io org setup are pending on the human side. The app works without them; only the "Connect GitHub" one-click flow and the sandboxed preview/deploy workspace feature are unavailable until they're filled in. A blank `FLY_API_TOKEN` specifically means a freshly-imported project's automatic first Pull (Phase 4.4) will fail with a workspace-provisioning error — expected, not a regression; the project itself is still created correctly, and re-running Pull once Fly/Sprites credentials exist picks up where it left off. The same blank token is why the Phase 5.1/5.2/5.5 deploy pipeline — code-complete as of this phase — hasn't actually been exercised against a real Sprite yet either; see `docs/PHASE5_1_5_2_5_5_NOTES.md`'s rough-edges section.
- GitHub credential strategy is OAuth App (not MCP) for the Push/Pull sync mechanism specifically (`github_credentials`, `github_oauth.py`) — this was explicitly decided after initially considering MCP-based push/pull for users: MCP tools are single-file, non-atomic, and would put git-write credentials inside the same tool surface the coding agent uses, which conflicts with this project's own architecture decision that the agent must never hold push/pull credentials. This is a *separate* thing from GitHub-as-a-connector (`mcp_servers`, GitHub's own real remote MCP server at `api.githubcopilot.com/mcp`, wired up like any other connector via `routers/connectors.py`) — that path is read/action-oriented agent tool access (list issues, check PR status, and so on), gated per-tool by the usual On/Off/Ask permissioning, and was never a candidate for holding push/pull credentials in the first place. Phase 4.3 is what made connecting it via real OAuth actually possible; see the Phase 4.3/4.4 entry above.
