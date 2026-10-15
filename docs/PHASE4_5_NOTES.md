# Phase 4.5 — Scheduling / Proactive Scanning (§26)

**Implementation Order step 15, the last piece of Phase 4.** Assumes Phases
1–3 are complete (the full turn loop, system prompt, permission states, and
crash recovery) and Phase 4.3 (Connector integration) is complete — §26
depends on it directly: "a scheduled run that touches GitHub issues/CI needs
a GitHub connector already connected and permissioned." Both were true going
into this pass — see `docs/PHASE4_3_4_4_NOTES.md`.

With this, **Phase 4 of 9 is complete.**

## What this delivers

A person can configure a recurring check on a project — "look for failing
CI," "check for new dependency vulnerabilities," "review open issues for
anything quick to fix" — on an hourly, daily, or custom cron-style cadence.
When it comes due, it starts a real session, with the schedule's own
description standing in as the initiating message, running the identical
turn loop, system prompt, and permission machinery every other session
uses — with exactly one behavioral difference: every mutating tool call in
that run is treated as Ask, regardless of what the project's Auto/Ask/Off
settings say, for the run's entire duration.

Files touched:

- `db/migrations/0009_scheduling.sql` — `project_schedules` (the recurring
  check's own config), `sessions.trigger`/`sessions.schedule_id` (how a
  session records who/what started it).
- `backend/app/services/scheduler_rules.py` — pure "is this schedule due
  right now" rule, kept dependency-free like `guard_rules.py`/
  `tool_partition.py`/`stuck_detector.py`, with real unit tests
  (`backend/tests/test_scheduler_rules.py`).
- `backend/app/services/scheduler.py` — the in-process background poll loop
  and `trigger_schedule`, the one function that actually starts a run (the
  loop and the "run now" endpoint both call it).
- `backend/app/services/agent_loop.py` — `_resolve_permission_for_call`
  gained `force_ask`; the mutating-call branch in `_run_inner` gained a
  third case (a native tool forced to Ask); `_action_resolved_approval`
  gained a `scheduled_tool:` branch, including the one genuinely new
  wrinkle this phase introduces — see "Nested approvals" below.
- `backend/app/services/system_prompt.py` — a new `SCHEDULED_RUN` dynamic
  section, present only on a scheduled session, explaining the forced-Ask
  behavior to the model directly rather than leaving it to infer from
  `SECURITY`'s now-contradicted "OK to do without asking" list.
- `backend/app/repositories/project_schedules.py`,
  `backend/app/repositories/sessions.py` (`create_for_project` gained
  `trigger`/`schedule_id`) — the data layer.
- `backend/app/routers/projects.py` — `/projects/{id}/schedules` CRUD plus a
  manual `/run` endpoint (not in §26's own text — see below).
- `backend/app/config.py` — `scheduler_poll_interval_seconds` (default 60).
- `backend/requirements.txt` — `croniter`, for parsing a custom cron
  expression.
- `frontend/app/projects/[id]/settings/page.tsx` — a Scheduling panel,
  matching the Memory/Project Knowledge panels already there.

## Design decisions the spec excerpt doesn't spell out

**In-process poll loop, not a separate Render Cron Job.** The backend is one
Render web service (see `docs/DEPLOYMENT.md`, confirmed against the live
Render workspace, not assumed) — there's no second service to point a cron
job at, and standing one up is real new infrastructure a background asyncio
task inside the process already running avoids needing. `scheduler.py`'s
loop polls every `scheduler_poll_interval_seconds` (60s default), checking
every enabled schedule against `scheduler_rules.is_due`. The real
consequence: **a schedule can't fire while this single free-tier instance is
asleep** (Render free tier spins down after inactivity — `docs/DEPLOYMENT.md`
already flags this same cold-start behavior for ordinary requests). A missed
tick isn't lost, just late — `is_due`'s hourly/daily/custom-cron rules are
all "has enough time elapsed," not "did we hit the exact minute," so the
first request that wakes the instance back up (or the next poll tick, once
awake) picks up anything overdue. If reliable to-the-minute firing while
otherwise idle matters, the fix is a paid Render instance (removes the sleep
entirely) or an external uptime pinger hitting `/health` periodically — not
a code change here.

**A schedule's first run fires immediately, not on its first real tick.**
`scheduler_rules.is_due` treats `last_run_at is None` as always due,
regardless of frequency. Reasoning: the person just opted into this from
their own Settings; an immediate confirmatory run is the fastest way to find
out the setup actually works (the connector they meant to grant really is
granted, the project's LLM credential resolves) rather than leaving them to
wonder — possibly for up to 24 hours — whether anything is happening at all.
Every run after the first follows the configured cadence exactly, measured
from `last_run_at`.

**No `next_run_at` column.** `is_due` computes due-ness from
`frequency`/`cron_expression`/`last_run_at` fresh on every poll tick rather
than reading a cached "when should this fire next" value maintained by a
second write path. One source of truth, at the cost of a few more croniter
calls per tick — a cost that's irrelevant at the schedule counts this will
plausibly ever see per account.

**Forced-Ask applies to mutating calls only, not literally "every tool
call."** §26's own text says "a scheduled run treats every one of its own
tool calls as Ask" — read as broadly as those seven words allow, that would
gate `view_file`/`web_search` too, meaning a scheduled run could never even
finish its own investigation unattended (there'd be no one to approve the
first read). That directly contradicts the same paragraph's next sentence:
"if a scheduled run's investigation surfaces something needing approval, it
stops there" — which presupposes the investigation itself runs to
completion first. Read against `tool_partition.py`'s existing read-only/
mutating split (already how every other permission decision in this codebase
draws that line), "every tool call" means every *mutating* one. A read-only
call — including a side-effect-free connector tool — still executes freely
on a scheduled run, exactly as it would interactively.

**A native tool forced to Ask gets its own `action_type`, not
`execute_bash_escalation`.** These answer genuinely different questions:
`execute_bash_escalation` means "this specific command text tripped the
heuristic guard"; the new `scheduled_tool:<name>` means "this call is
mutating and nobody's watching." Reusing the guard's own action_type for
execute_bash specifically would have been the smaller diff, but it would
also mean an approved scheduled bash command silently inherits
`bypass_guard=True` — someone approving "yes, run `pip install -r
requirements.txt`" would, as a side effect, also be granting a pass on the
credential-path/sudo/git-remote/curl-pipe-to-shell guard for that exact call,
which they never actually decided to grant. Keeping the two mechanisms
separate means an approved scheduled `execute_bash` call still runs through
the guard normally.

**Nested approvals.** The one genuinely new shape this phase introduces: an
approved `scheduled_tool:execute_bash` call can itself still trip the
heuristic guard on execution (see above) — a second, real
`execute_bash_escalation` gets requested at that point, parented to the same
original `tool_call` event so its eventual resolution reports back to the
right place. `_action_resolved_approval` previously never needed to produce
a *new* pending approval as a side effect of resolving one — it now returns
a sentinel (`"waiting_approval"`) when this happens, and `_run_inner` checks
for it before falling through into a fresh turn-loop iteration. This is the
one place this phase touched code whose previous behavior had no way to
exercise this branch at all; read it slowly if touching either function
again.

**The concurrency cap applies to a scheduled session exactly like an
interactive one.** §23.4/§25's "max 2 writable sessions per project, opening
a 3rd demotes the least-recently-used" is enforced in
`sessions_repo._enforce_concurrency_cap`, called unconditionally from
`create_for_project` — including the scheduler's own call into it. A
concrete consequence follows from *not* special-casing this: a schedule
firing while a person already has two writable sessions open on the same
project will demote their own least-recently-used one to read-only, exactly
as a third interactive session would. This is a deliberate reading of §26's
"no separate, more permissive code path for scheduled work," not an
oversight — carving out an exemption here would itself be exactly the kind
of special-casing that sentence rules out. If this turns out to be a bad
tradeoff in practice, the fix is narrow (skip the cap specifically for
`trigger='scheduled'`), but that's a product decision, not an implementation
gap.

**`POST /projects/{id}/schedules/{id}/run`.** Not in §26's own text. A
schedule can sit for up to 24 hours before its first natural tick; being
able to fire it once on demand — through the exact same `trigger_schedule`
the poll loop itself calls, not a parallel path — means a person can confirm
their setup works immediately instead of waiting to find out. Low-risk
addition: it's simply an earlier call to a function that was always going to
run anyway.

## Rough edges / known gaps

- **UTC only.** A custom cron expression is interpreted in UTC — there's no
  per-project or per-schedule timezone setting. "Every day at 9am" means 9am
  UTC, not 9am wherever the person is. Worth a `timezone` column on
  `project_schedules` (croniter doesn't need it — resolving a stored IANA
  zone name to a UTC offset at evaluation time is what would need adding) if
  this becomes a real complaint; not done here to keep this phase's schema
  change to exactly the two things §26 actually asked for.
- **Single-process only, same as the turn loop itself already is.**
  `scheduler.py`'s poll loop lives in the one running backend process, the
  same standing limitation `agent_loop.py`'s own `_running_sessions`/
  `_subscribers` registries and `docs/PHASE3_NOTES.md` already document for
  SSE fan-out. Running two backend instances would mean two independent poll
  loops, both evaluating the same schedules — `list_enabled`'s query has no
  locking, so both could observe the same due schedule in the same tick and
  both trigger it. Not a real risk against the current single-Render-service
  deployment; would need a real lock (a Postgres advisory lock, most simply)
  before ever running more than one instance.
- **No "next run" preview in the UI.** The Settings panel shows
  `last_run_at`, not a computed "next due around such-and-such." Computable
  from `scheduler_rules.is_due`'s own logic run forward, but not built here
  — `last_run_at` plus the configured frequency is legible enough for a
  first pass.
- **A disabled connector or expired credential isn't caught at schedule
  creation time.** §26 is explicit that "a scheduled run has no more reach
  than an interactive one does" — deliberately not enforced by checking for
  a granted GitHub connector before allowing a schedule whose description
  mentions GitHub, since the same is true of an ordinary interactive
  message and nothing gates *that* either. The turn loop's own
  `GITHUB_CONNECTOR` system-prompt block already tells the model plainly
  when it has no such connector; a scheduled run's report will say the same
  thing rather than silently doing nothing. This is a feature, not a gap —
  named here so it doesn't get "fixed" into an inconsistency with how every
  other session already works.

## Testing

`scheduler_rules.py` is pure and fully covered
(`backend/tests/test_scheduler_rules.py`) — no database, network, or
credentials needed, same standing as `test_tool_partition.py`/
`test_heuristic_guard.py`/etc. **Like every other phase's own honest
accounting in this repo: none of this suite has actually been run under
`pytest` in an environment this was built in** (no `pytest`, no network) —
run it for real before trusting a pass/fail claim about it.

`scheduler.py`'s poll loop, `trigger_schedule`, and the new branches in
`agent_loop.py` (`_resolve_permission_for_call`'s `force_ask`, the native-
tool Ask-gate branch, `_action_resolved_approval`'s `scheduled_tool:` branch
and its nested-escalation path) have no automated coverage — same standing
`docs/PHASE3_NOTES.md` already gives `_run_inner` itself, `mcp_tools.py`,
`mcp_oauth.py`, and `routers/agent.py`. Manually verifying end to end needs
real Supabase + an LLM credential + (to exercise the interesting branches) a
project with a granted connector and a command that trips the heuristic
guard — none of which existed in the sandbox this was built in.

## Closing note — Phase 4 is complete

That's all five of Phase 4's sub-prompts (4.1 Memory, 4.2 Project Knowledge,
4.3 Connector integration, 4.4 Auto-provisioning, 4.5 Scheduling). What's
next, per the roadmap, is Phase 5: the deploy pipeline, Live Preview,
sub-agent delegation, and visual QA — none of which this pass touched.
