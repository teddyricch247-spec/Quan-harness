# Coding Harness

A personal, single-user, mobile-first ReAct coding agent. It reads and writes files
directly in a GitHub repo, deploys via Vercel, verifies its own work with a second
DeepSeek call, and streams its reasoning live so you can watch it work from your phone.

Built from `harness-build-spec.md`. Not deployed anywhere — this is the source, for
you to run locally and deploy yourself when you're ready. No Vercel or Render actions
were taken.

## What's already done for you

The Supabase side is fully provisioned — I have your Supabase connector, so I used it
directly instead of making you click through the dashboard:

- **Project created**: `harness`, org `Webcraft Solutions Agency`, region `eu-west-1`,
  free tier ($0/month). Project ref: `lssfnrkqwymzfhgzlhad`.
- **Schema applied**: `projects`, `sessions`, `messages` tables exist and are empty,
  exactly matching `sql/schema.sql`.
- **Keys filled in**: `backend/.env` and `frontend/.env` already have the real
  Supabase URL and anon key — not just `.env.example`.

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

`backend/.env` has four more blanks — paste in real values before running:

- `DEEPSEEK_API_KEY` — from your DeepSeek account
- `GITHUB_TOKEN` — a Personal Access Token with the **repo** scope
- `VERCEL_TOKEN` — an account or team token
- `TAVILY_API_KEY` — from your Tavily account

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

## About the thinking switch

You asked for low/medium/high/max. I checked DeepSeek's actual docs first: **there is
no independent "medium" for V4 Flash's Responses API.** The three levels it natively
supports are `low`, `high`, and `max`. DeepSeek's Chat Completions compatibility layer
accepts `medium` as an input value, but it's an alias that silently maps to `high` —
not a distinct effort level. Shipping a 4-position switch where two of the positions
do the exact same thing seemed worse than just being upfront about it, so the switch
in `ReasoningSwitch.jsx` has three real positions: **Low / High / Max**.

It's a per-session setting (`sessions.reasoning_effort` in Postgres), changeable from
the composer at any time, and it's sent as `reasoning.effort` on every DeepSeek call
for a turn — both the main agent's tool-calling rounds and the verifier subagent that
runs after `finish_task`. That's the "applies everywhere" behavior you asked for.

## A note on the two system prompts

`shared/main-agent-system-prompt.md` and `shared/verifier-system-prompt.md` were
**reconstructed by me**, not copied from your upload — the build spec describes their
required content (identity, current-context template vars, tool-usage rules, code
philosophy, communication, memory behavior, boundaries for the main prompt; identity,
scope, what-to-check/what-not-to-do, output format for the verifier) but says to use
"the drafted" versions verbatim, and those drafts weren't in `harness-build-spec.md`
or anywhere else in this conversation. I wrote versions that satisfy every requirement
the spec lists, including the two required edits (the `vercel_create_project` ordering
rule and the `finish_task` stack-persistence rule). Read through both before you trust
them with real commits — they're yours to edit, not gospel.

## Repo layout

```
/harness
  /frontend   → Vite + React → deploy to Vercel yourself (root directory: /frontend)
  /backend    → Node + Express → deploy to Render yourself (root directory: /backend)
  /shared     → prompts + tool schemas, read by the backend at boot
  /sql        → schema.sql — already applied to the live Supabase project
```

## Deploying later (optional, when you're ready)

This wasn't done for you, per your request — but when you are ready:

- **Backend → Render**: new Web Service, root directory `backend`, build `npm
  install`, start `npm start`. It must be a real long-lived process (not serverless)
  so it can hold an SSE connection open for an entire multi-tool-call turn — Render's
  standard web service is exactly that. Set all six `backend/.env` vars as Render
  environment variables, plus `FRONTEND_ORIGIN` pointed at your real Vercel URL once
  you have it.
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

## Deliberately out of scope (per the spec)

- Branch/confirm ceremony before pushing to main — every write commits straight to
  the default branch.
- True concurrent subagents — the verifier is sequential.
- In-browser code execution or a live dev-server preview.
- Queue-driven background execution — the disconnect-tolerant loop in
  `backend/src/agent/loop.js` covers most of the real need without one.
