# Phase 4.1/4.2 notes — Memory System, Project Knowledge

Written the same way `/docs/PHASE1_NOTES.md` through `/docs/PHASE3_NOTES.md`
were: an honest account of what's real, what's a documented rough edge, and
every place this build had to make a call the spec excerpt didn't fully pin
down. Scope is exactly `phase-4-chopped.md`'s sub-prompts 4.1 (§20, Memory
System) and 4.2 (§21, Project Knowledge) — 4.3 (Connector integration), 4.4
(Auto-provisioning), and 4.5 (Scheduling) were explicitly out of scope for
this pass and are untouched.

**Read `/docs/PHASE3_NOTES.md`'s own "What Phase 4 needs to know" section
first** — this build follows it directly: `system_prompt.DynamicSections`
already had `project_knowledge`/`what_you_know_about_this_person`/
`what_you_know_about_this_project` as real extension points, and the
static/dynamic prompt-caching split question it flagged is resolved below
("Design decisions").

## What's real and working

- **Four new tables** (`db/migrations/0007_memory_and_project_knowledge.sql`):
  `project_memory` (one curated row per project), `project_memory_log` (the
  append-only raw material behind it), `build_user_memory` (the account-level
  counterpart), `project_knowledge` (human-authored, triggerable notes). RLS
  on all four follows the exact shape every other table in this codebase
  already uses — project-join for the first, last, and second-to-last;
  direct `user_id = auth.uid()` for `build_user_memory`, the same shape
  `llm_credentials`/`github_credentials` already use.
- **One schema change to an existing table**: `session_events.event_type`
  gains `project_knowledge_injected` — a real `ALTER TABLE ... DROP
  CONSTRAINT ... ADD CONSTRAINT`, not a comment-only edit, since (unlike
  `audit_log.tool`) that column has a genuinely enforced CHECK. See "Design
  decisions" below for why this event type exists at all.
- **`app/services/memory.py`** (pure) — the two revision prompts (§20's
  project-tier and account-tier instructions), and `enforce_char_budget`, a
  defensive backstop distinct from the soft ~4,000-character target given to
  the model in the prompt itself.
- **`app/services/project_knowledge.py`** (pure) — §21's keyword/path
  trigger matching, the once-per-session bookkeeping logic
  (`select_newly_triggered`), and the accumulated-context logic
  (`select_all_triggered` — see "Fixes applied after review" below),
  reconstructing "already triggered" from the caller's own event-log scan
  rather than holding it anywhere itself.
- **`app/services/memory_extraction.py`** — the I/O shell: three pieces run
  concurrently (`asyncio.gather`) after every completed-or-stuck turn — the
  raw log append, the project_memory revision call, the build_user_memory
  revision call — each independently exception-swallowing so one failing
  piece never blocks or skips another.
- **Three new `system_prompt.py` formatters** —
  `format_project_knowledge`/`format_what_you_know_about_this_project`/
  `format_what_you_know_about_this_person` — following the exact convention
  `format_project_secrets`/`format_current_plan` already established:
  plain-dict input, `None` when empty (§18's "only if non-empty" rule).
  `DynamicSections`' own fields needed no changes at all — Phase 3 already
  shipped them, unused; see `/docs/PHASE3_NOTES.md`.
- **`agent_loop.py` integration** — `_run_inner`'s per-iteration dynamic-
  section gathering now also reads `project_memory`/`build_user_memory`
  (read-only; writing is `memory_extraction.py`'s job alone) and computes
  every Project Knowledge note triggered so far this session
  (`select_all_triggered`), appending a bookkeeping event for whichever
  ones are newly triggering this iteration before the next iteration could
  re-trigger them. A new
  `_finish_turn` helper is the single place every genuine "this turn is
  over" exit converges — replacing three previously-duplicated
  `update_fields`+`_broadcast_done` pairs — so the memory-extraction call
  happens exactly once, exactly on `completed`/`stuck`, never on `failed` or
  `waiting_approval`.
- **New endpoints**: `GET/PUT/DELETE /projects/{id}/memory`,
  `GET/POST/PATCH/DELETE /projects/{id}/knowledge[/{note_id}]` in
  `routers/projects.py`; `GET/PUT/DELETE /account/memory` in
  `routers/account.py`. Every mutation gets an `audit_log` row
  (`tool='memory'`, `initiated_by='user'`) — reads don't, matching every
  other GET in this codebase.
- **Frontend**: a Memory panel and a Project Knowledge panel added to the
  project's own Settings page; a new `/connections/memory` page for the
  account-level store, linked from the Connections index. All three follow
  the existing `apiFetch`/`ErrorBanner`/`card`/`input`/`btn-*` conventions
  exactly — no new components, no new CSS.

## Testing — what actually ran, and what needs real infrastructure

Same constraint every phase before this documents: **no network, no package
installs** in the environment this was built in — `fastapi`/`pydantic`/
`supabase`/`litellm` aren't importable here, so nothing that imports
`app.db`, a repository, `agent_loop.py`, or `memory_extraction.py` can
actually run, only be read through carefully.

**Ran for real, 50/50 passing**, via the same manual assert-based runner
Phase 3 used (no `pytest` binary either) — `test_memory.py` (11 tests: both
revision prompts, `enforce_char_budget`'s truncation/boundary/no-op
behavior), `test_project_knowledge.py` (17 tests: keyword and path
triggering, case-insensitivity, the once-per-session filter, ordering), and
the new additions to `test_system_prompt.py` (8 tests: the three new
formatters, and that `assemble()` places `PROJECT_KNOWLEDGE`/
`WHAT_YOU_KNOW_ABOUT_THIS_PERSON`/`WHAT_YOU_KNOW_ABOUT_THIS_PROJECT` in
exactly §18's own listed order). These are every pure decision module this
phase adds or extends — the same "kept dependency-free specifically so this
was possible at all" reasoning Phase 2/3 give for their own pure modules.

One real bug this actually caught, before shipping: `_path_triggers`'
first draft used bare `fnmatch.fnmatch(path, trigger_value)`, which requires
a full match from the path's own root — §21's own worked example
(`migrations/*.sql`) would then only ever fire on a file literally at
`migrations/<x>.sql` from the repo root, never on the realistic
`backend/db/migrations/0007_x.sql`. `test_path_triggers_on_matching_glob`
failed against the first draft; fixed by also trying the pattern against
every path-separator-aligned suffix of the touched path (the same "matches
at any depth without a leading slash" convention `.gitignore`-style tools
already use) — see `project_knowledge.py`'s own docstring on
`_path_triggers`.

**Reviewed, not run at all** — `memory_extraction.py`, the three new
repositories, the new router endpoints, and every line of `agent_loop.py`'s
own changes (the dynamic-section gathering, `_finish_turn`, and the three
call sites now routed through it). No database, no LLM credential were
reachable here, the identical constraint every prior phase's own equivalent
code was under. Read through multiple times end-to-end by hand, cross-
checked against `_execute_call`'s already-shipped conventions
(unscoped-vs-owned repository split, `audit_repo.record`'s category/action
shape) rather than invented fresh.

**Written but needing live Supabase to run** —
`test_rls_isolation.py` gained `TestMemoryAndProjectKnowledgeIsolation` (5
tests: each new table's cross-account isolation, plus one confirming the
new `project_knowledge_injected` event type rides the existing
`session_events` policy with no policy change needed). Same
`conftest.py`-fixture pattern every existing class in that file already
uses; not run here for the same reason none of that file's existing tests
were run by any prior phase either.

**Smoke-test this against real infrastructure before trusting it in
production** — specifically: that a real `call_llm` against each of the two
revision prompts actually produces a plausible `memory_md` (the prompts
were written and reasoned through, never seen a live model's actual output);
that the `session_events.event_type` CHECK-constraint ALTER applies cleanly
against a live Supabase project with existing rows; and the same
Anthropic/OpenAI/Google/OpenRouter/custom-endpoint credential verification
every prior phase's `llm_client.py` note already asks for, now exercised by
two more call sites (`_revise_project_memory`/`_revise_user_memory`) on top
of the turn loop's own.

## Design decisions this phase had to make that the spec excerpt didn't spell out

- **Memory renders in the uncached half of the system prompt, deliberately,
  not fixed.** `/docs/PHASE3_NOTES.md` flagged this as an open question
  ("§17 groups user and project memory with the *static* portion, but
  `system_prompt.py`'s own section order renders `WHAT_YOU_KNOW_ABOUT_*`
  inside the dynamic tail... decide this deliberately while building 4.1").
  Decided: leave it dynamic. Moving it before `REPO_CONTEXT` to gain a cache
  breakpoint would mean memory renders even on a turn where nothing
  triggered a change, and — more importantly — would place genuinely
  per-turn-variable content (a note that just triggered) ahead of it in the
  same breakpoint, defeating the cache the same way `/docs/PHASE3_NOTES.md`
  already reasoned a mid-stream insertion would. `what_you_know_about_this_*`
  changes at most once per turn (after extraction) and `project_knowledge`
  changes whenever a note first triggers — neither is `REPO_CONTEXT`-stable
  within a turn, let alone session-stable, so neither is a good caching
  candidate regardless of position. Revisit only if a future phase's real
  usage shows the caching loss actually matters in practice.
- **"A file the agent touches" (§21's keyword trigger) is read as the file's
  *path*, not its content.** See `project_knowledge.py`'s own docstring for
  the full reasoning — `viewed_paths` is an existing, cheap, already-
  reconstructed signal; scanning viewed/created file content for a keyword
  substring on every tool result has no precedent anywhere in this codebase
  and would be real ongoing per-file work for a benefit §21's own wording
  doesn't clearly ask for.
- **A note stays in the prompt for exactly the one iteration it first
  triggers, not for the rest of the session.** The system prompt is rebuilt
  from scratch every iteration (`system_prompt.assemble` takes no history);
  nothing carries a dynamic section's text forward except the conversation
  transcript itself, which `project_knowledge_injected` deliberately doesn't
  join (see below). So "only ever injected once per session" is read
  literally: injected once, not "injected once, then kept." This matches
  §21's own "rather than permanently bloating every system prompt" framing
  better than the alternative (rendering it once, then re-rendering it on
  every later iteration of the same session, which is closer to the
  permanent-bloat problem §21 says this design avoids).
- **`project_knowledge_injected` is a new, silent `session_events` type,
  never rendered into the model-facing message list.**
  `message_builder.build_messages`'s own fallthrough branch already skips
  any `event_type` it doesn't explicitly handle (see that module's
  docstring) — confirmed by reading it, not assumed — so this was the
  cheapest way to get crash-durable, resume-safe "already triggered"
  tracking without inventing a second, parallel piece of session state.
  The alternative (tracking triggered ids only in `_run_inner`'s own local
  variables) would silently break the very first time a session's turn loop
  restarts after a `completed`/`stuck`/crash pause — exactly the pattern
  `_reconstruct_viewed_paths` and `crash_recovery.py` already exist to
  avoid for other per-session facts.
- **`_latest_user_text` was factored out of `_extract_keywords`** rather
  than duplicated — repo_map's ranking and §21's keyword trigger both need
  "what did the person just ask for," and giving them independently-
  maintained copies of the same five-line scan was the kind of drift this
  codebase's own `_record_tool_audit`/`_audit_labels` split (Phase 3) was
  written specifically to prevent for a different pair of call sites.
- **`_finish_turn` centralizes all three completed/stuck exits.** Before
  this phase, `agent_loop.py` had three separate, textually-identical
  `update_fields`+`_broadcast_done` pairs (the no-tool-calls branch, the
  hard-stop branch, the iteration-ceiling branch). Adding memory extraction
  to all three independently would have meant either three separate calls
  to `memory_extraction.extract_after_turn` (real risk of the same "which
  exit points are actually terminal" drift `_finish_turn` now prevents by
  construction) or accepting that a future fourth exit point might be added
  without the extraction call. `waiting_approval` exits and the `failed`
  exits (LlmCallFailedError, NoLlmCredentialError, `_run`'s own outer
  catch-all) deliberately do **not** go through `_finish_turn` — §20 says
  "completed or stuck," not "any turn that stops."
- **`project_memory_log` is deliberately excluded from every router this
  phase adds.** §20 draws a firm line — "the log exists so the index can be
  rebuilt... never itself injected into any prompt" — and separately says
  "view, edit, or clear **both memory stores**," naming `project_memory` and
  `build_user_memory` specifically, not the log. `clear_project_memory`/
  `clear_account_memory` reset `memory_md` to `""` and leave the log
  completely untouched for exactly this reason — see
  `project_memory.clear_owned`'s own docstring.
- **Clearing memory returns `200` with the now-empty body, not a bare
  `204`.** Every other DELETE in this codebase (a project, a secret) removes
  a row outright and has nothing left worth returning. Clearing memory
  resets content on a row that still exists — there's a real, useful answer
  to "what does it look like now," so this router deliberately deviates from
  the bare-204 convention here. Documented inline at both call sites
  (`routers/projects.py`, `routers/account.py`) so it doesn't read as an
  oversight later.
- **The two revision LLM calls reuse the turn's own already-resolved
  credential**, never re-resolving one. §20 says "the project's own resolved
  LLM credential" for the project-tier call and doesn't name a different one
  for the account-tier call — re-resolving would just re-fetch the identical
  `ResolvedCredential` `agent_loop.py` already has in scope at every
  `_finish_turn` call site, at the cost of an extra DB round trip and vault
  read for no behavioral difference.
- **No retry inside `memory_extraction.py`.** §16.3's three-attempt
  exponential backoff already lives inside `llm_client.call_llm` itself —
  wrapping that in a second retry loop here would just re-run an
  already-exhausted policy on top of itself. A failed extraction call is
  simply skipped for that turn; the next completed/stuck turn tries again
  with a fresh call.

## Rough edges (same spirit as every prior phase's own section)

1. **No frontend affordance for reordering, previewing which note would
   trigger on a hypothetical task, or bulk-editing Project Knowledge notes**
   — the Settings panel is plain create/list/delete, matching Project
   Secrets' own level of polish in the same file. A person with many notes
   has no way to see "which of these would fire right now" without actually
   running a session.
2. **`memory_extraction.py`'s two revision calls run with no tools and no
   system prompt of its own** (a bare `{"role": "user", "content": prompt}`
   list, the same shape `_run_compaction`'s own auxiliary call already
   uses) — reasonable for a single-turn extraction task, but means neither
   call benefits from `_apply_prompt_caching` at all (that function only
   ever looks for `system_prompt.assemble_static()`'s own exact text as the
   first message, which these calls never send). Not a correctness issue —
   these are infrequent, single-message calls, not a per-iteration cost the
   way the turn loop's own `call_llm` is — but worth knowing if the ratio
   of memory-extraction calls to real turn-loop calls is ever high enough
   to matter.
3. **A person editing `project_memory`/`build_user_memory` by hand while a
   session is mid-turn can have their edit silently overwritten** the next
   time that turn's own extraction step runs (`_revise_project_memory`/
   `_revise_user_memory` read-then-write with no version check against a
   concurrent human edit). §20 doesn't describe any locking or
   conflict-detection for this case, and Phase 1's own `sessions_repo`
   pattern generally doesn't version rows either — flagged rather than
   silently accepted, since it's a real, if narrow, race.
4. **`enforce_char_budget`'s truncation point is a plain `rfind` for the
   last `"\n\n"` before budget, with no Markdown-structure awareness** — it
   can still truncate mid-list-item or mid-code-fence if the model's own
   response happens to lack a paragraph break in the right place. Accepted
   because this path should be rare in practice (the soft 4,000-character
   target given to the model is well under `MEMORY_HARD_CAP`'s 8,000, so a
   well-behaved model response essentially never reaches the defensive
   cut at all) and because a slightly-rough truncation boundary is still a
   better failure mode than an unbounded, ever-growing prompt.
5. **`get_project_memory`/`list_project_knowledge` (and their `_owned`
   repository counterparts) do one extra `get_for_user` round trip to check
   project ownership before their real read** — the same shape
   `project_secrets_repo.list_for_project` already uses, so not a new
   pattern, but worth naming as the reason these endpoints are each two
   queries rather than one relying on RLS alone to scope the result (§5's
   own "defense in depth, not instead of" reasoning, applied consistently).

## Fixes applied after review

Two real issues turned up on a second pass, both in code this file's first
version had marked "reviewed, not run at all" — neither was caught by the
pure-module test suite because both live in the integration code the
no-network sandbox couldn't execute either.

1. **PROJECT_KNOWLEDGE was disappearing from the model's context one
   iteration after a note triggered — a real functional bug, not just a
   documentation gap.** The first version built the dynamic section from
   `select_newly_triggered`'s own return value alone. Since `already_
   triggered_ids` (reconstructed fresh from the event log every iteration)
   includes a note the moment its bookkeeping event is written, that note
   is excluded from `select_newly_triggered`'s result on every subsequent
   iteration — and since `message_builder.build_messages` deliberately
   skips rendering `project_knowledge_injected` events as conversation
   content, the note's body text had no other path back to the model. Net
   effect: a triggered note was visible to the model for exactly one LLM
   call, then gone for the rest of the session, despite remaining
   permanently marked "already triggered" (so it could never fire again
   either). This defeated the actual point of the feature — the example in
   §21 itself ("files under `migrations/` follow the naming convention...")
   is exactly the kind of guidance the agent needs available for every
   migration file it touches for the rest of the session, not just the one
   iteration it happened to view the first one.

   Fixed by adding `project_knowledge.select_all_triggered(notes,
   already_triggered_ids, newly_triggered)`, which returns every note
   triggered so far this session (the union of both), and having
   `agent_loop.py` render *that* into PROJECT_KNOWLEDGE each iteration
   instead of `newly_triggered` alone. `select_newly_triggered` is
   unchanged and still does exactly what it did before — decide what's
   genuinely new this iteration, so the bookkeeping event and the
   once-per-session trigger rule stay correct. Six new tests in
   `test_project_knowledge.py` cover `select_all_triggered` directly,
   including the exact regression case (nothing triggers this iteration,
   but something triggered on an earlier one — it must still render).

2. **`project_knowledge_repo.update_owned` never stamped `updated_at`.**
   Same gap `sessions_repo.update_fields`'s own docstring already names for
   `sessions` — 0007's tables have no update trigger for that column, so
   without an explicit stamp on every write, `ProjectKnowledgeOut.updated_at`
   (returned to the API) would show a note's original creation time forever,
   even after real edits via `PATCH /projects/{id}/knowledge/{note_id}`.
   Fixed the same way `sessions_repo.update_fields` already does: stamp
   `updated_at` explicitly in the payload. `project_memory.set_memory_md`
   and `build_user_memory.set_memory_md` had the identical gap on their
   upsert path (an upsert's ON CONFLICT only touches columns present in the
   payload, so the column's own `default now()` never fires on an update)
   — fixed the same way for consistency, even though neither `ProjectMemoryOut`
   nor `BuildUserMemoryOut` currently exposes `updated_at` to the API.

## What Phase 4.3 (and later) needs to know

- **Connector integration (4.3) is unaffected by anything here** — this
  phase touched no MCP/connector code path at all.
- **`_finish_turn` is now the one place to extend if a future phase needs
  its own "turn genuinely ended" hook** (a scheduled run's own completion
  handling, §26/4.5, is the obvious next candidate — a scheduled session
  still ends in `completed`/`stuck` through the exact same three call sites
  this phase already centralized, so its memory extraction should already
  work with zero changes once 4.5 exists; verify this rather than assuming
  it when 4.5 is built).
- **`audit_log.tool`'s vocabulary comment** (`0005_sessions.sql`, edited
  comment-only, consistent with the precedent Phase 3's own "Pre-Phase-4
  cleanup" section set) now includes `'memory'` for every person-triggered
  view/edit/clear of either memory store or a Project Knowledge note.
  Anything Phase 4.3+ adds that writes its own audit rows should follow the
  same category/action shape (`tool` = category, `action` = the specific
  name) `_record_tool_audit`/this phase's router handlers both already use.
- **Both new pure modules (`memory.py`, `project_knowledge.py`) have zero
  imports of `httpx`/`fastapi`/`supabase`/`app.config`/`app.db`**, same
  discipline every prior phase's own decision modules keep — extend them
  that way rather than folding new decision logic into `agent_loop.py` or
  `memory_extraction.py` directly, per `/docs/PHASE3_NOTES.md`'s own closing
  note on this.
