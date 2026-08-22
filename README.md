# Coding Harness

A personal, single-user, mobile-first ReAct coding agent. It reads and writes files
directly in a GitHub repo, deploys via Vercel, verifies its own work with a second
model call, and streams its reasoning live so you can watch it work from your phone.

Built from `harness-build-spec.md`. Not deployed anywhere — this is the source, for
you to run locally and deploy yourself when you're ready. No Vercel or Render actions
were taken.

## This build is a merge of two parallel threads

You built on this in two places at once: this chat (provider switching + prompt-maker
sessions) and a separate session — a mobile-synced repo with three commits
(`Initial commit` → two `Last Sync (Mobile)` commits) — that added a third model role,
the critic. You uploaded that repo back into this chat and asked me to synthesize it
with what I'd built here.

I diffed both trees file-by-file rather than guessing. Almost every changed file was
purely additive on one side or the other — no real conflict, just "this feature's code
is missing from that copy." Five files actually had overlapping edits to reconcile by
hand:

- `backend/src/agent/loop.js` — both sides changed this (I added `provider` threading,
  the other session added the whole critic dispatch branch and `MAX_CRITIQUE_CALLS`).
  Merged: provider-aware calls, `messageStore.js`-based history loading, and the full
  critic branch, all together.
- `backend/src/agent/critic.js` — kept the critic logic as built, but repointed it from
  the other session's `deepseek.js` to this session's generalized
  `responsesApiClient.js`, and added `provider` to its signature so a critique always
  runs on whichever provider the session is actually using.
- `frontend/src/components/ToolActionList.jsx` — both sides added a describer for a new
  tool call (`request_critique` there, `finalize_prompt` here). Both cases now coexist.
- `frontend/src/pages/SessionView.jsx` — took this session's structure (interview
  turns, provider switch, handoff/lock handling) as the base and folded in the other
  session's `critique_notes` rendering inside the build-turn summary bubble.
- This file — written fresh, folding in the other session's own README section on the
  critic (reproduced below, in "A third role: the critic") rather than trying to
  interleave two separate documents.

Everything else — `tools.js`, `main-agent-system-prompt.md`, `main-agent-tools.json`,
`critic-system-prompt.md` — was taken wholesale from whichever copy actually had it,
since the other side's copy of that same file was identical, just missing that one
feature.

## The three features, in one place

1. **A second, optional model provider.** The Responses-API client
   (`backend/src/services/responsesApiClient.js`, generalized from a DeepSeek-only
   `deepseek.js`) takes a `provider` object from a registry in `backend/src/config.js`.
   DeepSeek is still always there and still the default; filling in the `CUSTOM_*`
   vars in `backend/.env` registers a second provider (any endpoint that speaks the
   OpenAI Responses API shape) and a provider switch appears in the composer. Leave
   those vars blank and nothing changes — no switch shown, DeepSeek-only.
2. **Prompt-maker sessions.** A session "kind": instead of talking straight to the
   coding agent, a prompt-maker session runs a separate interviewer agent (own system
   prompt, own read-only tool set, own message history) that asks a few short
   questions, proposes a final prompt, and — only once you confirm it — hands that
   single prompt to a **brand-new** build session that never sees the interview. New
   sessions default to this mode. See "How prompt-maker sessions work" below.
3. **The critic.** A `request_critique` tool the main coding agent can call on itself,
   up to twice per turn, mid-task, before `finish_task` — a second model call with no
   tools and no structured output that pushes back on whether the work is actually
   good, not just whether it runs. See "A third role: the critic" below.

## What's already done for you

The Supabase side is fully provisioned — I have your Supabase connector, so I used it
directly instead of making you click through the dashboard:

- **Project created**: `harness`, org `Webcraft Solutions Agency`, region `eu-west-1`,
  free tier ($0/month). Project ref: `lssfnrkqwymzfhgzlhad`.
- **Schema applied**: `projects`, `sessions`, `messages` tables exist, matching
  `sql/schema.sql`. (`sessions` has one real row from earlier testing — untouched.)
- **Keys filled in**: `backend/.env` and `frontend/.env` already have the real
  Supabase URL and anon key — not just `.env.example`.
- **Migration 002 applied**: `sessions` also has the `kind`, `origin_session_id`,
  `provider`, and `completed_at` columns the prompt-maker feature needs, and
  `reasoning_effort`'s old three-value CHECK constraint was dropped in favor of
  app-layer validation. Ran directly against the live project via the Supabase
  connector — `sql/002_providers_and_prompt_maker.sql` is that same migration, kept in
  the repo in case you ever need it against a second environment. The critic feature
  needed no schema changes at all (`critique_notes` just lives inside the existing
  `turn_summary` JSON blob).

**Two things I could not do for you**, both by design — the Supabase connector
doesn't expose either of these to automated tools:

1. **Service role key.** Go to the
   [harness project](https://supabase.com/dashboard/project/lssfnrkqwymzfhgzlhad/settings/api)
   → Project Settings → API → copy the `service_role` key (labeled "secret", not
   "anon") → paste it into `backend/.env` as `SUPABASE_SERVICE_ROLE_KEY`.
2. **Auth setup.** In the same project:
   [Authentication → Providers](https://supabase.com/dashboard/project/lssfnrkqwymzfhgzlhad/auth/providers) →
   disable email signups (so nobody but you can ever create an account), then
   [Authentication → Users](https://supabase.com/dashboard/project/lssfnrkqwymzfhgzlhad/auth/users) →
   add yourself manually (email + password). This is the only login the app will ever
   have — there's no signup screen in the frontend.

**One thing worth knowing:** RLS is disabled on all three tables, on purpose — the
backend uses the service-role key (which bypasses RLS) and the browser never talks to
Postgres directly, so table-level policies wouldn't add anything here. Supabase's own
advisor will flag this as "critical" every time you check it; that's expected. If you
ever add a code path where the browser reads these tables directly, enable RLS with
real policies before you do.

## What you still need to fill in

`backend/.env` has four more required blanks — paste in real values before running:

- `DEEPSEEK_API_KEY` — from your DeepSeek account
- `GITHUB_TOKEN` — a Personal Access Token with the **repo** scope
- `VERCEL_TOKEN` — an account or team token
- `TAVILY_API_KEY` — from your Tavily account

Optional — only if you want a second provider you can switch to instead of DeepSeek:

- `CUSTOM_LABEL`, `CUSTOM_BASE_URL`, `CUSTOM_API_KEY`, `CUSTOM_MODEL` — point these at
  any endpoint that implements the OpenAI Responses API (`POST {base_url}/responses`,
  streaming, `instructions`/`input`/`tools` request shape). OpenAI's own API works
  here directly.
- `CUSTOM_REASONING_EFFORTS` — comma-separated levels your model's Responses API
  actually accepts for `reasoning.effort` (e.g. `low,medium,high`), or leave blank if
  the model doesn't take that param at all.

Leave the `CUSTOM_*` block blank and the app behaves exactly as it did before — no
provider switch shown, DeepSeek is the only option.

## Running it locally

```bash
# Backend
cd backend
npm install
npm run dev        # nodemon-style reload via `node --watch`

# Frontend, in a second terminal
cd frontend
npm install
npm run dev         # http://localhost:5173
```

Open `http://localhost:5173`, sign in with the email/password you created in Supabase
Auth, and you're in.

## How prompt-maker sessions work

Every new session is one of two `kind`s, chosen with a toggle on the "new session"
screen (defaults to **Prompt Maker**):

- **`build`** — talks straight to the main coding agent, exactly like the original
  single-agent design: `shared/main-agent-system-prompt.md`,
  `shared/main-agent-tools.json`, `backend/src/agent/loop.js`.
- **`interview`** — talks to a separate prompt-maker agent instead:
  `shared/interview-agent-system-prompt.md`, `shared/interview-agent-tools.json`,
  `backend/src/agent/interviewLoop.js`. It has its own system prompt and only three
  tools — `github_list_tree` and `github_read_file` (read-only, to ground questions in
  what's actually in the repo) and `finalize_prompt`. It cannot write code, touch
  GitHub, or touch Vercel.

The interview agent asks short questions, and once it believes it has enough, it
writes out the exact prompt it's proposing as normal chat text and waits for explicit
confirmation. Only after you confirm does it call `finalize_prompt`, which:

1. Creates a **brand-new `build` session** (`origin_session_id` pointing back at the
   interview session, for the "← from prompt maker" link in its header) with nothing
   in it — the interview's message history is never copied over, and structurally
   can't be: `backend/src/agent/messageStore.js` only replays real Responses-API items
   (`message`/`function_call`/`reasoning`/`function_call_output`) back into a session's
   own history, never another session's rows.
2. Locks the interview session (`completed_at`) — the frontend replaces its composer
   with a link to the build session, and the backend rejects any further POST to it
   (`409`) as a second guard against the same thing.
3. Streams a `handoff` SSE event back to the browser with the new session id and the
   generated prompt. The frontend navigates there and sends that prompt as the new
   session's first message the normal way (`SessionView.jsx`'s `autoSendPrompt`
   handling) — so the build session's first turn runs through the exact same code path
   as if you'd typed it yourself, no special-cased "handoff turn" on the backend.

One consequence worth knowing: a prompt-maker session is genuinely a dead end once
`finalize_prompt` fires. If you want changes after seeing what got built, make them in
the build session (it's a normal iterative session from there) rather than trying to
go back and re-open the interview.

## A third role: the critic

The original build had two model roles — the main agent and the verifier. A third,
the **critic**, addresses something the verifier was never meant to catch: the
verifier only checks whether committed code is *broken*, not whether it's actually
*good*. Nothing in the original design pushed the agent to reconsider its own work
before calling it done.

The critic closes that gap, and is deliberately built to not become a second verifier:

- **It's optional and agent-initiated.** The main agent decides whether to call it, via
  a `request_critique` tool — not automatic like the verifier. Guidance on when to use
  it lives in the "Self-critique on hard tasks" section of
  `shared/main-agent-system-prompt.md`.
- **It has no tools and returns no structured output.**
  `shared/critic-system-prompt.md` is its entire briefing: the request, the diffs so
  far, and project memory — nothing it can read on its own. It replies in plain prose,
  not JSON, and never proposes a diff. Contrast with the verifier, which has
  `github_read_file` and must return corrections that get auto-applied.
- **It's capped at two calls per turn**, enforced in `backend/src/agent/loop.js`
  (`MAX_CRITIQUE_CALLS`), not left to the model's discretion — a critic will always
  find *something* if asked enough times, so the cap exists to stop that turning into
  an unproductive loop rather than a genuine second look.
- **It runs on whichever provider the session is using.** `runCritique` in
  `backend/src/agent/critic.js` takes the same resolved `provider` object as the main
  agent's calls and the verifier's — a session on the custom provider gets critiqued
  by that same provider, not silently by DeepSeek.
- **Because every write already commits immediately** (no staging step — see the
  Boundaries section of the main prompt), acting on a critique just means writing more
  files before `finish_task` — the same tool, called again. Nothing new was needed to
  support that.

Relevant files: `shared/critic-system-prompt.md`, `backend/src/agent/critic.js`
(mirrors `verifier.js` but with no tool loop and no schema), the `request_critique`
entry in `shared/main-agent-tools.json`, and the dispatch branch in
`backend/src/agent/loop.js` alongside `finish_task`'s. Critique text is stored on the
turn summary as `critique_notes` and shown in the UI next to the verifier's notes
(`SessionView.jsx`).

## About the thinking switch

You asked for low/medium/high/max. I checked DeepSeek's actual docs first: **there is
no independent "medium" for V4 Flash's Responses API.** The three levels it natively
supports are `low`, `high`, and `max`. DeepSeek's Chat Completions compatibility layer
accepts `medium` as an input value, but it's an alias that silently maps to `high` —
not a distinct effort level. Shipping a 4-position switch where two of the positions
do the exact same thing seemed worse than just being upfront about it, so the switch
in `ReasoningSwitch.jsx` has three real positions: **Low / High / Max**.

It's a per-session setting (`sessions.reasoning_effort` in Postgres), changeable from
the composer at any time, and it's sent as `reasoning.effort` on every model call for
a turn — the main agent's (or prompt-maker's) tool-calling rounds, the critic (when
the agent asks for one mid-turn), and the verifier subagent that runs after
`finish_task`. That's the "applies everywhere" behavior you asked for.

Since the provider switch was added, the switch's actual positions are no longer
hardcoded to DeepSeek's three — `ReasoningSwitch.jsx` renders whatever
`reasoningEfforts` the currently-selected provider declares (`GET /api/meta`), so
switching to a custom provider with different levels — or none — changes what's shown
instead of silently sending a value that provider might reject.

## A note on the system prompts

None of the four agent system prompts came from a verbatim draft in this
conversation — the build spec describes their required content but says to use "the
drafted" versions, and those drafts were never actually shared with me:

- `shared/main-agent-system-prompt.md` and `shared/verifier-system-prompt.md` were
  reconstructed to satisfy every requirement the spec lists (identity, current-context
  template vars, tool-usage rules, code philosophy, communication, memory behavior,
  boundaries; the two required edits — `vercel_create_project` ordering and
  `finish_task` stack persistence — are in there).
- `shared/critic-system-prompt.md` and the "Self-critique on hard tasks" section woven
  into `main-agent-system-prompt.md` came from the other session, kept as-is.
- `shared/interview-agent-system-prompt.md` is new, written for the prompt-maker
  feature specifically (there's no spec section for it to satisfy — it's this
  conversation's own addition).

Read through all four before you trust them with real commits — they're yours to
edit, not gospel.

## Repo layout

```
/harness
  /frontend   → Vite + React → deploy to Vercel yourself (root directory: /frontend)
  /backend    → Node + Express → deploy to Render yourself (root directory: /backend)
  /shared     → prompts + tool schemas for all agent roles, read by the backend at boot:
                  main-agent-*        → the coding agent (build sessions)
                  interview-agent-*   → the prompt-maker agent (interview sessions)
                  verifier-*          → the post-finish_task correctness check
                  critic-*            → the optional mid-task self-critique
  /sql        → schema.sql (fresh-install shape) +
                002_providers_and_prompt_maker.sql (already applied to the live project)
```

## Deploying later (optional, when you're ready)

This wasn't done for you, per your request — but when you are ready:

- **Backend → Render**: new Web Service, root directory `backend`, build `npm
  install`, start `npm start`. It must be a real long-lived process (not serverless)
  so it can hold an SSE connection open for an entire multi-tool-call turn — Render's
  standard web service is exactly that. Set every var in `backend/.env` as a Render
  environment variable (the `CUSTOM_*` ones only if you're actually using a second
  provider), plus `FRONTEND_ORIGIN` pointed at your real Vercel URL once you have it.
- **Frontend → Vercel**: new project, root directory `frontend`, framework preset
  Vite. Set the three `frontend/.env` vars as Vercel environment variables, with
  `VITE_BACKEND_URL` pointed at your real Render URL.
- Vercel's project-creation endpoint (used internally by the `vercel_create_project`
  tool) is noted in the spec as one that "has revved before" — worth a quick check
  against Vercel's REST API docs before your first real run, in case it's moved again
  since this was built.

## Build order this followed

1. Postgres schema + Supabase Auth setup — schema done for you; Auth is the one manual
   step above.
2. Backend fetch wrappers for GitHub/Vercel/Tavily/DeepSeek — done.
3. Backend agent loop + SSE endpoint — done.
4. Backend verifier wiring on `finish_task` — done.
5. Frontend: login → project list → session view, SSE consumer — done.
6. Deploy — intentionally left to you.
7. (Post-initial-build, merged from a parallel session) The critic role, plus this
   session's own provider switching and prompt-maker sessions — done.

## Deliberately out of scope (per the spec)

- Branch/confirm ceremony before pushing to main — every write commits straight to
  the default branch.
- True concurrent subagents — the verifier and critic are both sequential, and the
  critic never runs concurrently with the main agent's own tool-calling rounds.
- In-browser code execution or a live dev-server preview.
- Queue-driven background execution — the disconnect-tolerant loop in
  `backend/src/agent/loop.js` covers most of the real need without one.
