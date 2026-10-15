# Phase Convert — notes

The spec is `phase-convert.md` (the section numbers C1–C12 below refer to it). This file records what was
built, what was decided where the spec left a gap, and — most importantly — **what was not verified**.

## What changed

**Backend** (no migration — Convert adds none):

| | |
|---|---|
| `POST /projects` | Optional `prompt`. With one it creates project + first session + first turn in one call and answers `ProjectStartOut`; without, behaves exactly as before and answers `ProjectOut`. `name` is optional (derived — `services/project_naming.py`, deterministic, no LLM), as are both credential ids (account defaults). Errors carry `detail: {code, message}`: `email_not_verified`, `llm_key_required`, `github_not_connected`. An early-setup failure rolls the project back (`_roll_back_project`). |
| `GET /projects` | Adds `last_activity_at`, `status`, `repo_full_name`; most recently active first. One sessions query for the whole list. |
| `GET /attention` | New. `{code:{waiting_approval,failed}, chat:{…zeros}}` — `services/attention_rules.py`. |
| `POST /connections/github-credential/{id}/set-default` | New (mirror of the LLM one). |
| `ProjectOut.workspace_status/workspace_error` | New. `services/workspace_setup.py` starts provisioning at creation and remembers the outcome **in process only**. |

**Frontend:** new shell (`AppShell`, `Drawer`, `TopBar`, `TabSwitch`, `Sheet`, `PageFrame`), Code home
(`/projects`) as a prompt-first composer, the workspace (`/projects/[id]`) with Chat | Preview and the ⋯ menu
(Push, Pull, Checkpoints, Deploy, Secrets, Sessions, Rename → sheets), `/settings` hub. Deleted: `NavBar`,
`WorkspaceShell`, `WorkspaceSyncPanel`, `DeployPanel`, `PreviewSecretsPanel`, the `/projects/new` wizard, the
Sessions page, `/connections`. Redirects live in `next.config.js`.

> **Update 2026-10-13 (reconciliation):** both of the gaps below are closed. The transcript UI is `ChatPane` (kept),
> and image attachments (Phase 6.1) are wired into it — see `docs/RECONCILIATION_NOTES.md`. The text below is what was
> true when Convert was first built.

## Read this first: two things the spec assumes that this repository does not have

1. **There is no chat/transcript UI in this repo.** C10 says approvals, stop, send and the streaming transcript
   are the "Workspace chat pane (unchanged)". The uploaded frontend rendered a "not built yet" placeholder
   there, and `main` (7f1bc44) has no other branch. The live Supabase project *does* have Phase 6 migrations
   (`session_attachments`, `0012_workspace_fingerprint`, `rls_cross_reference_checks`, `rls_audit`,
   `phase6_advisor_fixes`) — so Phase 6 existed somewhere that was never synced here. `components/ChatPane.tsx`
   is therefore a new, plain implementation against the existing endpoints, behind a narrow prop interface, so
   the real pane can replace it. `lib/stream.ts` is its fetch-based SSE reader (EventSource can't send the
   Bearer token).
2. **Not built because the backend has no endpoint:** image attachments (C4 "Images only, as in Phase 6"), a
   Stop button (the loop can be *steered* via `/interrupt` — sending while running does that — not cancelled), and
   a GitHub repository *picker* (import takes a typed `owner/repo`).

## Decisions where the spec was silent

- **The first message is stored by `agent_loop.start_turn`**, which already appends the user message and spawns
  the turn. The endpoint therefore calls it directly rather than inserting the message itself; the agent loop is
  untouched. Consequence: if `start_turn` fails *before* appending, nothing is stored server-side, so the
  "Retry" row re-sends the prompt the client kept (sessionStorage hand-off), not a stored message.
- **`turn.status`** is `running | not_started | failed`. `not_started` = an import whose first pull failed: the
  project and session exist, the turn is held back, and Code home saves the typed prompt as the workspace draft.
- **LLM-key pre-flight** checks that a credential is *selected or a default exists* — it doesn't read the vault.
  A key that exists but is invalid still fails inside the turn, as an error row, as before.
- **"Failed" attention window:** a failed/stuck session counts for 24 h (`FAILED_WINDOW_HOURS`), because there is
  no "acknowledged" column and no migration. A new turn clears it sooner. Change the constant to change it.
- **`workspace_status` is process-local.** After a backend restart a project that never finished provisioning
  reads `idle`, not `failed`. "Retry setup" calls the existing `POST /projects/{id}/workspace/wake`.
- **No `NEXT_PUBLIC_NEW_SHELL` flag.** Every old page is replaced in this pass, so there is nothing to fall back
  to. `NEXT_PUBLIC_CHAT_ENABLED` (default off) hides the Chat | Code switch until Phase 7.
- **A created GitHub repository is not deleted** if setup fails afterward (the API can't take it back safely);
  the error message says so.
- **Project list order** changed to most-recently-active first (the only consumers are Code home and the drawer).
- **Scratch without a name or prompt is still a 422** ("no prompt → exactly as today"; `name` used to be
  required). Import / create-new-repo with no name are named after the repository instead.
- **Provisioning race:** the background provisioning at creation can overlap the agent's own first call. Both
  converge on the same Sprite (deterministic name, idempotent `git init`), but the conflict check inside
  `ensure_workspace` is substring-matching on the provider's error text — see `workspace_setup.py`.
- Defaulted GitHub credential is stored on the project row (`github_credential_id`), because pull/push read it
  from there.

## Verification — be precise about this

Built in a sandbox with **no network**: no `pip install`, no `npm install`, no `next build`, no live API calls.

| | Status |
|---|---|
| `project_naming`, `attention_rules` (24 tests) | **Run, pass** (plain Python; they import nothing from the app) |
| `lib/transcript.ts`, `lib/sse.ts`, `lib/errors.ts`, `lib/format.ts` | **Run, pass** (tsx) |
| All backend Python | `py_compile` clean |
| All frontend TS/TSX | `tsc --noEmit` clean **against hand-written stubs for React/Next/Supabase** — catches typos and wrong props/fields in our code; does **not** validate React/Next API usage |
| `tests/test_create_project_flow.py`, `tests/test_github_set_default.py` | **Written, compile, never executed** (need fastapi/pydantic/supabase) |
| Everything visual (shell, drawer, sheets, responsive layout, focus trap), the SSE reader against a real server, the one-call create against a real DB | **Not run.** Needs a browser and a deploy |

First things to do on a real machine: `pip install -r requirements-dev.txt && pytest backend/tests`,
`npm ci && npm run build`, then walk Flow A–C in a browser at 390 px and 1280 px.

## Rough edges / follow-ups

- `PATCH /projects/{id}` cannot clear `llm_credential_id` (`null` means "no change"), so Project settings'
  "Use account default" option silently does nothing. Pre-existing; Convert's model chip works around it by always
  sending an explicit id.
- The SSE stream holds one connection per open session; the server only closes it on a terminal status.
- Deploy runs still poll every 2 s (`useDeployRuns`); `lib/stream.ts` could carry `/deploy/stream` later.
- Fly/Sprites credentials are still blank on Render (AGENTS.md): a fresh project's `workspace_status` will go
  `failed` on live until they're set — that is the card telling the truth, not a bug.
- The free Ling 3.1 Flash window ends **2026-10-13** (C12) — the "Connect a model key" banner is deliberately
  generic about price.

## Self-audit pass (after the first hand-off)

Re-checked everything I had written from memory against the source, and fixed what was wrong:

- **Workspace page leaked state between projects** (drawer → another project reuses the component): now keyed by id.
- **Global `ok` colour had been lightened**, which fails contrast as text — restored the original.
- **Old settings pages got narrower** (`max-w-3xl` vs the original `max-w-5xl`) — restored.
- **Scratch + no name + no prompt** no longer slips through as "Untitled project" (see above).
- **Model chip** now names the key explicitly when the account has keys but none flagged default (otherwise the
  server answered `llm_key_required` to a person who does have a key).
- Composer autofocus while disabled; conflicting `mb-*` utilities; stale back-arrow breadcrumb; `None` guard in
  set-default.

Verified correct against the source (no change needed): SSE event names (`event`/`status`) and `after_id`;
`GET /sessions/{id}`; message/interrupt/approval bodies; Push/Pull/Deploy/Checkpoint request bodies; the
connectors-access shapes; `AuthedUser` fields; `project_workspaces.*` includes `sprite_handle`; Next 14.2 supports the
`viewport` export; no undefined names in any Python file touched.
