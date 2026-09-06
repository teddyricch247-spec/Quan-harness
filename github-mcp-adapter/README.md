<p align="center">
  <img src="assets/logo.png" alt="Quan Adaptor logo" width="120" height="120" />
</p>

# Quan Adaptor

*Same idea as a physical adaptor: your stuff on one side, a platform's plug on the other, wired together. It started with GitHub — Vercel and Supabase came next because the shape of the problem is the same everywhere: a platform's own connector for Claude.ai stops short of something you actually need. This is the general answer, not just a GitHub-specific one.*

Lets Claude.ai (or any MCP-speaking agent) work against your GitHub repos,
Vercel projects, and Supabase Edge Function secrets — gated behind Supabase
acting as an OAuth 2.1 server, with **one approval covering all three**,
since every tool below is registered on this same server. Started as a fix
for the managed GitHub connector (which chokes on private/org repos);
Vercel and Supabase were added to fill gaps the official connectors for
those two don't cover at all, not to work around unreliability — see
"Design notes" below for exactly what's missing from each and why.

```
Claude.ai --OAuth-->                  Supabase   (issues a token; you approve the grant, once)
Claude.ai --MCP call, bearer token--> this server (Render)
this server --verifies token via Supabase JWKS--> GitHub API / Vercel API / Supabase Management API
```

This folder lives inside your **Quan Harness** repo, alongside `backend/` and
`frontend/`, but deploys as its own, separate Render service — see "Deploy on
Render" below. It doesn't read or import anything from `backend/` or
`frontend/`; it's self-contained.

## What's already done

- Full server (`server.py`): 32 tools total — 25 GitHub, 4 Vercel, 3
  Supabase — see the reference table below
- `static/login.html` + `static/consent.html` — the login and authorization
  pages Supabase's OAuth Server redirects your browser through
- `render.yaml`, for reference (see the Render section for why you won't
  deploy with the one-click Blueprint button here)
- Wired to your existing **`harness`** Supabase project — the same one this
  repo's own backend already uses — rather than a new one; more on exactly
  what that does and doesn't share below.
- **Not live-tested against Vercel's or Supabase's actual APIs** — I wrote
  the 7 new tools against their current official REST docs and mirrored the
  existing GitHub tools' patterns, but this sandbox has no network access to
  actually call either API. Syntax-checked, not execution-tested. Smoke-test
  with a read-only call (`vercel_list_env_vars` on some low-stakes project)
  before trusting the write/delete ones.

## Tool reference

Every description below is copied straight from its docstring in
`server.py` — that's the literal text Claude sees when deciding what to call.

| Tool | Description |
|---|---|
| **Repository & code browsing** ||
| `list_my_repos(limit=20)` | List repositories the configured GitHub token can access, most recently pushed first. |
| `get_repo(repo)` | Get metadata about a repository — description, default branch, visibility, language, stars, open issues. |
| `get_repo_tree(repo, ref="", path="")` | List every file and directory in a repository, recursively. The fix for "the agent can't find anything it doesn't already know the path to." |
| `search_code(query, repo="")` | Search source code on GitHub, optionally scoped to one repo. |
| `list_branches(repo, limit=50)` | List branches, with each one's latest commit SHA and whether it's protected. |
| **Commit history** ||
| `list_commits(repo, branch="", path="", limit=20)` | List recent commits, optionally filtered to a branch and/or file path. |
| `get_commit(repo, sha)` | Full detail on one commit, including every file it touched and the diff for each. |
| **File contents** ||
| `get_file(repo, path, ref="")` | Read a text file's full contents. |
| `create_or_update_file(repo, path, content, message, branch)` | Create or overwrite a file in a single commit. |
| `delete_file(repo, path, message, branch)` | Delete a file in a single commit. |
| **Branches** ||
| `create_branch(repo, new_branch, from_branch)` | Create a branch from the tip of an existing one. |
| `delete_branch(repo, branch)` | Delete a branch. Refuses on the default branch — see Design notes. |
| `force_update_branch(repo, branch, sha)` | `git push --force`, via the API. Refuses on the default branch — see Design notes. |
| **Pull requests** ||
| `create_pull_request(repo, branch, base, title, body)` | Open a pull request. |
| `list_pull_requests(repo, state="open", limit=20)` | List pull requests by state (open/closed/all). |
| `get_pull_request(repo, number)` | Full detail on one PR, including mergeability and change stats. |
| `list_pull_request_files(repo, number)` | The files changed in a PR, each with its diff. |
| `merge_pull_request(repo, number, merge_method="merge")` | Merge a PR (merge / squash / rebase). |
| `add_pull_request_comment(repo, number, body)` | Add a conversation comment to a PR. |
| **Issues** ||
| `list_issues(repo, state="open", limit=20)` | List issues (pull requests filtered out, even though GitHub's API mixes them in by default). |
| `get_issue(repo, number)` | Full detail on one issue, including labels. |
| `create_issue(repo, title, body="", labels=None)` | Open a new issue. |
| `add_issue_comment(repo, number, body)` | Add a comment to an issue. |
| `close_issue(repo, number)` | Close an issue (reversible — reopening restores it). |
| **Repositories** ||
| `create_repository(name, description="", private=True)` | Create a new repo. Needs broader token permissions than everything else here — see its docstring. |
| **Vercel** ||
| `vercel_list_env_vars(project, target="")` | List a project's env vars — key/target/type/updated_at only, never values. |
| `vercel_set_env_var(project, key, value, target=None, sensitive=True)` | Create-or-update an env var in one call. Doesn't redeploy — see its docstring. |
| `vercel_remove_env_var(project, key, target="")` | Delete an env var. Omitting `target` removes it from every environment. |
| `vercel_redeploy(project, branch="", target="production")` | Trigger a fresh deployment from the linked GitHub repo's latest commit. |
| **Supabase** ||
| `supabase_list_secrets(project_ref)` | List an Edge Function's secret names only, never values. |
| `supabase_set_secrets(project_ref, secrets)` | Create or update one or more secrets in a single call. |
| `supabase_delete_secrets(project_ref, names)` | Delete one or more secrets by name (Supabase's own bulk-delete endpoint — currently marked experimental on their side). |

## Design notes — what's gated, what isn't, and what's excluded

Every tool executes fully on its first call — no confirmation step. Two of
them have a **hard, non-interactive guard** instead, which is a different
thing from a confirmation step: no prompt, no second call, no override —
`delete_branch` and `force_update_branch` simply refuse outright if the
target is the repository's **default branch**, every time. Force-push in
particular is the scenario your developer's original note called out: an
instruction hidden in repo content (an issue, a PR body, a comment) that a
coding agent reads and acts on shouldn't be able to silently rewrite your
main branch's history with no way back. Every other branch, and every other
operation — including merging to main and deleting files — has zero
restriction.

**Deliberately not included (GitHub):** deleting a repository (cascades, no
undo, not a routine action) — and GitHub Actions/workflows, releases/tags,
and collaborator/permission management (different API surface than "read
and write my code").

**Deliberately not included (Vercel):** deleting a project, and buying or
attaching domains. Both already go through the official Vercel connector,
which gates domain purchases behind its own cost-confirmation step
(`get_purchase_quote` / `confirm_cost`) — no reason to build a second path
around that here.

**Deliberately not included (Supabase):** retrieving the service_role/secret
key, and deleting a project. The key is the one thing I'd actually call a
hard line rather than a judgment call — it's not scoped to one session or
one action the way everything else here is. Once it's in a transcript it's a
standing credential that bypasses Row Level Security entirely and works
until you rotate it, independent of whatever this adapter does afterward.
Everything else new here (env vars, secrets, redeploys) is cheap to reverse
if it goes wrong — that one isn't, so it stays out rather than gated.

Nothing new here got a `delete_branch`-style hard guard, deliberately: env
var writes, secret writes, and redeploys are all recoverable the same way
`merge_pull_request` and `delete_file` already are — reset the value, deploy
again — so they follow the "execute fully, no gate" tier those already sit
in, not the default-branch tier.

## How `harness` is and isn't shared with this repo's own backend

This adapter uses the same Supabase project (`harness`) that `backend/`
already runs on — reused rather than a fresh project, since you were already
at 2 active free Supabase projects in your org and this adapter needs no
database tables of its own.

- **Shared:** the Auth system — same user table, same JWT signing
  configuration, same OAuth Server toggle. There's already one account in
  there (`richquan247@gmail.com`) — that's the same login this adapter's
  consent screen uses, you don't need a second one.
- **Not shared:** any actual data. This adapter never queries harness's
  Postgres tables — only its Auth/OAuth layer.
- **The JWT signing key change is safe.** Step 1 below has you switch
  harness's signing algorithm from HS256 to RS256/ES256 — a project-wide
  setting. I checked `backend/src/auth/middleware.js`: it authenticates
  requests via `supabaseAuthClient.auth.getUser(token)`, which asks
  Supabase's own servers to validate the token rather than checking the
  signature itself. That call works the same regardless of signing
  algorithm, so this change won't affect the existing backend's login.

## Sleep & wake (Render free tier)

Render's free web services sleep after 15 minutes idle, and the first
request after that takes up to ~30-50 seconds to respond while it wakes up.
You already worked around this for `backend/` with
`frontend/src/lib/useBackendKeepAlive.js` — pinging `/health` every 5
minutes for as long as someone has the app's tab open. That's a good fit
there because there's a natural "someone is actively using this right now"
signal to hang the pinging off: an open browser tab.

An MCP server doesn't have that signal — Claude might go hours between
GitHub requests, then need one right now. So instead of an external pinger
that tries to keep it always warm, `server.py` tells the connecting model
directly how to handle a cold server, via FastMCP's `instructions` field:
if a tool call is unusually slow or times out on the first call in a while,
wait and retry once before reporting a failure — a second failure in a row
means something's actually wrong.

That's what you're describing as "the AI can literally just wake it up and
stop working until it woke up" — that's now the server's own stated
behavior for any MCP client that connects to it, not something you have to
separately ask for each time.

**On purpose, this doesn't keep the adapter always-on 24/7.** Render grants
750 free instance-hours **per workspace, per month** — shared across every
free service you run (`Quan-harness`, `Quan AI`, `the-edit-app-backend`, and
now this one). Keeping just this one service always warm would burn roughly
730 of those 750 hours by itself, leaving almost nothing for the others —
so it only spins up when something actually calls it, same as it does today.

If you ever want an alert when it's genuinely down (not just asleep) rather
than relying on retry-then-report, a free external uptime monitor (like
UptimeRobot) hitting `/healthz` on an infrequent schedule — say hourly, not
every few minutes — would tell you that without meaningfully touching the
750-hour budget. I didn't build that in; say the word if you want it.

## What's left — your part

### 1. Supabase dashboard (the `harness` project)

- ~~JWT signing keys~~ — **already done.** Confirmed on-screen: `harness`'s
  CURRENT KEY is **ECC (P-256)** — an asymmetric elliptic-curve key
  (what ES256 verification uses), not the legacy shared secret. This
  adapter's JWKS-based auth needs exactly that, and it's already in
  place — there was no "Migrate"/"Rotate" step actually pending here,
  despite what I said earlier. Nothing to do.
- **Authentication → URL Configuration**: set **Site URL** to this adapter's
  Render URL once you have it (step 4), e.g.
  `https://quan-github-mcp.onrender.com`.
- **Authentication → OAuth Server**: enable it, set **Authorization Path** to
  `/oauth/consent`, and turn on **dynamic client registration**.
- You already have a user (`richquan247@gmail.com`) — no need to add one.

> **Unrelated, still worth doing:** `harness` has 5 tables with Row Level
> Security disabled, including one called `secrets`. Nothing here touches
> them, but:
> ```sql
> ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
> ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
> ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
> ALTER TABLE public.providers ENABLE ROW LEVEL SECURITY;
> ALTER TABLE public.secrets ENABLE ROW LEVEL SECURITY;
> ```
> I didn't run this — enabling RLS with no policies yet blocks all access
> until you add policies, so it needs you to decide the access rules first.

### 2. Tokens

- **GitHub** — already done, if you're just adding Vercel/Supabase to an
  adapter you'd already deployed.
- **Vercel** — a personal access token from **vercel.com/account/tokens**.
  This is account/team-scoped, not project-scoped — it'll reach every
  project under whichever account or team it belongs to, there's no
  narrower option on Vercel's side. If your projects live under a Team
  rather than your personal account, also grab the Team ID from **Team
  Settings → General**.
- **Supabase** — a personal access token from
  **supabase.com/dashboard/account/tokens**. Different thing from
  `SUPABASE_ANON_KEY` below: that key belongs to one project (`harness`)
  and only touches its Auth layer, this token is account-wide and can
  manage every Supabase project you have. Name it something you'll
  recognize later, e.g. "quan-mcp-adapter".

### 3. Update the folder in your repo

This zip contains the updated `github-mcp-adapter/` folder — `server.py`,
`requirements.txt`, `render.yaml`, and `.env.example` all changed; the
`static/` pages didn't. Replace your existing local copy with this one
(same location, alongside `backend/` and `frontend/`), then commit and push
as normal. Nothing about `backend/` or `frontend/` changes.

### 4. Add the 3 new env vars to your existing Render service

This is the same `quan-github-mcp` service you already deployed for the
GitHub tools — no new service needed, since every tool (GitHub, Vercel,
Supabase) lives in the same `server.py` behind the same OAuth gate. On that
service's **Environment** tab, add:

| Env var | Value |
|---|---|
| `VERCEL_TOKEN` | the token from step 2 |
| `VERCEL_TEAM_ID` | the Team ID from step 2, or leave blank for a personal account |
| `SUPABASE_ACCESS_TOKEN` | the token from step 2 |

Push the updated code (step 3) and Render will redeploy the service with the
new tools available — same URL, same OAuth setup, nothing else to redo.

**Or** — say the word and I'll push these env var updates for you once
you've pasted the token values in chat... actually, don't paste them in
chat. Add them directly in Render's dashboard instead; that's the one step
here that should never go through me or this conversation.

### 5. Claude.ai

Nothing to redo here either — you already added this server as a connector
for the GitHub tools, and the same OAuth grant covers the new Vercel and
Supabase tools automatically. If Claude.ai caches the tool list per
session, a fresh conversation (or disconnect/reconnect on the connector)
picks up the 7 new ones.

## Other notes

- DCR means any MCP client that knows your server URL can *attempt* to
  register — expected, flagged in Supabase's own docs. The consent screen
  is the real gate: only approve requests you triggered yourself.
- Supabase's OAuth server doesn't yet support RFC 8707 resource indicators,
  so in theory a token could be replayed against a different FastMCP server
  that also uses `harness` as its auth provider. Not a practical risk with
  one server today.
