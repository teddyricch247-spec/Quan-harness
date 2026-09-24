# Quan Harness — Phases 1-3 + 4.1-4.4

A hosted, multi-tenant web application that lets a signed-up person delegate
coding tasks to an AI agent with real access to their own codebase. This repo
now covers **Phases 1–3 of 9, plus Phase 4's Memory System, Project
Knowledge, Connector Integration, and Auto-Provisioning sub-prompts
(4.1–4.4)**, from the full roadmap:

- **Phase 1 — Foundations:** auth, connections, projects/sessions data model,
  platform operations. See `docs/PHASE1_NOTES.md`.
- **Phase 2 — Workspace Service & tools:** a real Fly.io-backed project
  workspace, the three structured file tools, checkpoints, Push/Pull, and
  `execute_bash`/`run_lint`/`run_tests`. See `docs/PHASE2_NOTES.md`.
- **Phase 3 — Turn loop & system prompt:** the agent orchestration loop, the
  full system prompt, per-turn context assembly, compaction, stuck detection,
  the Ask-gate approval flow, and the agent-facing HTTP surface
  (`/messages`, `/interrupt`, `/stream`, `/approvals`). See
  `docs/PHASE3_NOTES.md`.
- **Phase 4.1/4.2 — Memory & Project Knowledge:** the two-tier Memory System
  (`project_memory`/`build_user_memory`, auto-extracted after every
  completed or stuck turn) and Project Knowledge (short, human-authored,
  keyword/path-triggered notes), both now wired into the system prompt's
  `WHAT_YOU_KNOW_ABOUT_*`/`PROJECT_KNOWLEDGE` sections. See
  `docs/PHASE4_1_4_2_NOTES.md`.
- **Phase 4.3/4.4 — Connector Integration polish & Auto-Provisioning:** §9's
  account-level connect/review flow (OAuth, static token, per-tool
  Auto/Ask/Off, per-project grants) and §12's New Project flow were both
  already substantially built in Phase 1 — this pass exercised them against
  real-world cases rather than re-reading the spec, and fixed two real gaps
  it found: a pre-registered-OAuth-client path so GitHub's own remote MCP
  server (which doesn't support dynamic client registration) can actually be
  connected via real OAuth, an OAuth token refresh-and-retry path that didn't
  exist before, and an 'import an existing repository' setup mode that
  hardcoded "main" as the default branch and never actually pulled the
  repository's content into the workspace. See `docs/PHASE4_3_4_4_NOTES.md`.

There's now a real, running agent that also remembers: send a message to a
session and it plans, edits files, runs commands, asks for approval on
anything flagged, and — once the turn ends — quietly updates what it knows
about this project and about you, the same loop end to end. Connecting a
real external tool (GitHub's own MCP server included) and importing an
existing repository both now work the way their own UI copy already claimed
they did. What's still missing — scheduling (4.5), the deploy pipeline, Live
Preview, sub-agent delegation, visual QA, and beyond — is exactly what
`docs/PHASE4_1_4_2_NOTES.md`'s closing section hands off next.

## What's in here

```
db/migrations/     SQL migrations — run these first (db/migrations/README.md)
backend/           FastAPI orchestration backend
frontend/          Next.js (App Router) frontend
docs/              Setup, deployment, and phase-scope notes — start here
NOTICES.md         Third-party attribution — §29's licensing requirement
```

## Quick start (local dev)

1. **Database.** Create a Supabase project, then follow `docs/YOUR_SETUP_CHECKLIST.md`
   and `db/migrations/README.md` to run the eight migration files against it.

2. **Fly.io** (Phase 2 — powers every project's workspace). Create a
   **dedicated** Fly.io org and follow `docs/YOUR_SETUP_CHECKLIST.md` §3
   before trying Push/Pull or expecting a project's workspace to actually
   provision. Without this, importing an existing repository still creates
   the project and links the repo correctly (Phase 4.4) — only the automatic
   first Pull into the workspace fails, with a clear message telling you to
   retry it later.

3. **An LLM credential** (Phase 3 — powers the agent itself). Add at least
   one under Connections → LLM Providers once signed in: an API key for
   Anthropic, OpenAI, Google, OpenRouter, or a custom OpenAI-compatible
   endpoint. Set one as your account default, or pin one per project — see
   `docs/PHASE3_NOTES.md` if a session fails immediately with "no LLM
   credential."

4. **Backend.**
   ```bash
   cd backend
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in real values — see docs/YOUR_SETUP_CHECKLIST.md
   uvicorn app.main:app --reload
   ```
   Runs on http://localhost:8000. Visit `/docs` for the interactive API reference
   (FastAPI's built-in Swagger UI).

5. **Frontend.**
   ```bash
   cd frontend
   npm install
   cp .env.local.example .env.local   # fill in real values
   npm run dev
   ```
   Runs on http://localhost:3000.

6. Sign up, verify your email (check your inbox — Supabase sends the link), and
   you're in.

## Running the tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Phase 2's pure-logic tests plus Phase 3's own (`test_stuck_detector.py`,
`test_tool_partition.py`, `test_compaction.py`, `test_repo_map.py`,
`test_system_prompt.py`, `test_tool_schemas.py`, `test_crash_recovery.py`,
`test_message_builder.py`, `test_llm_client.py`, `test_agent_loop_audit.py`) need
nothing beyond `pytest` and the installed requirements — no database, network,
credentials or environment variables. (`test_repo_map.py` also shells out to
`bash`/`find`/`grep` against a temp directory, so run it on Linux/macOS.)
Phase 4.1/4.2 added 50 more pure-module tests (`test_memory.py`,
`test_project_knowledge.py`, plus additions to `test_system_prompt.py`).
Phase 4.3 added 6 more to `test_tool_schemas.py`, covering the new
`oauth_session_ref`/`oauth_client_secret_ref` threading through
`merge_mcp_tools` and `should_attempt_oauth_refresh`'s own decision logic —
**none of this suite, across any phase, has ever actually been run under
`pytest` in an environment this was built in** (none had `pytest` or network
access) — run it for real first, and treat any failure there as more
trustworthy than any pass/fail claim in these docs. See `docs/PHASE3_NOTES.md`.
`test_rls_isolation.py`, `test_workspace_integration.py` and
`test_push_pull_integration.py` need real Supabase/Fly.io/GitHub credentials
(`test_execute_bash_env_isolation.py` does not — it is pure). `agent_loop.py`'s tool dispatch and
approval-resume path are covered by `test_agent_loop_audit.py`; its turn loop
(`_run_inner`) — including Phase 4.3's new OAuth refresh-and-retry branch in
`_execute_mcp`/`_refresh_oauth_token` — `mcp_tools.py`, `mcp_oauth.py`, and
`routers/agent.py` have no automated coverage at all beyond manual review —
see each file's own docstring, `docs/PHASE3_NOTES.md`, and
`docs/PHASE4_3_4_4_NOTES.md` for exactly what's been run versus reasoned
through.

## Where to go next

- **`docs/YOUR_SETUP_CHECKLIST.md`** — everything that requires *you* to click
  something on an external site (Supabase, GitHub, Fly.io) before this runs at
  all.
- **`docs/DEPLOYMENT.md`** — putting the backend on Render and the frontend on
  Vercel, matching the spec's tech stack (§2).
- **`docs/PHASE1_NOTES.md`** / **`docs/PHASE2_NOTES.md`** / **`docs/PHASE3_NOTES.md`**
  / **`docs/PHASE4_1_4_2_NOTES.md`** / **`docs/PHASE4_3_4_4_NOTES.md`**
  — what's real, what's a documented rough edge, and what the next phase
  needs to pick up.
- **`NOTICES.md`** — third-party attribution per §29. Aider, OpenHands, and
  DeepSeek Harness are all filled in as of Phase 3.
