# Reconciliation — one codebase out of two diverged lines (2026-10-13)

## What happened

Work on this product forked in early October and was never merged:

| | Line A — the Phase 6 line | Line B — the GitHub line |
|---|---|---|
| Base | Phase 5.8 (2026-10-05) | Phase 5.4 (2026-10-03) |
| Added | 5.6–5.8, then Phase 6.1 (image input) and 6.2 (isolation suite) | BYOK provider presets, Ling/thinking controls, Phase Convert (UI redesign) |
| Where it lived | a separate working copy; only the 24 files Phase 6 touched survive (an "overlay") | `github.com/teddyricch247-spec/Quan-harness` `main` |
| Live database | applied: `0012_workspace_fingerprint`, `session_attachments`, `rls_cross_reference_checks`, `rls_audit`, `phase6_advisor_fixes` | applied: `llm_provider_presets`, `llm_reasoning_config` |

The live Supabase migration history proves both lines happened, in this order: Oct 3 fingerprint → Oct 8 02:40 Phase 6 → Oct 8 10:03
presets → Oct 9 reasoning config. Phase Convert was then built on line B, and its push (`9749b60`) failed the Vercel build for an
unrelated reason (below).

## What this tree is

Line B, plus everything from line A that could be recovered, plus a reconstruction of what couldn't:

| Commit (author date) | What |
|---|---|
| `97c804e` (Oct 3) | Last commit of the original history — Phase 5.4. Everything before it is untouched. |
| Oct 5 | `db/migrations/0012_workspace_fingerprint.sql` — the live column, recorded in a file. |
| Oct 6 | **Phase 6.1** image input (backend, migration `0013`, client library). |
| Oct 8 | **Phase 6.2** isolation suite + CI workflow (migrations `0014`, `0015`). |
| Oct 8 | BYOK provider presets (migration now `0016`). |
| Oct 8 | Ling / thinking controls (migration now `0017`). |
| Oct 11 | **Phase Convert**, including the deletion of the pages/components it replaced. |
| Oct 13 | Phase 6 × Convert: pictures in the workspace composer and transcript. |
| Oct 13 | **Phase 5.6–5.8, reconstructed** (see below). Dated today because it was written today. |
| Oct 13 | Documentation, env example, setup checklist. |

Author dates for the first six are when the work was done (file timestamps and the live migration history). The previous history is
preserved: the old `main` tip is tagged `backup/pre-reconcile-main` (`7f1bc44`), and the failed Convert push `9749b60` exists on
GitHub only — back it up there before force-pushing (see "Deploying").

### Why the Vercel build failed

Convert changed `AuthGuard` to take a render function. Three old pages still wrapped plain children in it (`app/connections/page.tsx`,
`app/projects/new/page.tsx`, `app/projects/[id]/sessions/page.tsx`); `PHASE_CONVERT_NOTES.md` lists them (and `NavBar`,
`WorkspaceShell`, `WorkspaceSyncPanel`, `DeployPanel`, `PreviewSecretsPanel`) as deleted, but the deletions never reached the
repository. `next build` type-checks every file, so it failed on the first one. They are deleted here; `next.config.js` redirects
the old routes.

## Phase 5.6–5.8: recovered vs reconstructed — read this

The original source of Phase 5.6–5.8 was not in the GitHub repository, not in any zip's git history, and not in the Phase 6 overlay
(which only holds what Phase 6 changed). It was rebuilt on 2026-10-13 from the spec you supplied (`phase-5-chopped.md`), from the
call sites in the original `agent_loop.py` (which survived inside the overlay and fixes the interfaces exactly), and from the
original's own notes.

* **Recovered intact:** `services/agent_loop.py` (all the wiring), `services/data_flows.py` + its test, `services/message_builder.py`,
  `routers/agent.py`.
* **Rewritten:** `sub_agent.py`, `turn_limits.py`, `visual_qa.py`, `visual_qa_rules.py`, `workspace_fingerprint.py`, the browser and
  preview tool schemas, lane grouping, the Push/Pull gate in `routers/workspace.py`, the data-flows router and page, the fingerprint
  hook in `deploy_pipeline.py`, `tests/test_security_checklist.py`.
* **Still missing:** the original `docs/PHASE5_6_5_7_5_8_NOTES.md` (replaced by a new one that says what the reconstruction is), the
  original tests for those modules (replaced by new ones), and the Phase 5.x test harness (`test_agent_loop_phase5_wiring.py`'s
  `World`), so the 21-test Phase 6 wiring test is parked in `docs/phase6-pending/`.

It behaves as the spec describes, but **it has never run against a real Chromium, Sprite or model**, and it is not guaranteed to match
the original in detail. `docs/PHASE5_6_5_7_5_8_NOTES.md` lists exactly what is unverified. Two points that matter operationally:
the agent's browser is **off by default** (`AGENT_BROWSER_ENABLED`) and its network wall must be tested before it is turned on; and
§23.10's fourth bullet (short-lived, least-privilege GitHub tokens) is **not met** — the GitHub token is the broad `repo`-scope OAuth
token.

If your Render backend currently runs a *different* build that contains the original 5.6–5.8 (deployed from somewhere other than this
repository), deploying this tree replaces it with the reconstruction. Check what Render is running first; I could not (Render needs a
workspace choice, and I did not look).

## Other things that differ from the Phase 6 write-up

* **Migration numbers.** Phase 6's `0013`–`0015` kept their numbers. Presets/Ling were written as `0012`/`0013` on line B and are now
  `0016`/`0017`. The database records them by *name*, so nothing is re-applied (`0017` is guarded; `0016` drops and re-adds one CHECK constraint to the same strict superset — harmless
  to re-run, but not guarded).
* **Vision.** "Does this model read images?" = `visual_qa.credential_supports_vision` (litellm's table, or `AGENT_VISION_MODELS`). It
  fails closed. The pinned `litellm==1.55.4` doesn't know most current models, so expect "this model can't read images" until you list
  the model there.
* **Where pictures are attached.** The + sheet in the workspace has "Add an image" (as the Convert spec says); pictures wait in the
  message box and are uploaded when you send. **Code home (a new project's first prompt) has no image option**: `POST /projects`
  creates the session and starts the first turn in one call, so there is no session to attach to. Attach from the workspace once the
  project exists, or extend `POST /projects` (a backend change).
* **A Phase 5.7 fix came along:** a command that ran and exited non-zero no longer shows as a bare "Error:" in the model's context.
* **New:** *Project settings → What leaves this workspace* (the §23.10 data-flows screen).

## What was verified, and what was not

Verified here (the sandbox has no network):

* **Frontend:** the whole `frontend/` tree type-checks under `strict` against hand-written stubs for React / Next / Supabase. The stub
  setup was **checked against the real failure**: putting the old `connections` page back reports exactly the error Vercel printed
  (TS2746, `children` expects a single render function).
* **Backend:** every module compiles; an undefined-name check passes; **635 test cases pass** in a sandbox runner (the 5 failures are
  identical in the pre-merge tree — they need `pydantic` or live-environment fixtures). New tests that run for real include the
  fingerprint script in a real `git`, the sub-agent loop with a fake model, the browser rules, the security checklist
  (mutation-checked) and a static contract test of every call the agent loop makes into the Phase 5.x modules.
* Cross-module references the ports rely on were each checked to exist.

**Not verified — do these before trusting it:**

* `next build` (real Next, real types) and `pytest` for the suites that need `fastapi`/`pydantic`/`starlette`/`litellm`/`supabase`.
  Run `cd backend && pytest` and `cd frontend && npm run build` first.
* The agent loop in a real turn (delegation, approval round-trip, a browser session), a real picture to a real model, a real
  Chromium, the Sprite `Authorization` question, and the isolation suite (needs your test accounts or a CI Supabase project).
* The `ChatPane` picture flow and the data-flows page in a browser.

## Deploying

The history in this tree is **rewritten** (the same commits up to `97c804e`, then a different line), so GitHub needs a force push, and
Vercel and Render will both redeploy from it.

```bash
git fetch origin
git branch backup/github-main origin/main && git push origin backup/github-main   # keeps 9749b60 (the failed Convert push)
# optional but sensible first: cd backend && pytest ; cd ../frontend && npm ci && npm run build
git push --force-with-lease origin main
```

1. **Database:** nothing to apply — the live project already has every migration in `db/migrations/`. Compare `list_migrations` with the
   table in `db/migrations/README.md` if you want to be sure.
2. **Backend (Render):** optionally set `AGENT_VISION_MODELS`. Leave `AGENT_BROWSER_ENABLED` unset (off) until you have read
   `YOUR_SETUP_CHECKLIST.md` §3c and the notes' "Not verified" list. Redeploy after the push.
3. **Frontend (Vercel):** builds from the push; no new env vars.
4. **Smoke test:** open a project → + → Add an image → send. Expected: either the picture appears in the transcript and the agent
   describes it, or a clear sentence that the project's model can't read images and how to fix it. Then *Project settings → What leaves
   this workspace*.
